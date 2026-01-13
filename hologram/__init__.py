"""
Hologram Cognitive - Content-addressed coordinate system for claude-cognitive

A Merkle-DAG inspired approach to context routing:
- Content-addressed system buckets (static, deterministic)
- Quantized pressure buckets (dynamic, toroidal)
- Auto-discovered edges from content (no manual config)
- Pressure propagation along DAG edges
- Conservation of total attention

Based on concepts from "Hologram: The Physics of Information"
Adapted for claude-cognitive by Garret Sutherland / MirrorEthic LLC
"""

__version__ = "0.1.0"

from .coordinates import (
    compute_system_bucket,
    quantize_pressure,
    toroidal_decay,
    toroidal_boost,
    bucket_distance,
    SYSTEM_BUCKETS,
    PRESSURE_BUCKETS,
    HOT_THRESHOLD,
    WARM_THRESHOLD,
)

from .dag import (
    discover_edges,
    build_dag,
    EdgeDiscoveryConfig,
)

from .pressure import (
    apply_activation,
    propagate_pressure,
    apply_decay,
    PressureConfig,
)

from .system import (
    CognitiveFile,
    CognitiveSystem,
    get_context,
    process_turn,
)

from .router import (
    HologramRouter,
    create_router_from_directory,
)

__all__ = [
    # Coordinates
    'compute_system_bucket',
    'quantize_pressure', 
    'toroidal_decay',
    'toroidal_boost',
    'bucket_distance',
    'SYSTEM_BUCKETS',
    'PRESSURE_BUCKETS',
    'HOT_THRESHOLD',
    'WARM_THRESHOLD',
    
    # DAG
    'discover_edges',
    'build_dag',
    'EdgeDiscoveryConfig',
    
    # Pressure
    'apply_activation',
    'propagate_pressure',
    'apply_decay',
    'PressureConfig',
    
    # System
    'CognitiveFile',
    'CognitiveSystem',
    'get_context',
    'process_turn',
    
    # Router
    'HologramRouter',
    'create_router_from_directory',
]
