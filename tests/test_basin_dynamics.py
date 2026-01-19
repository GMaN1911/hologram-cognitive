#!/usr/bin/env python3
"""
Tests for Basin Dynamics (v0.3.0)

Tests the attention basin stickiness features:
- compute_basin_depth: consecutive HOT turns → basin depth
- compute_effective_decay: basin depth → slower decay rate
- update_basin_state: track consecutive HOT turns and update basins
- Integration with apply_decay: basin-aware decay in pressure system
"""

import sys
sys.path.insert(0, '.')

from hologram.pressure import (
    PressureConfig,
    compute_basin_depth,
    compute_effective_decay,
    update_basin_state,
    apply_decay,
)
from hologram.system import CognitiveFile
from hologram.coordinates import quantize_pressure


def test_compute_basin_depth():
    """Test basin depth computation from consecutive HOT turns."""
    config = PressureConfig()

    # 0 consecutive turns → shallow basin (1.0)
    depth = compute_basin_depth(0, config)
    assert depth == 1.0, f"Expected 1.0, got {depth}"

    # 1 consecutive turn → slightly deeper (1.0 + 0.2 * 1.5 = 1.3)
    depth = compute_basin_depth(1, config)
    assert 1.25 <= depth <= 1.35, f"Expected ~1.3, got {depth}"

    # max turns (5) → max depth (1.0 + 1.0 * 1.5 = 2.5)
    depth = compute_basin_depth(5, config)
    assert depth == 2.5, f"Expected 2.5, got {depth}"

    # Beyond max turns → still capped at 2.5
    depth = compute_basin_depth(10, config)
    assert depth == 2.5, f"Expected 2.5 (capped), got {depth}"

    print("✓ compute_basin_depth: All tests passed")


def test_compute_effective_decay():
    """Test effective decay rate from basin depth."""
    base_decay = 0.85

    # Shallow basin (1.0) → normal decay
    effective = compute_effective_decay(base_decay, 1.0)
    assert abs(effective - 0.85) < 0.001, f"Expected 0.85, got {effective}"

    # Medium basin (2.0) → sqrt decay ≈ 0.922
    effective = compute_effective_decay(base_decay, 2.0)
    expected = 0.85 ** 0.5  # ≈ 0.922
    assert abs(effective - expected) < 0.001, f"Expected {expected}, got {effective}"

    # Deep basin (2.5) → even slower decay ≈ 0.937
    effective = compute_effective_decay(base_decay, 2.5)
    expected = 0.85 ** 0.4  # ≈ 0.937
    assert abs(effective - expected) < 0.001, f"Expected {expected}, got {effective}"

    print("✓ compute_effective_decay: All tests passed")


def test_update_basin_state():
    """Test basin state updates based on tier changes."""
    config = PressureConfig()

    # Create test files
    files = {
        'hot_file.md': CognitiveFile(
            path='hot_file.md',
            raw_pressure=0.9,  # HOT tier
            pressure_bucket=quantize_pressure(0.9),
        ),
        'warm_file.md': CognitiveFile(
            path='warm_file.md',
            raw_pressure=0.5,  # WARM tier
            pressure_bucket=quantize_pressure(0.5),
            consecutive_hot_turns=3,  # Was HOT before
        ),
        'cold_file.md': CognitiveFile(
            path='cold_file.md',
            raw_pressure=0.2,  # COLD tier
            pressure_bucket=quantize_pressure(0.2),
        ),
    }

    # Update basin state
    update_basin_state(files, current_turn=1, config=config)

    # HOT file should have incremented consecutive_hot_turns
    assert files['hot_file.md'].consecutive_hot_turns == 1
    assert files['hot_file.md'].basin_depth > 1.0

    # WARM file (was HOT, now not) should have decremented by cooldown_rate (2)
    assert files['warm_file.md'].consecutive_hot_turns == 1  # 3 - 2 = 1

    # COLD file should stay at 0
    assert files['cold_file.md'].consecutive_hot_turns == 0
    assert files['cold_file.md'].basin_depth == 1.0

    print("✓ update_basin_state: All tests passed")


def test_basin_stickiness():
    """Test that files with deep basins decay more slowly."""
    config = PressureConfig()

    # Create two HOT files with different basin depths
    shallow_file = CognitiveFile(
        path='shallow.md',
        raw_pressure=0.9,
        pressure_bucket=quantize_pressure(0.9),
        consecutive_hot_turns=0,
        basin_depth=1.0,
        last_activated=0,  # Not recently activated
    )

    deep_file = CognitiveFile(
        path='deep.md',
        raw_pressure=0.9,
        pressure_bucket=quantize_pressure(0.9),
        consecutive_hot_turns=5,
        basin_depth=2.5,
        last_activated=0,  # Not recently activated
    )

    files = {
        'shallow.md': shallow_file,
        'deep.md': deep_file,
    }

    initial_shallow = shallow_file.raw_pressure
    initial_deep = deep_file.raw_pressure

    # Apply decay (turn 10 to avoid immunity)
    apply_decay(files, current_turn=10, config=config)

    # Calculate expected decays
    shallow_decay = compute_effective_decay(config.decay_rate, 1.0)  # 0.85
    deep_decay = compute_effective_decay(config.decay_rate, 2.5)     # ~0.937

    expected_shallow = initial_shallow * shallow_decay
    expected_deep = initial_deep * deep_decay

    # Verify shallow file decayed more
    assert abs(shallow_file.raw_pressure - expected_shallow) < 0.001, \
        f"Shallow: expected {expected_shallow}, got {shallow_file.raw_pressure}"
    assert abs(deep_file.raw_pressure - expected_deep) < 0.001, \
        f"Deep: expected {expected_deep}, got {deep_file.raw_pressure}"

    # Deep file should have higher pressure (decayed less)
    assert deep_file.raw_pressure > shallow_file.raw_pressure, \
        "Deep basin file should decay slower than shallow basin file"

    print("✓ Basin stickiness: Deep basins decay more slowly")


def test_turns_to_drop_hot():
    """Test how many turns it takes for files to drop from HOT based on basin depth."""
    config = PressureConfig()
    hot_threshold = 0.831  # raw_pressure threshold for HOT tier

    # Shallow basin (just activated)
    shallow = CognitiveFile(
        path='shallow.md',
        raw_pressure=0.9,
        pressure_bucket=quantize_pressure(0.9),
        consecutive_hot_turns=1,
        basin_depth=compute_basin_depth(1, config),
        last_activated=0,
    )

    # Deep basin (sustained focus)
    deep = CognitiveFile(
        path='deep.md',
        raw_pressure=0.9,
        pressure_bucket=quantize_pressure(0.9),
        consecutive_hot_turns=5,
        basin_depth=compute_basin_depth(5, config),
        last_activated=0,
    )

    # Count turns to drop from HOT
    shallow_turns = 0
    deep_turns = 0

    # Simulate shallow file decay
    pressure = 0.9
    while pressure >= hot_threshold and shallow_turns < 50:
        effective_decay = compute_effective_decay(config.decay_rate, compute_basin_depth(1, config))
        pressure *= effective_decay
        shallow_turns += 1

    # Simulate deep file decay
    pressure = 0.9
    while pressure >= hot_threshold and deep_turns < 50:
        effective_decay = compute_effective_decay(config.decay_rate, compute_basin_depth(5, config))
        pressure *= effective_decay
        deep_turns += 1

    print(f"  Shallow basin (1 turn): drops from HOT in ~{shallow_turns} turns")
    print(f"  Deep basin (5 turns): drops from HOT in ~{deep_turns} turns")

    # Deep should take roughly 2-3x longer
    assert deep_turns > shallow_turns * 1.5, \
        f"Deep basin should take significantly longer to drop (got {deep_turns} vs {shallow_turns})"

    print("✓ Turns to drop HOT: Deep basins are stickier")


def test_serialization():
    """Test that basin fields serialize and deserialize correctly."""
    original = CognitiveFile(
        path='test.md',
        raw_pressure=0.85,
        pressure_bucket=40,
        consecutive_hot_turns=3,
        basin_depth=1.9,
    )

    # Serialize
    data = original.to_dict()
    assert 'consecutive_hot_turns' in data
    assert 'basin_depth' in data
    assert data['consecutive_hot_turns'] == 3
    assert data['basin_depth'] == 1.9

    # Deserialize
    restored = CognitiveFile.from_dict(data)
    assert restored.consecutive_hot_turns == 3
    assert restored.basin_depth == 1.9

    print("✓ Serialization: Basin fields persist correctly")


def test_backward_compatibility():
    """Test that old state files without basin fields load correctly."""
    # Simulate old v0.2.0 state (no basin fields)
    old_data = {
        'path': 'legacy.md',
        'raw_pressure': 0.7,
        'pressure_bucket': 33,
        'last_activated': 10,
        'activation_count': 5,
        # No consecutive_hot_turns or basin_depth
    }

    # Should load with defaults
    file = CognitiveFile.from_dict(old_data)
    assert file.consecutive_hot_turns == 0
    assert file.basin_depth == 1.0

    print("✓ Backward compatibility: Old state loads with defaults")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Basin Dynamics v0.3.0 Tests")
    print("=" * 60)
    print()

    test_compute_basin_depth()
    test_compute_effective_decay()
    test_update_basin_state()
    test_basin_stickiness()
    test_turns_to_drop_hot()
    test_serialization()
    test_backward_compatibility()

    print()
    print("=" * 60)
    print("All tests passed! ✅")
    print("=" * 60)


if __name__ == '__main__':
    main()
