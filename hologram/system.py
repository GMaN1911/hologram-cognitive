"""
Cognitive System for Hologram Cognitive

Core data structures and turn processing.
This is the main entry point for the coordinate-based context system.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional, Any
from pathlib import Path
import json
import time

from .coordinates import (
    compute_system_bucket,
    compute_content_signature,
    quantize_pressure,
    get_tier,
    SYSTEM_BUCKETS,
    PRESSURE_BUCKETS,
    HOT_THRESHOLD,
    WARM_THRESHOLD,
)
from .dag import (
    discover_edges,
    build_dag,
    get_incoming_edges,
    compute_edge_weights,
    EdgeDiscoveryConfig,
)
from .pressure import (
    apply_activation,
    propagate_pressure,
    apply_decay,
    redistribute_pressure,
    get_pressure_stats,
    update_basin_state,
    PressureConfig,
)


@dataclass
class CognitiveFile:
    """
    A file in the cognitive coordinate system.
    
    Has two coordinates:
    - system_bucket: Static, content-addressed (where it lives architecturally)
    - pressure_bucket: Dynamic, attention state (how active it is)
    """
    path: str
    content: str = ""
    content_signature: str = ""  # For change detection
    
    # Coordinates
    system_bucket: int = 0
    pressure_bucket: int = 10  # Start in COLD
    raw_pressure: float = 0.2
    
    # DAG relationships
    outgoing_edges: Set[str] = field(default_factory=set)
    incoming_edges: Set[str] = field(default_factory=set)
    
    # Metadata
    last_activated: int = 0
    activation_count: int = 0
    last_resurrected: int = 0  # For toroidal decay cooldown
    created_at: float = field(default_factory=time.time)

    # Basin dynamics (v0.3.0) - attention stickiness
    consecutive_hot_turns: int = 0  # Consecutive turns in HOT tier
    basin_depth: float = 1.0        # 1.0 (shallow) to 2.5 (deep)
    
    @property
    def tier(self) -> str:
        """Get current tier: HOT, WARM, or COLD."""
        return get_tier(self.pressure_bucket)
    
    @property
    def coordinate(self) -> Tuple[int, int]:
        """Get full coordinate (system, pressure)."""
        return (self.system_bucket, self.pressure_bucket)
    
    @property
    def edge_count(self) -> int:
        """Total edges (in + out)."""
        return len(self.outgoing_edges) + len(self.incoming_edges)
    
    def to_dict(self) -> dict:
        """Serialize to dict for JSON storage."""
        return {
            'path': self.path,
            'content_signature': self.content_signature,
            'system_bucket': self.system_bucket,
            'pressure_bucket': self.pressure_bucket,
            'raw_pressure': self.raw_pressure,
            'outgoing_edges': list(self.outgoing_edges),
            'incoming_edges': list(self.incoming_edges),
            'last_activated': self.last_activated,
            'activation_count': self.activation_count,
            # Basin dynamics (v0.3.0)
            'consecutive_hot_turns': self.consecutive_hot_turns,
            'basin_depth': self.basin_depth,
        }
    
    @classmethod
    def from_dict(cls, data: dict, content: str = "") -> 'CognitiveFile':
        """Deserialize from dict."""
        file = cls(
            path=data['path'],
            content=content,
            content_signature=data.get('content_signature', ''),
            system_bucket=data.get('system_bucket', 0),
            pressure_bucket=data.get('pressure_bucket', 10),
            raw_pressure=data.get('raw_pressure', 0.2),
            last_activated=data.get('last_activated', 0),
            activation_count=data.get('activation_count', 0),
            # Basin dynamics (v0.3.0)
            consecutive_hot_turns=data.get('consecutive_hot_turns', 0),
            basin_depth=data.get('basin_depth', 1.0),
        )
        file.outgoing_edges = set(data.get('outgoing_edges', []))
        file.incoming_edges = set(data.get('incoming_edges', []))
        return file


@dataclass
class TurnRecord:
    """Record of a single turn for history."""
    turn: int
    timestamp: float
    query: str
    activated: List[str]
    propagated: List[str]
    hot: List[str]
    warm: List[str]
    cold_count: int
    pressure_stats: dict
    
    def to_dict(self) -> dict:
        return {
            'turn': self.turn,
            'timestamp': self.timestamp,
            'query': self.query,
            'activated': self.activated,
            'propagated': self.propagated,
            'hot': self.hot,
            'warm': self.warm,
            'cold_count': self.cold_count,
            'pressure_stats': self.pressure_stats,
        }


@dataclass
class CognitiveSystem:
    """
    The full cognitive coordinate system.
    
    Manages files, DAG, pressure dynamics, and turn processing.
    """
    files: Dict[str, CognitiveFile] = field(default_factory=dict)
    
    # DAG
    adjacency: Dict[str, Set[str]] = field(default_factory=dict)
    edge_weights: Dict[str, Dict[str, float]] = field(default_factory=dict)
    dynamic_weights: Dict[str, Dict[str, float]] = field(default_factory=dict)
    
    # State
    current_turn: int = 0
    history: List[TurnRecord] = field(default_factory=list)
    
    # Config
    dag_config: EdgeDiscoveryConfig = field(default_factory=EdgeDiscoveryConfig)
    pressure_config: PressureConfig = field(default_factory=PressureConfig)
    
    def add_file(self, path: str, content: str, rebuild_dag: bool = True) -> CognitiveFile:
        """
        Add a file to the system.

        Computes system bucket from content and discovers edges.

        Args:
            path: File path relative to .claude/
            content: File content
            rebuild_dag: If True, rebuild DAG after adding (set False for batch adds)
        """
        file = CognitiveFile(
            path=path,
            content=content,
            content_signature=compute_content_signature(content),
            system_bucket=compute_system_bucket(path, content),
            pressure_bucket=10,  # Start COLD
            raw_pressure=0.2,
        )
        self.files[path] = file

        # Rebuild DAG with new file (skip for batch adds)
        if rebuild_dag:
            self._rebuild_dag()

        return file

    def add_files_batch(self, files: Dict[str, str], dag_cache_path: str = None) -> None:
        """
        Add multiple files at once (much faster than individual adds).

        Only rebuilds DAG once after all files are added.
        With caching, subsequent loads with unchanged files are instant.

        Args:
            files: Dict of path -> content
            dag_cache_path: Path to DAG cache file (enables caching)
        """
        for path, content in files.items():
            self.add_file(path, content, rebuild_dag=False)

        # Single DAG rebuild at the end (with caching if path provided)
        self._rebuild_dag(cache_path=dag_cache_path)
    
    def remove_file(self, path: str):
        """Remove a file from the system."""
        if path in self.files:
            del self.files[path]
            self._rebuild_dag()
    
    def update_file(self, path: str, content: str):
        """Update a file's content (recomputes bucket and edges)."""
        if path in self.files:
            old_signature = self.files[path].content_signature
            new_signature = compute_content_signature(content)

            if old_signature != new_signature:
                # Content changed, update
                file = self.files[path]
                file.content = content
                file.content_signature = new_signature
                file.system_bucket = compute_system_bucket(path, content)
                self._rebuild_dag()
    
    def _compute_dag_cache_key(self) -> str:
        """Compute a cache key from all file signatures."""
        import hashlib
        signatures = sorted(f"{p}:{f.content_signature}" for p, f in self.files.items())
        combined = "|".join(signatures)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def _load_dag_cache(self, cache_path: str) -> bool:
        """Try to load DAG from cache. Returns True if successful."""
        import json
        from pathlib import Path

        cache_file = Path(cache_path)
        if not cache_file.exists():
            return False

        try:
            cache = json.loads(cache_file.read_text())
            if cache.get('cache_key') != self._compute_dag_cache_key():
                return False  # Cache is stale

            # Restore adjacency
            self.adjacency = {k: set(v) for k, v in cache['adjacency'].items()}
            self.edge_weights = cache.get('edge_weights', {})

            # Update file edge sets
            incoming = get_incoming_edges(self.adjacency)
            for path, file in self.files.items():
                file.outgoing_edges = self.adjacency.get(path, set())
                file.incoming_edges = incoming.get(path, set())

            return True
        except Exception:
            return False

    def _save_dag_cache(self, cache_path: str) -> None:
        """Save DAG to cache file."""
        import json
        from pathlib import Path

        cache = {
            'cache_key': self._compute_dag_cache_key(),
            'adjacency': {k: list(v) for k, v in self.adjacency.items()},
            'edge_weights': self.edge_weights,
        }
        Path(cache_path).write_text(json.dumps(cache))

    def _rebuild_dag(self, cache_path: str = None):
        """Rebuild DAG from current file contents (with optional caching)."""
        # Try to load from cache first
        if cache_path and self._load_dag_cache(cache_path):
            return  # Cache hit!

        # Cache miss - rebuild
        content_map = {p: f.content for p, f in self.files.items()}
        self.adjacency = build_dag(content_map, self.dag_config)
        self.edge_weights = compute_edge_weights(content_map, self.adjacency)

        # Update file edge sets
        incoming = get_incoming_edges(self.adjacency)
        for path, file in self.files.items():
            file.outgoing_edges = self.adjacency.get(path, set())
            file.incoming_edges = incoming.get(path, set())

        # Save to cache for next time
        if cache_path:
            self._save_dag_cache(cache_path)

    def update_dynamic_weights(self, activated: List[str], learning_rate: float = 0.1, max_weight: float = 2.0):
        """
        Update dynamic weights based on co-activation.

        Files activated together strengthen their connection.
        """
        if len(activated) < 2:
            return

        for i in range(len(activated)):
            source = activated[i]
            for j in range(len(activated)):
                if i == j:
                    continue
                target = activated[j]

                # Initialize source dict if not present
                if source not in self.dynamic_weights:
                    self.dynamic_weights[source] = {}

                # Increment weight
                current = self.dynamic_weights[source].get(target, 0.0)
                new_weight = min(max_weight, current + learning_rate)
                self.dynamic_weights[source][target] = new_weight

    def get_effective_weights(self) -> Dict[str, Dict[str, float]]:
        """
        Get effective edge weights (static + dynamic).

        Dynamic weights boost static weights or create new edges.
        """
        # Start with static weights (deep copy to avoid modifying original)
        effective = {}
        for src, targets in self.edge_weights.items():
            effective[src] = targets.copy()

        # Merge dynamic weights
        for source, targets in self.dynamic_weights.items():
            if source not in effective:
                effective[source] = {}

            for target, weight in targets.items():
                # Add to existing static weight or create new edge
                static = effective[source].get(target, 0.0)
                effective[source][target] = static + weight

        return effective
    
    def find_activated(self, query: str) -> Dict[str, float]:
        """
        Find files activated by a query with activation scores.

        Returns dict of path → score where score reflects match quality:
        - Multiple keyword matches stack (more matches = higher score)
        - Title/path matches weighted higher than content matches
        - Partial/prefix matches contribute smaller scores

        Returns:
            Dict mapping file paths to activation scores (0.0 = not activated)
        """
        scores: Dict[str, float] = {}
        query_lower = query.lower()
        words = [w for w in query_lower.split() if len(w) > 2]

        if not words:
            return scores

        for path, file in self.files.items():
            score = 0.0
            path_lower = path.lower()
            content_lower = file.content.lower()

            # Extract title (first # line) for higher-weight matching
            title_lower = ""
            for line in file.content.split('\n')[:5]:
                if line.startswith('#'):
                    title_lower = line.lower()
                    break

            for word in words:
                # Exact match in path/filename: +1.0 (highest priority)
                if word in path_lower:
                    score += 1.0
                # Exact match in title: +0.8
                elif title_lower and word in title_lower:
                    score += 0.8
                # Exact match in content: +0.4
                elif word in content_lower:
                    score += 0.4
                # Partial/prefix match (4+ char prefix): +0.2
                elif len(word) >= 4:
                    # Check if word is prefix of any significant word in content
                    if any(w.startswith(word) for w in content_lower.split() if len(w) > 4):
                        score += 0.2

            if score > 0:
                scores[path] = score

        return scores
    
    def save_state(self, filepath: str):
        """Save system state to JSON."""
        state = {
            'current_turn': self.current_turn,
            'files': {p: f.to_dict() for p, f in self.files.items()},
            'dynamic_weights': self.dynamic_weights,
        }
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)
    
    def load_state(self, filepath: str, content_loader=None):
        """
        Load system state from JSON.
        
        Args:
            filepath: Path to state file
            content_loader: Optional function(path) → content
        """
        with open(filepath, 'r') as f:
            state = json.load(f)
        
        self.current_turn = state.get('current_turn', 0)
        self.dynamic_weights = state.get('dynamic_weights', {})
        
        for path, file_data in state.get('files', {}).items():
            content = ""
            if content_loader:
                content = content_loader(path)
            self.files[path] = CognitiveFile.from_dict(file_data, content)
        
        self._rebuild_dag()


def get_context(system: CognitiveSystem) -> Dict[str, List[CognitiveFile]]:
    """
    Get files organized by tier for injection.
    
    Returns:
        Dict with keys 'HOT', 'WARM', 'COLD' containing sorted file lists
    """
    result = {"HOT": [], "WARM": [], "COLD": []}
    
    for file in system.files.values():
        result[file.tier].append(file)
    
    # Sort by pressure within tier (highest first)
    for tier in result:
        result[tier].sort(key=lambda f: f.pressure_bucket, reverse=True)
    
    return result


def process_turn(
    system: CognitiveSystem,
    query: str,
    custom_activated: Optional[List[str]] = None
) -> TurnRecord:
    """
    Process a single turn.

    1. Find activated files from query (or use custom list)
    2. Apply activation boost (scaled by match score)
    3. Propagate pressure along DAG edges
    4. Apply decay to inactive files
    5. Record turn history

    Args:
        system: The cognitive system
        query: User query text
        custom_activated: Optional explicit list of activated paths

    Returns:
        TurnRecord with details of what happened
    """
    system.current_turn += 1

    # Find activated files with scores
    if custom_activated is not None:
        # Custom activation: uniform score of 1.0
        activated_scores = {p: 1.0 for p in custom_activated}
    else:
        # Query-based activation with variable scores
        activated_scores = system.find_activated(query)

    # Update activation metadata
    for path in activated_scores:
        if path in system.files:
            system.files[path].last_activated = system.current_turn
            system.files[path].activation_count += 1

    # Update dynamic weights (self-learning)
    system.update_dynamic_weights(list(activated_scores.keys()))

    # Apply pressure dynamics with scores
    apply_activation(system.files, activated_scores, system.pressure_config)
    
    # Track propagation
    propagated = set()
    hot_before = {p for p, f in system.files.items() if f.tier == "HOT"}
    
    propagate_pressure(
        system.files,
        system.adjacency,
        system.get_effective_weights(),
        system.pressure_config
    )
    
    hot_after = {p for p, f in system.files.items() if f.tier == "HOT"}
    propagated = hot_after - hot_before - set(activated_scores.keys())
    
    # Apply decay
    apply_decay(system.files, system.current_turn, system.pressure_config)

    # Update basin state (v0.3.0) - track consecutive HOT turns for decay resistance
    update_basin_state(system.files, system.current_turn, system.pressure_config)

    # Enforce conservation every turn (not just periodically)
    # This ensures total pressure stays at budget and fixes the "all files HOT" issue
    redistribute_pressure(system.files, system.pressure_config)

    # Get final context
    context = get_context(system)
    
    # Create record
    record = TurnRecord(
        turn=system.current_turn,
        timestamp=time.time(),
        query=query,
        activated=list(activated_scores.keys()),
        propagated=list(propagated),
        hot=[f.path for f in context['HOT']],
        warm=[f.path for f in context['WARM']],
        cold_count=len(context['COLD']),
        pressure_stats=get_pressure_stats(system.files),
    )
    
    system.history.append(record)
    
    return record


def get_bucket_distribution(system: CognitiveSystem) -> Dict[int, List[str]]:
    """
    Get distribution of files across system buckets.
    
    Returns:
        Dict mapping bucket → list of paths
    """
    buckets = {}
    for path, file in system.files.items():
        bucket = file.system_bucket
        if bucket not in buckets:
            buckets[bucket] = []
        buckets[bucket].append(path)
    return buckets


def get_neighbors(system: CognitiveSystem, path: str, include_dag: bool = True) -> List[str]:
    """
    Get neighbor files.
    
    Neighbors are:
    - Files in same or adjacent system buckets
    - Files connected via DAG edges
    
    Args:
        path: File path
        include_dag: Include DAG-connected files
    
    Returns:
        List of neighbor paths
    """
    if path not in system.files:
        return []
    
    file = system.files[path]
    neighbors = set()
    
    # Bucket neighbors (same or ±1)
    for other_path, other_file in system.files.items():
        if other_path == path:
            continue
        bucket_diff = abs(file.system_bucket - other_file.system_bucket)
        if bucket_diff <= 1:
            neighbors.add(other_path)
    
    # DAG neighbors
    if include_dag:
        neighbors.update(file.outgoing_edges)
        neighbors.update(file.incoming_edges)
    
    return list(neighbors)
