"""
Cognitive System for Hologram Cognitive

Core data structures and turn processing.
This is the main entry point for the coordinate-based context system.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional, Any
from pathlib import Path
import json
import math
import re
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
    prepare_targets,
    discover_edges_prepared,
    edge_weights_prepared,
    config_fingerprint,
)

DAG_CACHE_VERSION = 2

# A query word found in more than this share of the candidate files says nothing about which
# file the query is about (a project's own name appears in all of its docs). Small systems
# are exempt: with a handful of files a shared word is still a signal.
ACTIVATION_DF_MAX_SHARE = 0.5
ACTIVATION_DF_MIN_FILES = 10
from .route_policy import demotion_released, is_demoted_path, query_terms
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

    # T³ adaptive dynamics (v0.4.0) - learned from edit correlation
    # Defaults match PressureConfig constants for zero-change backward compat
    # Loaded from t3_file_state.json by Session layer before each turn
    learned_decay: float = 0.85      # Per-file decay rate
    learned_boost: float = 0.6       # Per-file activation boost
    
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
            'last_resurrected': self.last_resurrected,
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
            last_resurrected=data.get('last_resurrected', 0),
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
    
    # State
    current_turn: int = 0
    history: List[TurnRecord] = field(default_factory=list)
    
    # Config
    dag_config: EdgeDiscoveryConfig = field(default_factory=EdgeDiscoveryConfig)
    pressure_config: PressureConfig = field(default_factory=PressureConfig)

    # Route policy (route_policy.py): a path matching demote_patterns is never activated by a
    # query unless the query names the area, so fixture trees stay indexed without accumulating
    # pressure. Empty = off; HologramRouter.from_directory fills it from ProjectConfig.
    demote_patterns: List[str] = field(default_factory=list)
    demote_factor: float = 0.1
    demote_release_tokens: List[str] = field(default_factory=list)
    
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
    
    def _load_dag_cache(self, cache_path: str) -> Tuple[Dict[str, Tuple[str, Dict[str, float]]], Set[str]]:
        """(per-source entries {source: (signature, {target: weight})}, paths the entries were
        checked against). Empty if the cache is missing, unreadable, from another format, or
        built under a different config."""
        try:
            cache = json.loads(Path(cache_path).read_text())
            if (cache.get('version') != DAG_CACHE_VERSION
                    or cache.get('config') != config_fingerprint(self.dag_config)):
                return {}, set()
            paths = cache['paths']
            entries = {src: (e['sig'], {paths[i]: w for i, w in zip(e['e'], e['w'])})
                       for src, e in cache['sources'].items()}
            return entries, set(paths)
        except Exception:
            return {}, set()

    def _save_dag_cache(self, cache_path: str, fresh: Dict[str, Dict[str, float]]) -> None:
        """Write the per-source entries in `fresh` atomically (a hook killed mid-write by its
        timeout must not leave a truncated cache that poisons every later load)."""
        import os
        paths = list(self.files)
        index = {p: i for i, p in enumerate(paths)}
        cache = {
            'version': DAG_CACHE_VERSION,
            'config': config_fingerprint(self.dag_config),
            'paths': paths,
            'sources': {
                src: {'sig': self.files[src].content_signature,
                      'e': [index[t] for t in w],
                      'w': list(w.values())}
                for src, w in fresh.items()
            },
        }
        tmp = f"{cache_path}.tmp{os.getpid()}"
        try:
            Path(tmp).write_text(json.dumps(cache))
            os.replace(tmp, cache_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _rebuild_dag(self, cache_path: str = None):
        """Rebuild the DAG from current file contents (with optional per-source caching).

        A source's edges and weights depend only on its own content and on the set of paths,
        so a cached source with an unchanged signature is reused and checked only against
        paths it has not seen. HOLOGRAM_DAG_BUDGET_SEC (unset/0 = no limit) caps the time spent
        on sources that need work; past it, a source keeps its stale cached edges (or none),
        is counted in `dag_stale_sources`, and is left out of the saved cache so the next
        rebuild recomputes it.
        """
        import os
        budget = float(os.environ.get('HOLOGRAM_DAG_BUDGET_SEC') or 0)
        deadline = time.monotonic() + budget if budget > 0 else None

        cached, seen_paths = self._load_dag_cache(cache_path) if cache_path else ({}, set())
        targets = prepare_targets(list(self.files), self.dag_config)
        current = set(self.files)
        new_targets = [t for t in targets if t.path not in seen_paths]

        adjacency, edge_weights, fresh = {}, {}, {}
        stale = 0
        for path, file in self.files.items():
            entry = cached.get(path)
            reusable = entry is not None and entry[0] == file.content_signature
            weights = None
            if reusable and not new_targets:
                weights = {t: w for t, w in entry[1].items() if t in current}
            elif deadline is None or time.monotonic() < deadline:
                scan = new_targets if reusable else targets
                content_lower = file.content.lower()
                edges = discover_edges_prepared(path, file.content, scan, self.dag_config, content_lower)
                found = edge_weights_prepared(path, content_lower, [t for t in scan if t.path in edges])
                weights = ({t: w for t, w in entry[1].items() if t in current} if reusable else {})
                weights.update(found)
            if weights is not None:
                fresh[path] = weights
            else:
                stale += 1
                weights = {t: w for t, w in entry[1].items() if t in current} if entry else {}
            adjacency[path] = set(weights)
            edge_weights[path] = weights

        self.adjacency = adjacency
        self.edge_weights = edge_weights
        self.dag_stale_sources = stale

        # Update file edge sets
        incoming = get_incoming_edges(self.adjacency)
        for path, file in self.files.items():
            file.outgoing_edges = self.adjacency.get(path, set())
            file.incoming_edges = incoming.get(path, set())

        if cache_path:
            self._save_dag_cache(cache_path, fresh)
    
    def find_activated(self, query: str) -> Dict[str, float]:
        """
        Find files activated by a query with activation scores.

        Returns dict of path → score where score reflects match quality:
        - Multiple keyword matches stack (more matches = higher score)
        - Title/path matches weighted higher than content matches
        - Partial/prefix matches contribute smaller scores

        Stop-words never match, a word found in most of the files is dropped as carrying no
        signal, and demoted paths (route policy) are skipped unless the query names them.

        Returns:
            Dict mapping file paths to activation scores (0.0 = not activated)
        """
        words = query_terms(query)
        if not words:
            return {}

        skip_demoted = bool(self.demote_patterns) and not demotion_released(self, query)
        whole = {w: re.compile(r'(?<![a-z0-9_])' + re.escape(w) + r'(?![a-z0-9_])') for w in words}
        prefix = {w: re.compile(r'(?<![a-z0-9_])' + re.escape(w)) for w in words if len(w) >= 4}

        hits: Dict[str, Dict[str, float]] = {w: {} for w in words}
        candidates = 0
        for path, file in self.files.items():
            if skip_demoted and is_demoted_path(self, path):
                continue
            candidates += 1
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
                    hits[word][path] = 1.0
                # Exact match in title: +0.8
                elif title_lower and word in title_lower:
                    hits[word][path] = 0.8
                elif word in content_lower:
                    # Whole word in content: +0.4
                    if whole[word].search(content_lower):
                        hits[word][path] = 0.4
                    # Prefix of a longer word (4+ chars): +0.2
                    elif word in prefix and prefix[word].search(content_lower):
                        hits[word][path] = 0.2

        config = self.pressure_config
        large = candidates >= ACTIVATION_DF_MIN_FILES
        scores: Dict[str, float] = {}
        for word, matched in hits.items():
            if large and len(matched) > ACTIVATION_DF_MAX_SHARE * candidates:
                continue
            rarity = 1.0
            if config.activation_idf and large:
                rarity = math.log((candidates + 1) / (len(matched) + 1)) / math.log(candidates + 1)
            for path, weight in matched.items():
                scores[path] = scores.get(path, 0.0) + weight * rarity

        if config.activation_max_files and len(scores) > config.activation_max_files:
            best = sorted(scores, key=lambda p: (-scores[p], p))[:config.activation_max_files]
            scores = {p: scores[p] for p in best}

        return scores

    def save_state(self, filepath: str):
        """Save system state to JSON."""
        state = {
            'current_turn': self.current_turn,
            'files': {p: f.to_dict() for p, f in self.files.items()},
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
    custom_activated: Optional[List[str]] = None,
    extra_scores: Optional[Dict[str, float]] = None,
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

    # Activation that does not come from the query's words (session focus: hologram/focus.py).
    for path, score in (extra_scores or {}).items():
        if path in system.files and score > 0:
            activated_scores[path] = activated_scores.get(path, 0.0) + score

    # Update activation metadata
    for path in activated_scores:
        if path in system.files:
            system.files[path].last_activated = system.current_turn
            system.files[path].activation_count += 1

    # Apply pressure dynamics with scores
    apply_activation(system.files, activated_scores, system.pressure_config)
    
    # Track propagation
    propagated = set()
    hot_before = {p for p, f in system.files.items() if f.tier == "HOT"}
    
    propagate_pressure(
        system.files,
        system.adjacency,
        system.edge_weights,
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
