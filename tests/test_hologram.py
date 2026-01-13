#!/usr/bin/env python3
"""
Tests for Hologram Cognitive

Run with: python -m pytest tests/ -v
Or just: python tests/test_hologram.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hologram import (
    compute_system_bucket,
    quantize_pressure,
    toroidal_decay,
    toroidal_boost,
    bucket_distance,
    discover_edges,
    build_dag,
    EdgeDiscoveryConfig,
    apply_activation,
    propagate_pressure,
    apply_decay,
    PressureConfig,
    CognitiveFile,
    CognitiveSystem,
    process_turn,
    get_context,
    HologramRouter,
    SYSTEM_BUCKETS,
    PRESSURE_BUCKETS,
    HOT_THRESHOLD,
    WARM_THRESHOLD,
)


# ============================================================
# COORDINATE TESTS
# ============================================================

def test_system_bucket_deterministic():
    """Same input always gives same bucket."""
    path = "modules/test.md"
    content = "test content"
    
    b1 = compute_system_bucket(path, content)
    b2 = compute_system_bucket(path, content)
    
    assert b1 == b2
    assert 0 <= b1 < SYSTEM_BUCKETS


def test_system_bucket_different_content():
    """Different content gives different buckets (usually)."""
    path = "modules/test.md"
    
    b1 = compute_system_bucket(path, "content A")
    b2 = compute_system_bucket(path, "content B")
    
    # Not guaranteed different, but should be for distinct content
    # Just verify both are valid
    assert 0 <= b1 < SYSTEM_BUCKETS
    assert 0 <= b2 < SYSTEM_BUCKETS


def test_quantize_pressure():
    """Pressure quantization works correctly."""
    assert quantize_pressure(0.0) == 0
    assert quantize_pressure(1.0) == PRESSURE_BUCKETS - 1
    assert quantize_pressure(0.5) == (PRESSURE_BUCKETS - 1) // 2
    
    # Clamping
    assert quantize_pressure(-0.5) == 0
    assert quantize_pressure(1.5) == PRESSURE_BUCKETS - 1


def test_toroidal_decay():
    """Decay wraps around toroidally."""
    assert toroidal_decay(10, 2) == 8
    assert toroidal_decay(1, 2) == PRESSURE_BUCKETS - 1  # Wrap
    assert toroidal_decay(0, 1) == PRESSURE_BUCKETS - 1  # Wrap


def test_toroidal_boost():
    """Boost wraps around toroidally."""
    assert toroidal_boost(10, 2) == 12
    assert toroidal_boost(PRESSURE_BUCKETS - 1, 2) == 1  # Wrap


def test_bucket_distance():
    """Distance uses shortest path on torus."""
    assert bucket_distance(0, 5) == 5
    assert bucket_distance(5, 0) == 5
    
    # Should take wrapped path when shorter
    assert bucket_distance(0, PRESSURE_BUCKETS - 2) == 2
    assert bucket_distance(2, PRESSURE_BUCKETS - 2) == 4


# ============================================================
# DAG DISCOVERY TESTS
# ============================================================

def test_discover_edges_filename():
    """Discovers edges from filename mentions."""
    content = "This file uses the pipeline module."
    all_paths = ["modules/pipeline.md", "modules/other.md"]
    
    edges = discover_edges("source.md", content, all_paths)
    
    assert "modules/pipeline.md" in edges
    assert "modules/other.md" not in edges


def test_discover_edges_path():
    """Discovers edges from full path mentions."""
    content = "See modules/t3-telos.md for details."
    all_paths = ["modules/t3-telos.md", "modules/other.md"]
    
    edges = discover_edges("source.md", content, all_paths)
    
    assert "modules/t3-telos.md" in edges


def test_discover_edges_hyphenated():
    """Discovers edges from hyphenated name parts."""
    content = "The anticipatory coherence system handles this."
    all_paths = ["modules/anticipatory-coherence.md", "modules/other.md"]
    
    edges = discover_edges("source.md", content, all_paths)
    
    assert "modules/anticipatory-coherence.md" in edges


def test_build_dag():
    """Builds complete DAG from multiple files."""
    files = {
        "alpha.md": "References bravo module.",
        "bravo.md": "References charlie module.",
        "charlie.md": "No references.",
    }
    
    dag = build_dag(files)
    
    assert "bravo.md" in dag["alpha.md"]
    assert "charlie.md" in dag["bravo.md"]
    assert len(dag["charlie.md"]) == 0


# ============================================================
# PRESSURE DYNAMICS TESTS
# ============================================================

def test_apply_activation():
    """Activation boosts pressure."""
    files = {
        "a.md": CognitiveFile(path="a.md", raw_pressure=0.2),
        "b.md": CognitiveFile(path="b.md", raw_pressure=0.2),
    }
    
    apply_activation(files, ["a.md"], PressureConfig(activation_boost=0.4))
    
    assert files["a.md"].raw_pressure > 0.5
    assert files["a.md"].pressure_bucket > files["b.md"].pressure_bucket


def test_apply_decay():
    """Decay reduces pressure over time."""
    files = {
        "a.md": CognitiveFile(path="a.md", raw_pressure=0.8, last_activated=0),
    }
    
    apply_decay(files, current_turn=5, config=PressureConfig(decay_rate=0.5))
    
    assert files["a.md"].raw_pressure < 0.8


def test_propagate_pressure():
    """Pressure flows along edges."""
    files = {
        "hot.md": CognitiveFile(path="hot.md", raw_pressure=0.9),
        "cold.md": CognitiveFile(path="cold.md", raw_pressure=0.1),
    }
    files["hot.md"].pressure_bucket = quantize_pressure(0.9)
    files["cold.md"].pressure_bucket = quantize_pressure(0.1)
    
    adjacency = {"hot.md": {"cold.md"}, "cold.md": set()}
    
    propagate_pressure(files, adjacency, config=PressureConfig(edge_flow_rate=0.2))
    
    # Cold should have gained pressure
    assert files["cold.md"].raw_pressure > 0.1


# ============================================================
# SYSTEM TESTS
# ============================================================

def test_cognitive_file_tier():
    """File tier is computed correctly from pressure bucket."""
    file = CognitiveFile(path="test.md")
    
    file.pressure_bucket = HOT_THRESHOLD + 1
    assert file.tier == "HOT"
    
    file.pressure_bucket = WARM_THRESHOLD + 1
    assert file.tier == "WARM"
    
    file.pressure_bucket = WARM_THRESHOLD - 1
    assert file.tier == "COLD"


def test_cognitive_system_add_file():
    """Adding files computes buckets and discovers edges."""
    system = CognitiveSystem()
    
    system.add_file("alpha.md", "References bravo module.")
    system.add_file("bravo.md", "Standalone file.")
    
    assert "alpha.md" in system.files
    assert "bravo.md" in system.files
    assert "bravo.md" in system.files["alpha.md"].outgoing_edges


def test_process_turn():
    """Turn processing activates files and applies dynamics."""
    system = CognitiveSystem()
    system.add_file("orin.md", "Orin sensory system.")
    system.add_file("other.md", "Unrelated content.")
    
    record = process_turn(system, "work on orin")
    
    assert "orin.md" in record.activated
    assert system.files["orin.md"].raw_pressure > system.files["other.md"].raw_pressure


def test_get_context():
    """Context organizes files by tier."""
    system = CognitiveSystem()
    system.add_file("hot.md", "Hot content.")
    system.add_file("cold.md", "Cold content.")
    
    system.files["hot.md"].pressure_bucket = HOT_THRESHOLD + 1
    system.files["cold.md"].pressure_bucket = 5
    
    context = get_context(system)
    
    assert any(f.path == "hot.md" for f in context["HOT"])
    assert any(f.path == "cold.md" for f in context["COLD"])


# ============================================================
# INTEGRATION TESTS
# ============================================================

def test_full_workflow():
    """Test complete workflow from files to injection."""
    system = CognitiveSystem()
    
    # Add files with relationships
    system.add_file("systems/orin.md", """
        # Orin Sensory System
        Layer 0 perception.
        Uses pipe-to-orin for data flow.
        Connected to t3-telos.
    """)
    system.add_file("integrations/pipe-to-orin.md", """
        # Pipe to Orin
        Data flow to orin sensory cortex.
        Part of pipeline system.
    """)
    system.add_file("modules/t3-telos.md", """
        # T3 Telos
        Trajectory system.
        Uses orin for perception.
    """)
    system.add_file("unrelated.md", "Completely unrelated content.")
    
    # Process multiple queries to build up pressure (like real usage)
    process_turn(system, "work on orin layer 0")
    process_turn(system, "orin sensory system")
    record = process_turn(system, "orin perception")
    
    # Should activate orin
    assert "systems/orin.md" in record.activated
    
    # Orin should have significantly higher pressure than unrelated
    orin_pressure = system.files["systems/orin.md"].raw_pressure
    unrelated_pressure = system.files["unrelated.md"].raw_pressure
    
    assert orin_pressure > unrelated_pressure * 2, \
        f"Orin ({orin_pressure}) should be much higher than unrelated ({unrelated_pressure})"
    
    # Related files should have elevated pressure due to propagation
    pipe_pressure = system.files["integrations/pipe-to-orin.md"].raw_pressure
    assert pipe_pressure > unrelated_pressure, \
        f"Pipe ({pipe_pressure}) should be higher than unrelated ({unrelated_pressure})"


def test_dag_discovery_accuracy():
    """Test that DAG discovery finds expected relationships."""
    system = CognitiveSystem()
    
    system.add_file("alpha.md", "Module Alpha uses module-beta for processing.")
    system.add_file("module-beta.md", "Module Beta is standalone.")
    
    # Should discover edge from alpha.md to module-beta.md
    assert "module-beta.md" in system.files["alpha.md"].outgoing_edges
    # Reverse edge should be tracked
    assert "alpha.md" in system.files["module-beta.md"].incoming_edges


# ============================================================
# RUN TESTS
# ============================================================

def run_tests():
    """Run all tests and report results."""
    import traceback
    
    tests = [
        test_system_bucket_deterministic,
        test_system_bucket_different_content,
        test_quantize_pressure,
        test_toroidal_decay,
        test_toroidal_boost,
        test_bucket_distance,
        test_discover_edges_filename,
        test_discover_edges_path,
        test_discover_edges_hyphenated,
        test_build_dag,
        test_apply_activation,
        test_apply_decay,
        test_propagate_pressure,
        test_cognitive_file_tier,
        test_cognitive_system_add_file,
        test_process_turn,
        test_get_context,
        test_full_workflow,
        test_dag_discovery_accuracy,
    ]
    
    passed = 0
    failed = 0
    
    print("=" * 60)
    print("HOLOGRAM COGNITIVE TESTS")
    print("=" * 60)
    
    for test in tests:
        try:
            test()
            print(f"✅ {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__}")
            print(f"   {e}")
            traceback.print_exc()
            failed += 1
    
    print()
    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
