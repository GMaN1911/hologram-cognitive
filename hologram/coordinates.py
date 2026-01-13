"""
Coordinate System for Hologram Cognitive

Content-addressed system buckets + quantized pressure with toroidal topology.

Key insight: Quantization creates intentional collisions = neighborhoods.
Same content → same bucket (deterministic via SHA3).
Bucket topology defines adjacency (not content similarity).
"""

import hashlib
from typing import Tuple

# ============================================================
# CONFIGURATION
# ============================================================

SYSTEM_BUCKETS = 48      # Number of system coordinate buckets
PRESSURE_BUCKETS = 48    # Number of pressure levels (toroidal wrap)

# Pressure tier thresholds (bucket ranges)
HOT_THRESHOLD = 40       # Buckets 40-47 = HOT
WARM_THRESHOLD = 20      # Buckets 20-39 = WARM
                         # Buckets 0-19 = COLD


# ============================================================
# SYSTEM BUCKET (static, content-addressed)
# ============================================================

def compute_system_bucket(path: str, content: str = "") -> int:
    """
    Compute content-addressed system bucket.

    Same content → same bucket (deterministic).
    Bucket collisions create neighborhoods by design (not semantic similarity).

    Args:
        path: File path (always included in hash)
        content: File content (optional, for true content-addressing)

    Returns:
        Bucket index 0 to SYSTEM_BUCKETS-1
    """
    hasher = hashlib.sha3_256()
    hasher.update(path.encode('utf-8'))
    
    if content:
        # Include content signature for true content-addressing
        content_hash = hashlib.sha3_256(content.encode('utf-8')).digest()[:8]
        hasher.update(content_hash)
    
    digest = hasher.digest()
    bucket = int.from_bytes(digest[:4], 'big') % SYSTEM_BUCKETS
    return bucket


def compute_content_signature(content: str) -> str:
    """
    Compute a short content signature for change detection.
    
    Returns:
        8-character hex signature
    """
    return hashlib.sha3_256(content.encode('utf-8')).hexdigest()[:8]


# ============================================================
# PRESSURE BUCKET (dynamic, quantized)
# ============================================================

def quantize_pressure(raw_pressure: float) -> int:
    """
    Convert continuous pressure (0.0-1.0) to discrete bucket.
    
    Intentional collision = neighborhoods.
    Items with pressure 0.452 and 0.455 both map to bucket 21.
    
    Args:
        raw_pressure: Continuous pressure value (clamped to 0-1)
    
    Returns:
        Bucket index 0 to PRESSURE_BUCKETS-1
    """
    clamped = max(0.0, min(1.0, raw_pressure))
    bucket = int(clamped * (PRESSURE_BUCKETS - 1))
    return bucket


def unquantize_pressure(bucket: int) -> float:
    """
    Convert bucket back to approximate raw pressure (center of bucket).
    """
    return bucket / (PRESSURE_BUCKETS - 1)


def get_tier(pressure_bucket: int) -> str:
    """
    Get tier name from pressure bucket.
    
    Returns:
        'HOT', 'WARM', or 'COLD'
    """
    if pressure_bucket >= HOT_THRESHOLD:
        return "HOT"
    elif pressure_bucket >= WARM_THRESHOLD:
        return "WARM"
    return "COLD"


# ============================================================
# TOROIDAL OPERATIONS
# ============================================================

def toroidal_decay(bucket: int, decay_amount: int = 2) -> int:
    """
    Decay pressure with toroidal wrap.
    
    Bucket wraps around: 2 decaying by 3 → 47 (not -1).
    This creates closed topology - nothing truly dies, just cycles.
    
    Args:
        bucket: Current pressure bucket
        decay_amount: How many buckets to decay
    
    Returns:
        New bucket after decay (wrapped)
    """
    return (bucket - decay_amount) % PRESSURE_BUCKETS


def toroidal_boost(bucket: int, boost_amount: int) -> int:
    """
    Boost pressure with toroidal wrap.
    
    Bucket 46 boosted by 3 → 1 (wraps around).
    
    Args:
        bucket: Current pressure bucket
        boost_amount: How many buckets to boost
    
    Returns:
        New bucket after boost (wrapped)
    """
    return (bucket + boost_amount) % PRESSURE_BUCKETS


def bucket_distance(a: int, b: int) -> int:
    """
    Distance on torus (shortest path, considering wrap).
    
    Distance between bucket 2 and 46 is 4 (via wrap), not 44.
    
    Args:
        a: First bucket
        b: Second bucket
    
    Returns:
        Shortest distance on torus
    """
    direct = abs(a - b)
    wrapped = PRESSURE_BUCKETS - direct
    return min(direct, wrapped)


# ============================================================
# COORDINATE UTILITIES
# ============================================================

def get_coordinate(system_bucket: int, pressure_bucket: int) -> Tuple[int, int]:
    """
    Get full coordinate tuple.
    """
    return (system_bucket, pressure_bucket)


def coordinate_distance(coord_a: Tuple[int, int], coord_b: Tuple[int, int]) -> float:
    """
    Euclidean-ish distance between coordinates.
    
    System bucket distance is weighted higher (structural difference).
    Pressure bucket distance uses toroidal metric.
    """
    system_dist = abs(coord_a[0] - coord_b[0])  # System is not toroidal
    pressure_dist = bucket_distance(coord_a[1], coord_b[1])  # Pressure is toroidal
    
    # Weight system distance higher
    return (system_dist * 2.0) + pressure_dist


def are_neighbors(coord_a: Tuple[int, int], coord_b: Tuple[int, int], 
                  system_threshold: int = 2, pressure_threshold: int = 5) -> bool:
    """
    Check if two coordinates are neighbors.
    
    Args:
        coord_a: First coordinate (system, pressure)
        coord_b: Second coordinate
        system_threshold: Max system bucket difference
        pressure_threshold: Max pressure bucket difference (toroidal)
    
    Returns:
        True if coordinates are neighbors
    """
    system_dist = abs(coord_a[0] - coord_b[0])
    pressure_dist = bucket_distance(coord_a[1], coord_b[1])
    
    return system_dist <= system_threshold and pressure_dist <= pressure_threshold
