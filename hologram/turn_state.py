"""
Turn State for Hologram Cognitive v0.3.0

Implements cross-turn state inheritance:
- Attention clusters (co-activated files)
- Pressure inheritance (unresolved context carries forward)
- Tension tracking (unresolved cognitive load)
- Resolution detection integration point

This models how human working memory actually works: sustained focus creates
"sticky" attention that resists distraction, while unresolved cognitive load
carries forward until resolution.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple
from pathlib import Path
import json
import time


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class TurnStateConfig:
    """Configuration for turn-state inheritance."""

    # Inheritance
    enable_inheritance: bool = True          # Enable pressure inheritance
    inheritance_rate: float = 0.6            # How much pressure carries forward
    inheritance_threshold: float = 0.3       # Min pressure to inherit

    # Tension tracking
    tension_accumulation: float = 0.15       # Tension added per unresolved query
    tension_decay: float = 0.3               # Tension released per turn
    max_tension_sources: int = 5             # Max topics to track

    # Cluster tracking
    cluster_stability_turns: int = 3         # Turns before cluster is "stable"
    min_cluster_size: int = 2                # Min files for valid cluster


# =============================================================================
# Turn State
# =============================================================================

@dataclass
class TurnState:
    """
    Persistent state across conversation turns.

    Tracks:
    - attention_cluster: Files that have co-activated recently
    - pressure_inheritance: Pressure to carry forward to next turn
    - unresolved_tension: Accumulated cognitive load (0.0-1.0)
    - tension_sources: Topics contributing to tension
    """
    turn: int = 0
    timestamp: float = field(default_factory=time.time)

    # Attention cluster (co-activated files)
    attention_cluster: Set[str] = field(default_factory=set)
    cluster_formation_turn: int = 0
    cluster_sustained_turns: int = 0

    # Inherited pressure from previous turn
    pressure_inheritance: Dict[str, float] = field(default_factory=dict)

    # Tension tracking
    unresolved_tension: float = 0.0
    tension_sources: List[str] = field(default_factory=list)

    # Resolution state
    last_resolution_turn: int = 0
    pending_crystallization: bool = False

    def to_dict(self) -> dict:
        """Serialize to dict for JSON storage."""
        return {
            'turn': self.turn,
            'timestamp': self.timestamp,
            'attention_cluster': list(self.attention_cluster),
            'cluster_formation_turn': self.cluster_formation_turn,
            'cluster_sustained_turns': self.cluster_sustained_turns,
            'pressure_inheritance': self.pressure_inheritance,
            'unresolved_tension': self.unresolved_tension,
            'tension_sources': self.tension_sources,
            'last_resolution_turn': self.last_resolution_turn,
            'pending_crystallization': self.pending_crystallization,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'TurnState':
        """Deserialize from dict."""
        state = cls(
            turn=data.get('turn', 0),
            timestamp=data.get('timestamp', time.time()),
            cluster_formation_turn=data.get('cluster_formation_turn', 0),
            cluster_sustained_turns=data.get('cluster_sustained_turns', 0),
            unresolved_tension=data.get('unresolved_tension', 0.0),
            tension_sources=data.get('tension_sources', []),
            last_resolution_turn=data.get('last_resolution_turn', 0),
            pending_crystallization=data.get('pending_crystallization', False),
        )
        state.attention_cluster = set(data.get('attention_cluster', []))
        state.pressure_inheritance = data.get('pressure_inheritance', {})
        return state

    def copy(self) -> 'TurnState':
        """Create a deep copy of this state."""
        return TurnState.from_dict(self.to_dict())


# =============================================================================
# State Persistence
# =============================================================================

def save_turn_state(state: TurnState, claude_dir: Path) -> Path:
    """
    Save turn state to JSON file.

    Args:
        state: TurnState to save
        claude_dir: Path to .claude directory

    Returns:
        Path to saved file
    """
    filepath = claude_dir / 'turn_state.json'
    filepath.write_text(json.dumps(state.to_dict(), indent=2))
    return filepath


def load_turn_state(claude_dir: Path) -> TurnState:
    """
    Load turn state from JSON file.

    Args:
        claude_dir: Path to .claude directory

    Returns:
        TurnState (empty if file doesn't exist)
    """
    filepath = claude_dir / 'turn_state.json'
    if filepath.exists():
        try:
            data = json.loads(filepath.read_text())
            return TurnState.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            pass
    return TurnState()


# =============================================================================
# Cluster Management
# =============================================================================

def update_attention_cluster(
    prev_cluster: Set[str],
    activated_files: Set[str],
    sustained_turns: int,
    resolved: bool,
    config: Optional[TurnStateConfig] = None
) -> Tuple[Set[str], int]:
    """
    Update attention cluster based on newly activated files.

    Clusters grow when files co-activate, and persist until resolution.

    Args:
        prev_cluster: Previous attention cluster
        activated_files: Files activated this turn
        sustained_turns: How long cluster has been stable
        resolved: Whether resolution was detected
        config: Configuration options

    Returns:
        (new_cluster, new_sustained_turns)
    """
    if config is None:
        config = TurnStateConfig()

    if resolved:
        # Resolution detected - start fresh cluster
        return activated_files.copy(), 0

    if not activated_files:
        # No activation - decay cluster stability
        return prev_cluster, max(0, sustained_turns - 1)

    # Check overlap between new activation and existing cluster
    overlap = prev_cluster & activated_files

    if overlap or not prev_cluster:
        # Growing or starting cluster
        new_cluster = prev_cluster | activated_files
        # Increment sustained if significant overlap
        overlap_ratio = len(overlap) / max(len(prev_cluster), 1)
        if overlap_ratio >= 0.3 or not prev_cluster:
            new_sustained = sustained_turns + 1
        else:
            new_sustained = sustained_turns
        return new_cluster, new_sustained
    else:
        # No overlap - possible topic shift, but don't reset immediately
        # Blend in new files while keeping some history
        new_cluster = (prev_cluster | activated_files)
        return new_cluster, max(0, sustained_turns - 1)


# =============================================================================
# Pressure Inheritance
# =============================================================================

def compute_inherited_pressure(
    files: Dict[str, any],  # path -> CognitiveFile
    config: Optional[TurnStateConfig] = None
) -> Dict[str, float]:
    """
    Compute pressure to inherit for next turn.

    Only files above inheritance_threshold are inherited.
    Inherited pressure is scaled by inheritance_rate.

    Args:
        files: Dict of path -> CognitiveFile
        config: Configuration options

    Returns:
        Dict of path -> inherited pressure
    """
    if config is None:
        config = TurnStateConfig()

    if not config.enable_inheritance:
        return {}

    inherited = {}
    for path, file in files.items():
        pressure = file.raw_pressure if hasattr(file, 'raw_pressure') else 0.0
        if pressure >= config.inheritance_threshold:
            inherited[path] = pressure * config.inheritance_rate

    return inherited


def apply_inherited_pressure(
    files: Dict[str, any],  # path -> CognitiveFile
    inherited: Dict[str, float],
    config: Optional[TurnStateConfig] = None
):
    """
    Apply inherited pressure from previous turn.

    Adds inherited pressure to current raw_pressure (capped at 1.0).
    Called before activation boost.

    Args:
        files: Dict of path -> CognitiveFile (modified in place)
        inherited: Dict of path -> inherited pressure
        config: Configuration options
    """
    if config is None:
        config = TurnStateConfig()

    if not config.enable_inheritance or not inherited:
        return

    for path, inherit_amount in inherited.items():
        if path in files:
            file = files[path]
            old_pressure = file.raw_pressure
            file.raw_pressure = min(1.0, old_pressure + inherit_amount)


# =============================================================================
# Tension Tracking
# =============================================================================

def extract_tension_sources(query: str, max_sources: int = 5) -> List[str]:
    """
    Extract potential tension sources (topics) from query.

    Simple heuristic: extract significant words/phrases.

    Args:
        query: User query text
        max_sources: Maximum sources to extract

    Returns:
        List of tension source strings
    """
    # Simple extraction: significant words (4+ chars, not stopwords)
    stopwords = {
        'that', 'this', 'with', 'from', 'have', 'will', 'what', 'when',
        'where', 'which', 'would', 'could', 'should', 'about', 'there',
        'their', 'they', 'been', 'being', 'were', 'does', 'doing',
    }

    words = query.lower().split()
    significant = [
        w.strip('.,!?()[]{}"\':;')
        for w in words
        if len(w) >= 4 and w.lower() not in stopwords
    ]

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for w in significant:
        if w not in seen:
            seen.add(w)
            unique.append(w)

    return unique[:max_sources]


def update_tension(
    prev_tension: float,
    prev_sources: List[str],
    query: str,
    resolved: bool,
    config: Optional[TurnStateConfig] = None
) -> Tuple[float, List[str]]:
    """
    Update tension level based on query and resolution state.

    Tension accumulates with unresolved queries and decays naturally.
    Resolution significantly reduces tension.

    Args:
        prev_tension: Previous tension level (0.0-1.0)
        prev_sources: Previous tension sources
        query: Current query text
        resolved: Whether resolution was detected
        config: Configuration options

    Returns:
        (new_tension, new_sources)
    """
    if config is None:
        config = TurnStateConfig()

    if resolved:
        # Resolution - significant tension release
        new_tension = max(0.0, prev_tension - 0.5)
        return new_tension, []

    # Extract new tension sources from query
    new_sources = extract_tension_sources(query, config.max_tension_sources)

    # Compute query tension (more question words/complexity = more tension)
    query_tension = 0.0
    query_lower = query.lower()

    # Question indicators add tension
    if '?' in query:
        query_tension += 0.1
    if any(w in query_lower for w in ['why', 'how', 'confused', 'unclear', 'help']):
        query_tension += 0.1
    if any(w in query_lower for w in ['still', 'yet', 'not working', 'broken']):
        query_tension += 0.15

    # Base accumulation
    query_tension += config.tension_accumulation

    # Apply decay and add new tension
    decayed = prev_tension * (1.0 - config.tension_decay)
    new_tension = min(1.0, decayed + query_tension)

    # Merge sources (keep recent, drop old)
    merged_sources = new_sources + [s for s in prev_sources if s not in new_sources]
    merged_sources = merged_sources[:config.max_tension_sources]

    return new_tension, merged_sources


# =============================================================================
# State Transition
# =============================================================================

def compute_next_state(
    prev_state: TurnState,
    activated_files: Set[str],
    files: Dict[str, any],
    query: str,
    resolved: bool,
    resolution_type: str = "none",
    config: Optional[TurnStateConfig] = None
) -> TurnState:
    """
    Compute next turn state from previous state and current turn results.

    This is the main state transition function that integrates:
    - Attention cluster updates
    - Pressure inheritance computation
    - Tension tracking
    - Resolution handling

    Args:
        prev_state: Previous turn state
        activated_files: Files activated this turn
        files: Dict of path -> CognitiveFile (after pressure updates)
        query: User query text
        resolved: Whether resolution was detected
        resolution_type: "completion", "topic_change", or "none"
        config: Configuration options

    Returns:
        New TurnState for next turn
    """
    if config is None:
        config = TurnStateConfig()

    # Update attention cluster
    new_cluster, new_sustained = update_attention_cluster(
        prev_state.attention_cluster,
        activated_files,
        prev_state.cluster_sustained_turns,
        resolved,
        config
    )

    # Update tension
    new_tension, new_sources = update_tension(
        prev_state.unresolved_tension,
        prev_state.tension_sources,
        query,
        resolved,
        config
    )

    # Compute pressure inheritance for next turn
    new_inheritance = compute_inherited_pressure(files, config)

    # Check crystallization trigger
    should_crystallize = (
        resolved and
        resolution_type == "completion" and
        prev_state.cluster_sustained_turns >= config.cluster_stability_turns and
        len(prev_state.attention_cluster) >= config.min_cluster_size
    )

    # Build next state
    if resolved and resolution_type == "topic_change":
        # Topic change - reset cluster but keep some inheritance
        next_state = TurnState(
            turn=prev_state.turn + 1,
            attention_cluster=activated_files.copy(),
            cluster_formation_turn=prev_state.turn + 1,
            cluster_sustained_turns=0,
            pressure_inheritance={},  # Clean slate for new topic
            unresolved_tension=new_tension,
            tension_sources=new_sources,
            last_resolution_turn=prev_state.turn + 1,
            pending_crystallization=should_crystallize,
        )
    elif resolved:
        # Completion - may crystallize, reset some state
        next_state = TurnState(
            turn=prev_state.turn + 1,
            attention_cluster=new_cluster if not should_crystallize else set(),
            cluster_formation_turn=prev_state.turn + 1 if should_crystallize else prev_state.cluster_formation_turn,
            cluster_sustained_turns=0 if should_crystallize else new_sustained,
            pressure_inheritance={},  # Clear inheritance on resolution
            unresolved_tension=new_tension,
            tension_sources=new_sources,
            last_resolution_turn=prev_state.turn + 1,
            pending_crystallization=should_crystallize,
        )
    else:
        # No resolution - continue accumulating
        next_state = TurnState(
            turn=prev_state.turn + 1,
            attention_cluster=new_cluster,
            cluster_formation_turn=prev_state.cluster_formation_turn if prev_state.attention_cluster else prev_state.turn + 1,
            cluster_sustained_turns=new_sustained,
            pressure_inheritance=new_inheritance,
            unresolved_tension=new_tension,
            tension_sources=new_sources,
            last_resolution_turn=prev_state.last_resolution_turn,
            pending_crystallization=False,
        )

    next_state.timestamp = time.time()
    return next_state
