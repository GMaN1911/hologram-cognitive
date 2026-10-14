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
import sys
import json
import time
import math
from pathlib import Path
from fnmatch import fnmatch
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple, Any
from collections import deque

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
from .route_policy import demotion_factor


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
    # Opt-in for existing router callers; MCP explicitly uses ProjectConfig.
    demote_patterns: List[str] = field(default_factory=list)
    demote_factor: float = 0.1
    demote_release_tokens: List[str] = field(default_factory=lambda: [
        'fixture', 'fixtures', '__fixtures__', 'eval_fixtures', 'testdata', 'test data',
    ])
    last_query: Optional[str] = None
    
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
        state_dir: Optional[str] = None,
    ) -> 'HologramRouter':
        """
        Create router from a directory.

        Args:
            claude_dir: Directory to SCAN forward for files (a project root, or .claude/)
            file_patterns: Glob patterns for files to include (default: ['**/*.md'])
            instance_id: Instance identifier (default: from env or 'default')
            state_dir: Where to keep state (content cache, DAG cache, hologram_state.json,
                history). Defaults to claude_dir (legacy layout: state in the scanned dir).
                Pass a separate dir (e.g. <project>/.hologram) to scan a project root
                forward while keeping state out of the project tree.

        Returns:
            Configured HologramRouter
        """
        if file_patterns is None:
            file_patterns = ['**/*.md']

        if instance_id is None:
            instance_id = os.environ.get('CLAUDE_INSTANCE', 'default')

        claude_path = Path(claude_dir)   # scan root (walked forward)
        # State location. Legacy (state_dir=None): dag/state in the scanned dir, content
        # cache in <scanned>/.hologram. Separated (state_dir given): everything flat in it.
        if state_dir:
            state_path = Path(state_dir)
            state_path.mkdir(parents=True, exist_ok=True)
            content_cache_dir = state_path
            # a project 0.4's hook learned keeps its state at the root: carry it over, once
            from .migrate import adopt_legacy_layout
            for line in adopt_legacy_layout(claude_path, state_path):
                print(f"[migrate] {line}", file=sys.stderr)
        else:
            state_path = claude_path
            content_cache_dir = claude_path / '.hologram'

        # The ignore list is the route policy's (hologram/route_policy.py), the one the MCP
        # project scanner reads too, so the two never drift.
        from . import route_policy
        default_ignores = list(route_policy.DEFAULT_IGNORES)

        extra_excludes: List[str] = ["plugins/cache/**"]
        exclude_file = claude_path / ".hologram_exclude"
        if exclude_file.exists():
            try:
                for line in exclude_file.read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        extra_excludes.append(line)
            except Exception as e:
                print(f"Warning: Could not read .hologram_exclude: {e}")

        exclude_patterns = default_ignores + extra_excludes

        # Pre-extract the bare-name forms of each ignore pattern once, so nested
        # vendor trees like `t3v2/.venv` get pruned just like top-level `.venv`.
        bare_ignores = [p[:-3] for p in exclude_patterns if p.endswith('/**')]

        def _dir_ignored(rel_dir: str) -> bool:
            if not rel_dir:
                return False
            basename = os.path.basename(rel_dir.rstrip('/'))
            probe_slash = rel_dir + '/'
            for pat in exclude_patterns:
                if fnmatch(probe_slash, pat) or fnmatch(rel_dir, pat):
                    return True
                if pat.endswith('/**') and fnmatch(rel_dir, pat[:-3]):
                    return True
            for bare in bare_ignores:
                if fnmatch(basename, bare):
                    return True
            return False

        def _file_matches_pattern(rel_path: str, fname: str, patterns: List[str]) -> bool:
            for p in patterns:
                if fnmatch(rel_path, p):
                    return True
                # '**/*.md' style — match basename too for files at any depth
                tail = p.rsplit('/', 1)[-1]
                if fnmatch(fname, tail):
                    return True
            return False

        # Content cache: sidesteps re-read_text() of unchanged files on each
        # router init. files.json already records {size, mtime, hash} but not
        # content; we keep content in its own sidecar so files.json stays lean.
        cache_dir = content_cache_dir
        cache_path = cache_dir / 'content_cache.json'
        content_cache: Dict[str, dict] = {}
        if cache_path.exists():
            try:
                content_cache = json.loads(cache_path.read_text()) or {}
            except Exception as e:
                print(f"Warning: Could not read content_cache.json: {e}")
                content_cache = {}

        # Walk with in-place dir pruning: never descend into .venv/node_modules.
        # This is the fix for the hang — Path.glob('**/*.md') had no way to
        # skip ignored subtrees.
        files: Dict[str, str] = {}
        new_cache: Dict[str, dict] = {}
        cache_hits = 0
        cache_misses = 0
        for dirpath, dirnames, filenames in os.walk(claude_path):
            rel_dir = os.path.relpath(dirpath, claude_path)
            if rel_dir == '.':
                rel_dir = ''
            dirnames[:] = [
                d for d in dirnames
                if not _dir_ignored(os.path.join(rel_dir, d) if rel_dir else d)
            ]
            for fname in filenames:
                rel_path = os.path.join(rel_dir, fname) if rel_dir else fname
                if not _file_matches_pattern(rel_path, fname, file_patterns):
                    continue
                if any(fnmatch(rel_path, p) for p in extra_excludes):
                    continue
                full = Path(dirpath) / fname
                try:
                    st = full.stat()
                except OSError as e:
                    print(f"Warning: Could not stat {full}: {e}")
                    continue
                mtime = st.st_mtime
                size = st.st_size
                cached = content_cache.get(rel_path)
                if (
                    cached
                    and cached.get('mtime') == mtime
                    and cached.get('size') == size
                    and 'content' in cached
                ):
                    files[rel_path] = cached['content']
                    new_cache[rel_path] = cached
                    cache_hits += 1
                    continue
                try:
                    content = full.read_text(encoding='utf-8')
                except Exception as e:
                    print(f"Warning: Could not read {full}: {e}")
                    continue
                files[rel_path] = content
                new_cache[rel_path] = {'mtime': mtime, 'size': size, 'content': content}
                cache_misses += 1

        # Persist cache. Pruned entries for deleted files drop naturally since
        # we rebuild from `new_cache`, not mutate in place.
        if new_cache != content_cache:
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(new_cache))
            except Exception as e:
                print(f"Warning: Could not write content_cache.json: {e}")

        # Create system with batch loading + DAG caching
        # First load: O(n²) DAG build. Subsequent loads: instant from cache
        dag_cache = str(state_path / '.hologram_dag_cache.json')
        system = CognitiveSystem()
        system.add_files_batch(files, dag_cache_path=dag_cache)

        # Route policy — same single source as the ignore list above. A directory-built
        # router is what the hooks run, so the gate must be on here by default: applied at
        # activation (system) and at injection ranking (router).
        from . import route_policy
        demote: Dict[str, Any] = {
            'demote_patterns': list(route_policy.DEMOTE_PATTERNS),
            'demote_factor': route_policy.DEMOTE_FACTOR,
            'demote_release_tokens': list(route_policy.DEMOTE_RELEASE_TOKENS),
        }
        for name, value in demote.items():
            setattr(system, name, value)

        # Create router
        router = cls(
            system=system,
            **demote,
            instance_id=instance_id,
            state_file=str(state_path / 'hologram_state.json'),
            history_file=str(state_path / 'hologram_history.jsonl'),
        )
        
        # Try to load existing state
        router.load_state()
        
        return router
    
    def process_query(self, query: str, extra_scores: Optional[Dict[str, float]] = None) -> TurnRecord:
        """
        Process a user query.
        
        Finds activated files, propagates pressure, applies decay.
        
        Args:
            query: User's query text
        
        Returns:
            TurnRecord with details of what happened
        """
        self.last_query = query
        record = process_turn(self.system, query, None, extra_scores)
        
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

        visited = set(query_hit_paths)
        queue = deque([(path, 0) for path in query_hit_paths])

        while queue:
            current, dist = queue.popleft()

            # Check neighbors (both directions)
            # Outgoing edges
            for neighbor in self.system.adjacency.get(current, set()):
                if neighbor == file_path:
                    return dist + 1
                if neighbor not in visited:
                    visited.add(neighbor)
                    # Limit to 3 hops
                    if dist + 1 < 3:
                        queue.append((neighbor, dist + 1))

            # Incoming edges (use stored incoming_edges, not O(n²) scan)
            if current in self.system.files:
                for neighbor in self.system.files[current].incoming_edges:
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

    def _demotion_factor(self, path: str, query: Optional[str] = None) -> float:
        """Route-quality gate (SUBAGENT_HARNESS_DESIGN.md §17): fixture/test-data trees keep their
        index entry but lose routing priority, unless the query explicitly asks about them.
        Returns 1.0 (no demotion) or the configured factor."""
        return demotion_factor(self, path, query or "")

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
            priority *= self._demotion_factor(file.path, getattr(self, 'last_query', None))
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

    def observe(self, files_used, files_edited=None, query: str = ""):
        """
        Close the route→use→reinforce loop.

        Explicitly activate the files that were ACTUALLY used this turn (not just
        the ones that matched the query) so their pressure rises toward HOT and
        persists. Without this feedback, per-project pressure only ever decays
        (WARM→COLD) and nothing reaches the HOT tier — the "no hot files" bug.

        Args:
            files_used:   files read/touched this turn
            files_edited: files written/edited (weighted same as used here;
                          surfaced separately for future label use)
            query:        the turn's prompt, recorded on the turn for history

        Returns:
            TurnRecord, or None if no observed file belongs to this project.
        """
        seen = list(dict.fromkeys(list(files_used or []) + list(files_edited or [])))
        present = [p for p in seen if p in self.system.files]
        if not present:
            return None
        record = process_turn(self.system, query or "", custom_activated=present)
        self.save_state()
        self.append_history(record)
        return record

    def hold(self, reason: str):
        """Record that something arrived which is not a prompt (hologram/route_policy.py): no
        activation, no decay, no turn. The row keeps "the last turn" honest for its readers:
        the end-of-turn learner would otherwise count the previous prompt's files a second time."""
        if not self.history_file:
            return
        try:
            with open(self.history_file, 'a') as f:
                f.write(json.dumps({
                    'turn': self.system.current_turn, 'timestamp': time.time(), 'query': '',
                    'activated': [], 'propagated': [], 'hot': [], 'warm': [],
                    'held': reason, 'instance_id': self.instance_id,
                }) + '\n')
        except Exception as e:
            print(f"Warning: Could not append history: {e}")

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
            from .migrate import STATE_SCHEMA
            state = {
                'schema': STATE_SCHEMA,
                'current_turn': self.system.current_turn,
                'instance_id': self.instance_id,
                'files': {
                    path: {
                        'pressure_bucket': f.pressure_bucket,
                        'raw_pressure': f.raw_pressure,
                        'last_activated': f.last_activated,
                        'activation_count': f.activation_count,
                        # Without this a router built per prompt (the hook path) forgets every
                        # resurrection, and past turn 100 the cooldown never applies again.
                        'last_resurrected': f.last_resurrected,
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

            # A state from before the fixed budget (0.4, or this tree before 2026-10-03) is
            # migrated once, here, so every surface that loads it gets the same result.
            from .migrate import migrate_state, needs_migration
            if needs_migration(state):
                for line in migrate_state(state, self.state_file, self.system.pressure_config.total_pressure_budget):
                    print(f"[migrate] {line}", file=sys.stderr)
                with open(self.state_file, 'w') as f:
                    json.dump(state, f, indent=2)

            self.system.current_turn = state.get('current_turn', 0)
            
            # Restore pressure state for existing files
            for path, file_state in state.get('files', {}).items():
                if path in self.system.files:
                    file = self.system.files[path]
                    file.pressure_bucket = file_state.get('pressure_bucket', 10)
                    file.raw_pressure = file_state.get('raw_pressure', 0.2)
                    file.last_activated = file_state.get('last_activated', 0)
                    file.activation_count = file_state.get('activation_count', 0)
                    file.last_resurrected = file_state.get('last_resurrected', 0)
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
