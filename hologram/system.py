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
    
    def add_file(self, path: str, content: str) -> CognitiveFile:
        """
        Add a file to the system.

        Computes system bucket from content and discovers edges.
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

        # Rebuild DAG with new file
        self._rebuild_dag()

        return file
    
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
    
    def _rebuild_dag(self):
        """Rebuild DAG from current file contents."""
        content_map = {p: f.content for p, f in self.files.items()}
        self.adjacency = build_dag(content_map, self.dag_config)
        self.edge_weights = compute_edge_weights(content_map, self.adjacency)
        
        # Update file edge sets
        incoming = get_incoming_edges(self.adjacency)
        for path, file in self.files.items():
            file.outgoing_edges = self.adjacency.get(path, set())
            file.incoming_edges = incoming.get(path, set())
    
    def find_activated(self, query: str) -> Set[str]:
        """
        Find files activated by a query.
        
        Simple keyword matching against paths and content.
        """
        activated = set()
        query_lower = query.lower()
        words = [w for w in query_lower.split() if len(w) > 2]
        
        for path, file in self.files.items():
            for word in words:
                # Check path
                if word in path.lower():
                    activated.add(path)
                    break
                # Check content
                if word in file.content.lower():
                    activated.add(path)
                    break
        
        return activated
    
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
    custom_activated: Optional[List[str]] = None
) -> TurnRecord:
    """
    Process a single turn.
    
    1. Find activated files from query (or use custom list)
    2. Apply activation boost
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
    
    # Find activated files
    if custom_activated is not None:
        activated = set(custom_activated)
    else:
        activated = system.find_activated(query)
    
    # Update activation metadata
    for path in activated:
        if path in system.files:
            system.files[path].last_activated = system.current_turn
            system.files[path].activation_count += 1
    
    # Apply pressure dynamics
    apply_activation(system.files, list(activated), system.pressure_config)
    
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
    propagated = hot_after - hot_before - activated
    
    # Apply decay
    apply_decay(system.files, system.current_turn, system.pressure_config)

    # Periodic pressure normalization to correct floating-point drift
    # (Conservation property can degrade over many turns without this)
    if system.current_turn % 100 == 0:
        redistribute_pressure(system.files, system.pressure_config)

    # Get final context
    context = get_context(system)
    
    # Create record
    record = TurnRecord(
        turn=system.current_turn,
        timestamp=time.time(),
        query=query,
        activated=list(activated),
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
