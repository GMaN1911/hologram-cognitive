"""
Hologram Router for Claude-Cognitive

Drop-in replacement for context-router-v2.py.
Uses coordinate-based system with auto-discovered DAG.

Usage:
    router = HologramRouter.from_directory('.claude/')
    context = router.process_query("work on orin sensory")
    injection = router.get_injection_text()
"""

import os
import json
import time
import math
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple, Any

from .system import (
    CognitiveSystem,
    CognitiveFile,
    TurnRecord,
    process_turn,
    get_context,
    get_bucket_distribution,
)
from .dag import EdgeDiscoveryConfig, summarize_dag
from .pressure import PressureConfig, get_pressure_stats
from .coordinates import HOT_THRESHOLD, WARM_THRESHOLD


@dataclass
class InjectionConfig:
    """Configuration for context injection."""
    
    # What to inject
    hot_full_content: bool = True       # Inject full content for HOT files
    warm_header_lines: int = 25         # Lines to inject for WARM files (0 = skip)
    cold_skip: bool = True              # Skip COLD files entirely
    
    # Limits
    max_hot_files: int = 10             # Max HOT files to inject
    max_warm_files: int = 15            # Max WARM files to inject
    max_total_chars: int = 100000       # Hard limit on total injection size
    
    # Formatting
    include_coordinates: bool = True    # Show (system, pressure) in output
    include_tier_markers: bool = True   # Show 🔥/🌡️/❄️ markers
    separator: str = "\n---\n"          # Between files


@dataclass
class HologramRouter:
    """
    Main router class for claude-cognitive integration.
    
    Replaces context-router-v2.py with coordinate-based system.
    """
    system: CognitiveSystem
    injection_config: InjectionConfig = field(default_factory=InjectionConfig)
    
    # State file paths
    state_file: str = ""
    history_file: str = ""
    
    # Instance tracking
    instance_id: str = "default"
    
    @classmethod
    def from_directory(
        cls,
        claude_dir: str,
        file_patterns: Optional[List[str]] = None,
        instance_id: Optional[str] = None,
    ) -> 'HologramRouter':
        """
        Create router from .claude/ directory.
        
        Args:
            claude_dir: Path to .claude/ directory
            file_patterns: Glob patterns for files to include (default: ['**/*.md'])
            instance_id: Instance identifier (default: from env or 'default')
        
        Returns:
            Configured HologramRouter
        """
        if file_patterns is None:
            file_patterns = ['**/*.md']
        
        if instance_id is None:
            instance_id = os.environ.get('CLAUDE_INSTANCE', 'default')
        
        claude_path = Path(claude_dir)
        
        # Find all matching files
        files = {}
        for pattern in file_patterns:
            for filepath in claude_path.glob(pattern):
                if filepath.is_file():
                    rel_path = str(filepath.relative_to(claude_path))
                    try:
                        content = filepath.read_text(encoding='utf-8')
                        files[rel_path] = content
                    except Exception as e:
                        print(f"Warning: Could not read {filepath}: {e}")

        # Create system with batch loading + DAG caching
        # First load: O(n²) DAG build. Subsequent loads: instant from cache
        dag_cache = str(claude_path / '.hologram_dag_cache.json')
        system = CognitiveSystem()
        system.add_files_batch(files, dag_cache_path=dag_cache)
        
        # Create router
        router = cls(
            system=system,
            instance_id=instance_id,
            state_file=str(claude_path / 'hologram_state.json'),
            history_file=str(claude_path / 'hologram_history.jsonl'),
        )
        
        # Try to load existing state
        router.load_state()
        
        return router
    
    def process_query(self, query: str) -> TurnRecord:
        """
        Process a user query.
        
        Finds activated files, propagates pressure, applies decay.
        
        Args:
            query: User's query text
        
        Returns:
            TurnRecord with details of what happened
        """
        record = process_turn(self.system, query)
        
        # Auto-save state
        self.save_state()
        self.append_history(record)
        
        return record
    
    def _calculate_hop_distance(self, file_path: str, query_hit_paths: Set[str]) -> int:
        """
        Calculate minimum hop distance from query-hit files using BFS.

        Args:
            file_path: File to calculate distance for
            query_hit_paths: Set of files that directly matched query

        Returns:
            Minimum hop distance (0 for query hits, 999 if unreachable)
        """
        if file_path in query_hit_paths:
            return 0

        visited = set()
        queue = [(path, 0) for path in query_hit_paths]
        visited.update(query_hit_paths)

        while queue:
            current, dist = queue.pop(0)

            # Check neighbors (both directions)
            neighbors = set()
            neighbors.update(self.system.adjacency.get(current, set()))

            # Incoming edges (use stored incoming_edges, not O(n²) scan)
            if current in self.system.files:
                neighbors.update(self.system.files[current].incoming_edges)

            for neighbor in neighbors:
                if neighbor == file_path:
                    return dist + 1
                if neighbor not in visited:
                    visited.add(neighbor)
                    # Limit to 3 hops
                    if dist + 1 < 3:
                        queue.append((neighbor, dist + 1))

        return 999  # Not reachable within 3 hops

    def _is_hub(self, file_path: str, threshold: int = 15) -> bool:
        """
        Check if file is a hub by in-degree.

        Args:
            file_path: File to check
            threshold: In-degree threshold for hub status

        Returns:
            True if file is a hub
        """
        in_degree = len(self.system.files[file_path].incoming_edges)
        return in_degree >= threshold

    def _calculate_injection_priority(
        self,
        file: 'CognitiveFile',
        activated_paths: Set[str],
        query_hit_paths: Set[str],
        top_k: int = 3,
        hop_lambda: float = 0.7
    ) -> Tuple[float, float, int]:
        """
        Calculate injection priority with non-saturating aggregate.

        Priority = pressure × top_k_mean_weight × exp(-lambda × hop_distance)

        This prevents saturation in dense SCCs by:
        1. Using top-k mean instead of max (rewards multiple strong connections)
        2. Adding hop-based decay (penalizes long chains)
        3. Supporting edge_trust multiplier (usage validation, future)

        Args:
            file: File to calculate priority for
            activated_paths: Set of paths that were recently activated
            query_hit_paths: Set of paths that directly matched query
            top_k: Number of top edges to average (default 3)
            hop_lambda: Decay rate for hop distance (default 0.7)

        Returns:
            (priority, aggregate_weight, hop_distance) tuple
        """
        pressure = file.raw_pressure

        # Collect all edge weights to activated files
        weights = []

        # Outgoing edges (file → activated)
        for target_path in file.outgoing_edges:
            if target_path in activated_paths:
                weight = self.system.edge_weights.get(file.path, {}).get(target_path, 1.0)
                # Apply edge trust (future: learned from usage)
                edge_trust = getattr(self.system, 'edge_trust', {}).get(file.path, {}).get(target_path, 1.0)
                weights.append(weight * edge_trust)

        # Incoming edges (activated → file)
        for source_path in file.incoming_edges:
            if source_path in activated_paths:
                weight = self.system.edge_weights.get(source_path, {}).get(file.path, 1.0)
                edge_trust = getattr(self.system, 'edge_trust', {}).get(source_path, {}).get(file.path, 1.0)
                weights.append(weight * edge_trust)

        # Aggregate: top-k mean (non-saturating)
        if weights:
            weights_sorted = sorted(weights, reverse=True)
            top_weights = weights_sorted[:min(top_k, len(weights_sorted))]
            aggregate_weight = sum(top_weights) / len(top_weights)
        else:
            aggregate_weight = 0.0

        # Hop-based decay
        hop_distance = self._calculate_hop_distance(file.path, query_hit_paths)
        hop_decay = math.exp(-hop_lambda * hop_distance)

        # Final priority
        priority = pressure * aggregate_weight * hop_decay

        return priority, aggregate_weight, hop_distance

    def get_injection_text(self) -> str:
        """
        Get formatted text for context injection with edge-weighted prioritization.

        Uses refined tiered injection:
        - Tier 1 (Critical): 0-1 hop, priority > 1.5, full content (80% budget)
        - Tier 2 (High): 2 hop, priority > 1.0, headers only (20% budget)
        - Tier 3 (Medium): 3+ hop, priority > 0.5, listed only

        Features:
        - Top-k mean aggregate (non-saturating in dense SCCs)
        - Hop-based decay (penalizes long chains)
        - Hub governance (caps high in-degree files in Tier 1)
        - Reserved header budget (prevents full-content waste)

        Returns:
            Formatted string ready for injection into prompt
        """
        context = get_context(self.system)
        config = self.injection_config

        # Get recently activated files AND query-hit files
        activated_paths = set()
        query_hit_paths = set()
        if self.system.history:
            last_turn = self.system.history[-1]
            activated_paths = set(last_turn.activated)
            # Query hits are files activated in the last turn
            # (In future: could track lexical matches separately)
            query_hit_paths = activated_paths.copy()

        # Calculate priorities for all non-COLD files
        files_with_priority = []
        for file in context['HOT'] + context['WARM']:
            priority, aggregate_weight, hop_distance = self._calculate_injection_priority(
                file, activated_paths, query_hit_paths
            )
            files_with_priority.append({
                'file': file,
                'priority': priority,
                'aggregate_weight': aggregate_weight,
                'hop_distance': hop_distance,
                'is_hub': self._is_hub(file.path),
            })

        # Sort by priority (highest first)
        files_with_priority.sort(key=lambda x: x['priority'], reverse=True)

        # Build separate tier lists
        critical = [(f, p) for f, p in [(item['file'], item['priority']) for item in files_with_priority]
                    if p > 1.5]
        high = [(f, p) for f, p in [(item['file'], item['priority']) for item in files_with_priority]
                if 1.0 < p <= 1.5]
        medium = [(f, p) for f, p in [(item['file'], item['priority']) for item in files_with_priority]
                  if 0.5 < p <= 1.0]

        # Reserve 20% budget for headers
        full_content_budget = int(config.max_total_chars * 0.8)
        header_budget = int(config.max_total_chars * 0.2)

        parts = []
        full_chars = 0
        header_chars = 0
        already_injected = set()

        # Header
        hot_count = len(context['HOT'])
        warm_count = len(context['WARM'])
        cold_count = len(context['COLD'])

        parts.append(f"ATTENTION STATE [Turn {self.system.current_turn}]")
        parts.append(f"Instance: {self.instance_id}")
        parts.append(f"🔥 HOT: {hot_count} | 🌡️ WARM: {warm_count} | ❄️ COLD: {cold_count}")
        parts.append("")

        # Tier 1: Critical files (full content, 80% budget)
        # Apply hub governance: limit hubs in Tier 1
        hubs_in_tier1 = 0
        max_hubs_tier1 = 2

        if critical and config.hot_full_content:
            for file, priority in critical[:config.max_hot_files]:
                if full_chars >= full_content_budget:
                    break

                # Hub governance
                file_path = file.path
                if self._is_hub(file_path):
                    if hubs_in_tier1 >= max_hubs_tier1:
                        # Push hub to Tier 2 instead
                        high.insert(0, (file, priority))
                        continue
                    hubs_in_tier1 += 1

                header_text = self._format_file_header(file, "🔥 CRITICAL", priority)
                content = file.content.strip()

                estimated_chars = len(header_text) + len(content)
                if full_chars + estimated_chars > full_content_budget:
                    break

                parts.append(header_text)
                parts.append(content)
                parts.append("")

                full_chars += estimated_chars
                already_injected.add(file_path)

        # Tier 2: High priority files (headers only, 20% budget)
        if high and config.warm_header_lines > 0:
            for file, priority in high[:config.max_warm_files]:
                if file.path in already_injected:
                    continue
                if header_chars >= header_budget:
                    break

                header_text = self._format_file_header(file, "⭐ HIGH", priority)
                lines = file.content.strip().split('\n')
                preview = '\n'.join(lines[:config.warm_header_lines])
                if len(lines) > config.warm_header_lines:
                    preview += f"\n[... {len(lines) - config.warm_header_lines} more lines]"

                estimated_chars = len(header_text) + len(preview)
                if header_chars + estimated_chars > header_budget:
                    break

                parts.append(header_text)
                parts.append(preview)
                parts.append("")

                header_chars += estimated_chars
                already_injected.add(file.path)

        # Tier 3: Medium priority files (list only)
        medium_not_injected = [(f, p) for f, p in medium if f.path not in already_injected]
        if medium_not_injected:
            parts.append(f"📋 MEDIUM PRIORITY ({len(medium_not_injected)} files):")
            for file, priority in medium_not_injected[:10]:
                parts.append(f"  - {file.path} (priority: {priority:.2f})")
            if len(medium_not_injected) > 10:
                parts.append(f"  ... and {len(medium_not_injected) - 10} more")
            parts.append("")

        # COLD summary
        if not config.cold_skip and context['COLD']:
            parts.append(f"❄️ COLD ({len(context['COLD'])} files):")
            for file in context['COLD'][:10]:
                parts.append(f"  - {file.path}")
            if len(context['COLD']) > 10:
                parts.append(f"  ... and {len(context['COLD']) - 10} more")

        return '\n'.join(parts)
    
    def _format_file_header(self, file: CognitiveFile, tier_marker: str, priority: float = None) -> str:
        """Format file header for injection."""
        config = self.injection_config

        parts = [f"### {file.path}"]

        if config.include_tier_markers:
            parts[0] = f"{tier_marker} {parts[0]}"

        if config.include_coordinates:
            coord_str = f"Coordinate: ({file.system_bucket}, {file.pressure_bucket})"
            if priority is not None:
                coord_str += f", Priority: {priority:.2f}"
            parts.append(coord_str)

        if file.outgoing_edges:
            edges = list(file.outgoing_edges)[:5]
            parts.append(f"Links to: {', '.join(edges)}")
            if len(file.outgoing_edges) > 5:
                parts[-1] += f" (+{len(file.outgoing_edges) - 5} more)"

        return '\n'.join(parts)
    
    def get_context_dict(self) -> Dict[str, Any]:
        """
        Get context as structured dict (for JSON output).
        """
        context = get_context(self.system)
        stats = get_pressure_stats(self.system.files)
        
        return {
            'turn': self.system.current_turn,
            'instance_id': self.instance_id,
            'stats': stats,
            'hot': [
                {'path': f.path, 'coordinate': f.coordinate, 'edges': len(f.outgoing_edges)}
                for f in context['HOT']
            ],
            'warm': [
                {'path': f.path, 'coordinate': f.coordinate, 'edges': len(f.outgoing_edges)}
                for f in context['WARM']
            ],
            'cold_count': len(context['COLD']),
        }
    
    def activate_files(self, paths: List[str]):
        """
        Manually activate specific files.
        
        Useful for pinned files or explicit activation.
        """
        process_turn(self.system, "", custom_activated=paths)
    
    def get_dag_summary(self) -> dict:
        """Get summary of discovered DAG structure."""
        return summarize_dag(self.system.adjacency)
    
    def get_bucket_map(self) -> Dict[int, List[str]]:
        """Get mapping of system buckets to files."""
        return get_bucket_distribution(self.system)
    
    def save_state(self):
        """Save current state to file."""
        if not self.state_file:
            return
        
        try:
            state = {
                'current_turn': self.system.current_turn,
                'instance_id': self.instance_id,
                'files': {
                    path: {
                        'pressure_bucket': f.pressure_bucket,
                        'raw_pressure': f.raw_pressure,
                        'last_activated': f.last_activated,
                        'activation_count': f.activation_count,
                    }
                    for path, f in self.system.files.items()
                }
            }
            
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save state: {e}")
    
    def load_state(self):
        """Load state from file if exists."""
        if not self.state_file or not os.path.exists(self.state_file):
            return
        
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
            
            self.system.current_turn = state.get('current_turn', 0)
            
            # Restore pressure state for existing files
            for path, file_state in state.get('files', {}).items():
                if path in self.system.files:
                    file = self.system.files[path]
                    file.pressure_bucket = file_state.get('pressure_bucket', 10)
                    file.raw_pressure = file_state.get('raw_pressure', 0.2)
                    file.last_activated = file_state.get('last_activated', 0)
                    file.activation_count = file_state.get('activation_count', 0)
        except Exception as e:
            print(f"Warning: Could not load state: {e}")
    
    def append_history(self, record: TurnRecord):
        """Append turn record to history file."""
        if not self.history_file:
            return
        
        try:
            with open(self.history_file, 'a') as f:
                entry = record.to_dict()
                entry['instance_id'] = self.instance_id
                f.write(json.dumps(entry) + '\n')
        except Exception as e:
            print(f"Warning: Could not append history: {e}")


def create_router_from_directory(
    claude_dir: str,
    **kwargs
) -> HologramRouter:
    """
    Convenience function to create router from directory.
    
    Args:
        claude_dir: Path to .claude/ directory
        **kwargs: Additional arguments for HologramRouter.from_directory
    
    Returns:
        Configured HologramRouter
    """
    return HologramRouter.from_directory(claude_dir, **kwargs)


# ============================================================
# CLI COMPATIBILITY (for hook integration)
# ============================================================

def main():
    """
    CLI entry point for hook integration.
    
    Reads query from stdin or args, outputs injection to stdout.
    Compatible with claude-cognitive hooks.
    """
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='Hologram Cognitive Router')
    parser.add_argument('--claude-dir', default='.claude/', help='Path to .claude directory')
    parser.add_argument('--query', help='Query to process')
    parser.add_argument('--json', action='store_true', help='Output JSON instead of text')
    parser.add_argument('--dag-summary', action='store_true', help='Show DAG summary')
    parser.add_argument('--bucket-map', action='store_true', help='Show bucket distribution')
    
    args = parser.parse_args()
    
    # Get query from args or stdin
    query = args.query
    if not query and not sys.stdin.isatty():
        query = sys.stdin.read().strip()
    
    # Create router
    router = HologramRouter.from_directory(args.claude_dir)
    
    # Handle special commands
    if args.dag_summary:
        summary = router.get_dag_summary()
        print(json.dumps(summary, indent=2, default=list))
        return
    
    if args.bucket_map:
        buckets = router.get_bucket_map()
        for bucket in sorted(buckets.keys()):
            print(f"\nBucket {bucket}:")
            for path in buckets[bucket]:
                print(f"  {path}")
        return
    
    # Process query
    if query:
        router.process_query(query)
    
    # Output
    if args.json:
        print(json.dumps(router.get_context_dict(), indent=2))
    else:
        print(router.get_injection_text())


if __name__ == '__main__':
    main()
