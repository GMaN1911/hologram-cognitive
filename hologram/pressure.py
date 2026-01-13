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
    activation_boost: float = 0.4       # Pressure boost when file is activated
    
    # Propagation
    edge_flow_rate: float = 0.15        # How much pressure flows per edge per turn
    flow_decay_per_hop: float = 0.7     # Flow decreases with distance
    max_propagation_hops: int = 2       # How far pressure propagates
    
    # Decay
    decay_rate: float = 0.85            # Multiply pressure by this each turn
    decay_immunity_turns: int = 2       # Don't decay recently activated files
    
    # Conservation
    enable_conservation: bool = True    # If true, boosting drains from others
    total_pressure_budget: float = 10.0 # Total pressure in system (if conserved)
    
    # Thresholds
    hot_propagates: bool = True         # Only HOT files propagate
    min_pressure_to_propagate: float = 0.8  # Minimum raw pressure to propagate


def apply_activation(
    files: Dict[str, 'CognitiveFile'],
    activated_paths: List[str],
    config: Optional[PressureConfig] = None
) -> Dict[str, float]:
    """
    Apply activation boost to files that were mentioned/triggered.
    
    If conservation is enabled, pressure is drained from non-activated files.
    
    Args:
        files: Dict of path → CognitiveFile
        activated_paths: Paths that were activated this turn
        config: Pressure configuration
    
    Returns:
        Dict of path → pressure delta (for logging)
    """
    if config is None:
        config = PressureConfig()
    
    if not activated_paths:
        return {}
    
    deltas = {}
    
    # Calculate boost
    total_boost = len(activated_paths) * config.activation_boost
    
    if config.enable_conservation:
        # Drain from non-activated files to maintain conservation
        non_activated = [p for p in files if p not in activated_paths]
        if non_activated:
            drain_per_file = total_boost / len(non_activated)
            for path in non_activated:
                old = files[path].raw_pressure
                files[path].raw_pressure = max(0.0, old - drain_per_file)
                files[path].pressure_bucket = quantize_pressure(files[path].raw_pressure)
                deltas[path] = files[path].raw_pressure - old
    
    # Apply boost to activated files
    for path in activated_paths:
        if path in files:
            old = files[path].raw_pressure
            files[path].raw_pressure = min(1.0, old + config.activation_boost)
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
        if source_path not in adjacency or not adjacency[source_path]:
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

            outgoing = adjacency.get(current, set())
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
    
    Args:
        files: Dict of path → CognitiveFile
        current_turn: Current turn number
        config: Pressure configuration
    
    Returns:
        Dict of path → pressure delta from decay
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
        file.raw_pressure *= config.decay_rate
        file.pressure_bucket = quantize_pressure(file.raw_pressure)
        deltas[path] = file.raw_pressure - old
    
    return deltas


def redistribute_pressure(
    files: Dict[str, 'CognitiveFile'],
    config: Optional[PressureConfig] = None
):
    """
    Redistribute pressure to maintain budget (if conservation enabled).
    
    Called periodically to correct drift from floating point errors.
    """
    if config is None:
        config = PressureConfig()
    
    if not config.enable_conservation:
        return
    
    current_total = sum(f.raw_pressure for f in files.values())
    
    if current_total == 0:
        # Distribute evenly
        even_pressure = config.total_pressure_budget / len(files)
        for file in files.values():
            file.raw_pressure = even_pressure
            file.pressure_bucket = quantize_pressure(file.raw_pressure)
    else:
        # Scale to match budget
        scale = config.total_pressure_budget / current_total
        for file in files.values():
            file.raw_pressure = min(1.0, file.raw_pressure * scale)
            file.pressure_bucket = quantize_pressure(file.raw_pressure)


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
