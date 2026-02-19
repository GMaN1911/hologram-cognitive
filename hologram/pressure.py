"""
Pressure Dynamics for Hologram Cognitive

Handles attention pressure: activation, propagation along edges, decay.
Key feature: Conservation - total pressure is bounded, boosting one cools others.

This is the "physics" of the system.
"""

from dataclasses import dataclass
from typing import Dict, Set, List, Optional, TYPE_CHECKING
from collections import defaultdict

from .coordinates import quantize_pressure, PRESSURE_BUCKETS, HOT_THRESHOLD

if TYPE_CHECKING:
    from .system import CognitiveFile, CognitiveSystem


@dataclass
class PressureConfig:
    """Configuration for pressure dynamics."""
    
    # Activation
    activation_boost: float = 0.6       # Pressure boost when file is activated (bumped for first-mention HOT injection)
    
    # Propagation
    edge_flow_rate: float = 0.15        # How much pressure flows per edge per turn
    flow_decay_per_hop: float = 0.7     # Flow decreases with distance
    max_propagation_hops: int = 2       # How far pressure propagates
    
    # Decay
    decay_rate: float = 0.85            # Multiply pressure by this each turn
    decay_immunity_turns: int = 2       # Don't decay recently activated files

    # Toroidal Decay: "The Lighthouse" (Active by Default)
    # Metaphor: A lighthouse beam that sweeps periodically, illuminating
    # forgotten context without disrupting your current navigation.
    use_toroidal_decay: bool = True       # ENABLED: Gentle re-anchoring
    resurrection_threshold: float = 0.05  # When file is effectively dead
    resurrection_pressure: float = 0.55   # Resurrect to WARM (visible but non-disruptive)
    resurrection_cooldown: int = 100      # Sweep cycle: ~3-4 hours of heavy usage

    # Conservation
    enable_conservation: bool = True    # If true, boosting drains from others
    total_pressure_budget: float = 10.0 # Base budget (scales with file count if dynamic)
    dynamic_budget: bool = True         # Scale budget with file count
    budget_per_file: float = 0.5        # Budget contribution per file (dynamic mode)

    # Thresholds
    hot_propagates: bool = True         # Only HOT files propagate
    min_pressure_to_propagate: float = 0.8  # Minimum raw pressure to propagate

    # Basin dynamics (v0.3.0) - attention stickiness
    max_basin_depth_turns: int = 5       # Turns at HOT to reach max basin depth
    basin_depth_multiplier: float = 1.5  # How much deeper basins resist decay
    basin_cooldown_rate: int = 2         # How fast basins shallow when not HOT


# =============================================================================
# Basin Dynamics (v0.3.0)
# =============================================================================

def compute_basin_depth(
    consecutive_hot_turns: int,
    config: Optional[PressureConfig] = None
) -> float:
    """
    Compute basin depth from consecutive HOT turns.

    Basin depth ranges from 1.0 (shallow, just activated) to 2.5 (deep, sustained focus).
    Deeper basins resist decay more strongly, modeling how sustained attention
    creates "sticky" focus that resists distraction.

    Args:
        consecutive_hot_turns: Number of consecutive turns file has been HOT
        config: Pressure configuration

    Returns:
        Basin depth in range [1.0, 1.0 + basin_depth_multiplier]
    """
    if config is None:
        config = PressureConfig()

    # Normalize to [0, 1] range, capped at max_basin_depth_turns
    normalized = min(consecutive_hot_turns / config.max_basin_depth_turns, 1.0)

    # Basin depth: 1.0 + (normalized * multiplier)
    # Default: 1.0 (shallow) to 2.5 (deep with multiplier=1.5)
    return 1.0 + (normalized * config.basin_depth_multiplier)


def compute_effective_decay(
    base_decay: float,
    basin_depth: float
) -> float:
    """
    Compute effective decay rate based on basin depth.

    Deeper basins = slower decay. Uses root function so deeper basins
    decay more slowly:
    - basin_depth=1.0: decay^1.0 = 0.85 (normal decay)
    - basin_depth=2.0: decay^0.5 = 0.92 (slower decay)
    - basin_depth=2.5: decay^0.4 = 0.94 (much slower decay)

    Args:
        base_decay: Normal decay rate (e.g., 0.85)
        basin_depth: Current basin depth (1.0 to 2.5)

    Returns:
        Effective decay rate (higher = slower decay)
    """
    return base_decay ** (1.0 / basin_depth)


def update_basin_state(
    files: Dict[str, 'CognitiveFile'],
    current_turn: int,
    config: Optional[PressureConfig] = None
):
    """
    Update basin state for all files after pressure changes.

    Called at the end of each turn to track:
    - consecutive_hot_turns: incremented if HOT, decremented (by cooldown_rate) if not
    - basin_depth: recomputed from consecutive_hot_turns

    Args:
        files: Dict of path → CognitiveFile
        current_turn: Current turn number (unused, for future extensions)
        config: Pressure configuration
    """
    if config is None:
        config = PressureConfig()

    for file in files.values():
        is_hot_now = file.tier == "HOT"

        if is_hot_now:
            # File is HOT - deepen the basin
            file.consecutive_hot_turns += 1
        else:
            # File is not HOT - shallow the basin gradually
            file.consecutive_hot_turns = max(
                0,
                file.consecutive_hot_turns - config.basin_cooldown_rate
            )

        # Recompute basin depth
        file.basin_depth = compute_basin_depth(file.consecutive_hot_turns, config)


def apply_activation(
    files: Dict[str, 'CognitiveFile'],
    activated_scores: Dict[str, float],
    config: Optional[PressureConfig] = None
) -> Dict[str, float]:
    """
    Apply activation boost to files that were mentioned/triggered.

    Boost is scaled by activation score - files with higher match quality
    get proportionally higher boosts (capped at 3x base boost).

    If conservation is enabled, pressure is drained from non-activated files.

    Args:
        files: Dict of path → CognitiveFile
        activated_scores: Dict of path → activation score (higher = stronger match)
        config: Pressure configuration

    Returns:
        Dict of path → pressure delta (for logging)
    """
    if config is None:
        config = PressureConfig()

    if not activated_scores:
        return {}

    deltas = {}

    # Calculate total boost based on sum of scores (capped per-file at 3x)
    capped_scores = {p: min(s, 3.0) for p, s in activated_scores.items()}
    total_boost = sum(capped_scores.values()) * config.activation_boost

    if config.enable_conservation:
        # Drain from non-activated files to maintain conservation
        non_activated = [p for p in files if p not in activated_scores]
        if non_activated:
            drain_per_file = total_boost / len(non_activated)
            for path in non_activated:
                old = files[path].raw_pressure
                files[path].raw_pressure = max(0.0, old - drain_per_file)
                files[path].pressure_bucket = quantize_pressure(files[path].raw_pressure)
                deltas[path] = files[path].raw_pressure - old

    # Apply boost to activated files, scaled by their score
    for path, score in activated_scores.items():
        if path in files:
            old = files[path].raw_pressure
            # Scale boost by score (capped at 3x base boost)
            scaled_boost = config.activation_boost * min(score, 3.0)
            files[path].raw_pressure = min(1.0, old + scaled_boost)
            files[path].pressure_bucket = quantize_pressure(files[path].raw_pressure)
            deltas[path] = files[path].raw_pressure - old

    return deltas


def propagate_pressure(
    files: Dict[str, 'CognitiveFile'],
    adjacency: Dict[str, Set[str]],
    edge_weights: Optional[Dict[str, Dict[str, float]]] = None,
    config: Optional[PressureConfig] = None
) -> Dict[str, float]:
    """
    Propagate pressure along DAG edges using BFS with hop decay.

    HOT files push pressure to their neighbors up to max_propagation_hops.
    Pressure decays by flow_decay_per_hop ** hop_distance.
    Pressure is conserved: what flows out comes from the source.

    Args:
        files: Dict of path → CognitiveFile
        adjacency: DAG adjacency (source → targets)
        edge_weights: Optional edge weights (source → target → weight)
        config: Pressure configuration

    Returns:
        Dict of path → pressure delta from propagation
    """
    if config is None:
        config = PressureConfig()

    deltas = defaultdict(float)

    # Find source files that can propagate
    sources = []
    for path, file in files.items():
        if config.hot_propagates:
            if file.raw_pressure < config.min_pressure_to_propagate:
                continue
        sources.append(path)

    # BFS from each source with hop tracking
    for source_path in sources:
        # Check if source has any outgoing edges (structural or dynamic)
        has_adj = source_path in adjacency and adjacency[source_path]
        has_weights = edge_weights and source_path in edge_weights and edge_weights[source_path]

        if not has_adj and not has_weights:
            continue

        # BFS: (current_path, hop_distance, accumulated_flow)
        base_flow = config.edge_flow_rate
        queue = [(source_path, 0, base_flow)]
        visited = {source_path}

        while queue:
            current, hop, flow = queue.pop(0)

            # Don't propagate beyond max hops
            if hop >= config.max_propagation_hops:
                continue

            # Combine structural edges (adjacency) and dynamic edges (edge_weights keys)
            outgoing = set()
            if current in adjacency:
                outgoing.update(adjacency[current])
            if edge_weights and current in edge_weights:
                outgoing.update(edge_weights[current].keys())

            if not outgoing:
                continue

            # Divide flow among outgoing edges
            flow_per_edge = flow / len(outgoing)

            for target_path in outgoing:
                if target_path not in files:
                    continue

                # Apply edge weight
                weight = 1.0
                if edge_weights and current in edge_weights:
                    weight = edge_weights[current].get(target_path, 1.0)

                # Apply hop decay
                hop_decay = config.flow_decay_per_hop ** (hop + 1)
                actual_flow = flow_per_edge * weight * hop_decay

                # Target receives pressure
                deltas[target_path] += actual_flow

                # Source loses pressure (conservation)
                if config.enable_conservation:
                    deltas[source_path] -= actual_flow

                # Continue BFS from this target (if not visited)
                if target_path not in visited:
                    visited.add(target_path)
                    queue.append((target_path, hop + 1, actual_flow))

    # Apply deltas
    for path, delta in deltas.items():
        if path in files:
            old = files[path].raw_pressure
            files[path].raw_pressure = max(0.0, min(1.0, old + delta))
            files[path].pressure_bucket = quantize_pressure(files[path].raw_pressure)

    return dict(deltas)


def apply_decay(
    files: Dict[str, 'CognitiveFile'],
    current_turn: int,
    config: Optional[PressureConfig] = None
) -> Dict[str, float]:
    """
    Apply decay to all files.

    Recently activated files are immune (decay_immunity_turns).

    Toroidal Decay: "The Lighthouse" (Active by Default)
    When use_toroidal_decay=True (default), files that decay below
    resurrection_threshold will "wrap around" and resurrect to WARM tier.

    Design Philosophy:
    - Resurrect to WARM (0.55), not HOT (0.8)
    - High visibility without displacing active work
    - Conservation still applies, but impact is gentle
    - Metaphor: Lighthouse beam illuminating forgotten context
    - You can navigate toward it or ignore it (user agency)

    This implements spaced repetition for long-context re-anchoring.
    In sessions >1000 turns, human working memory fails. The lighthouse
    compensates by periodically surfacing forgotten but relevant files.

    Args:
        files: Dict of path → CognitiveFile
        current_turn: Current turn number
        config: Pressure configuration

    Returns:
        Dict of path → pressure delta from decay (negative for normal decay,
        positive for resurrections to WARM tier)
    """
    if config is None:
        config = PressureConfig()

    deltas = {}

    for path, file in files.items():
        # Skip recently activated files
        turns_since_active = current_turn - file.last_activated
        if turns_since_active < config.decay_immunity_turns:
            continue

        old = file.raw_pressure

        # Basin-aware decay (v0.3.0)
        # Deeper basins (more consecutive HOT turns) decay more slowly
        effective_decay = compute_effective_decay(config.decay_rate, file.basin_depth)
        file.raw_pressure *= effective_decay

        # Toroidal resurrection (experimental)
        if config.use_toroidal_decay:
            # Check if pressure dropped below resurrection threshold
            if file.raw_pressure < config.resurrection_threshold:
                # Check cooldown to prevent rapid resurrection loops
                turns_since_resurrection = current_turn - file.last_resurrected
                if turns_since_resurrection >= config.resurrection_cooldown:
                    # Resurrect: wrap around to HOT pressure
                    file.raw_pressure = config.resurrection_pressure
                    file.last_resurrected = current_turn
                    # Delta will show large positive jump (resurrection event)
                else:
                    # Still in cooldown, clamp at threshold (don't go lower)
                    file.raw_pressure = config.resurrection_threshold

        file.pressure_bucket = quantize_pressure(file.raw_pressure)
        deltas[path] = file.raw_pressure - old

    return deltas


def compute_effective_budget(
    file_count: int,
    config: Optional[PressureConfig] = None
) -> float:
    """
    Compute effective pressure budget based on file count.

    With dynamic_budget=True, budget scales with file count to ensure
    files can reach meaningful pressures (HOT/WARM thresholds) regardless
    of how many files are in the system.

    Formula: max(base_budget, file_count * budget_per_file)

    Args:
        file_count: Number of files in the system
        config: Pressure configuration

    Returns:
        Effective budget for conservation
    """
    if config is None:
        config = PressureConfig()

    if not config.dynamic_budget:
        return config.total_pressure_budget

    # Scale budget with file count, but never below base budget
    dynamic = file_count * config.budget_per_file
    return max(config.total_pressure_budget, dynamic)


def redistribute_pressure(
    files: Dict[str, 'CognitiveFile'],
    config: Optional[PressureConfig] = None
):
    """
    Redistribute pressure to maintain budget (if conservation enabled).

    Called after each turn to enforce conservation.
    Properly handles the 1.0 cap by redistributing overflow to other files.

    With dynamic_budget=True, the budget scales with file count so files
    can reach meaningful pressures even with large file counts.
    """
    if config is None:
        config = PressureConfig()

    if not config.enable_conservation:
        return

    if not files:
        return

    # Compute effective budget (may scale with file count)
    effective_budget = compute_effective_budget(len(files), config)

    current_total = sum(f.raw_pressure for f in files.values())

    if current_total == 0:
        # Distribute evenly
        even_pressure = effective_budget / len(files)
        for file in files.values():
            file.raw_pressure = even_pressure
            file.pressure_bucket = quantize_pressure(file.raw_pressure)
        return

    # Simple proportional scaling
    scale = effective_budget / current_total

    if scale <= 1.0:
        # Scaling down - straightforward, no cap issues
        for file in files.values():
            file.raw_pressure *= scale
            file.pressure_bucket = quantize_pressure(file.raw_pressure)
    else:
        # Scaling up - need to handle 1.0 cap carefully
        # First pass: scale up, cap at 1.0, track overflow
        overflow = 0.0
        uncapped_files = []
        for file in files.values():
            new_pressure = file.raw_pressure * scale
            if new_pressure > 1.0:
                overflow += new_pressure - 1.0
                file.raw_pressure = 1.0
            else:
                file.raw_pressure = new_pressure
                uncapped_files.append(file)
            file.pressure_bucket = quantize_pressure(file.raw_pressure)

        # Distribute overflow to uncapped files (up to 3 iterations to handle cascading)
        for _ in range(3):
            if overflow <= 0.001 or not uncapped_files:
                break
            share = overflow / len(uncapped_files)
            overflow = 0.0
            still_uncapped = []
            for file in uncapped_files:
                new_pressure = file.raw_pressure + share
                if new_pressure > 1.0:
                    overflow += new_pressure - 1.0
                    file.raw_pressure = 1.0
                else:
                    file.raw_pressure = new_pressure
                    still_uncapped.append(file)
                file.pressure_bucket = quantize_pressure(file.raw_pressure)
            uncapped_files = still_uncapped


def get_pressure_stats(files: Dict[str, 'CognitiveFile']) -> dict:
    """
    Get statistics about current pressure distribution.
    """
    pressures = [f.raw_pressure for f in files.values()]
    
    hot_count = sum(1 for f in files.values() if f.pressure_bucket >= HOT_THRESHOLD)
    warm_count = sum(1 for f in files.values() if 20 <= f.pressure_bucket < HOT_THRESHOLD)
    cold_count = len(files) - hot_count - warm_count
    
    return {
        'total_pressure': sum(pressures),
        'avg_pressure': sum(pressures) / len(pressures) if pressures else 0,
        'max_pressure': max(pressures) if pressures else 0,
        'min_pressure': min(pressures) if pressures else 0,
        'hot_count': hot_count,
        'warm_count': warm_count,
        'cold_count': cold_count,
    }
