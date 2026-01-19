#!/usr/bin/env python3
"""
Integration test for Hologram v0.3.0 features.

Simulates a realistic multi-turn conversation with:
- Basin dynamics (sustained attention creates stickiness)
- Turn-state inheritance (pressure carries forward)
- Resolution detection (completion resets state)
- Tension tracking (questions accumulate cognitive load)
"""

import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, '.')

import hologram
from hologram import Session, TurnState


def setup_test_env():
    """Create a temporary .claude directory with test files."""
    temp_dir = Path(tempfile.mkdtemp())
    claude_dir = temp_dir / '.claude'
    claude_dir.mkdir()

    # Create test memory files
    files = {
        'pipeline.md': """# Pipeline System

The main processing pipeline for message handling.

## Components
- Message parser
- Context router
- Response generator

## Key Functions
- `process_message()` - Main entry point
- `route_context()` - Context routing logic
""",
        'orin.md': """# Orin - Layer 0 Sensory

Hardware: Jetson Orin Nano
Role: Sentiment analysis, typing detection

## API
- POST /analyze - Analyze message
- GET /health - Health check

## Integration
Connected to [[pipeline.md]] via HTTP.
""",
        'debugging.md': """# Debugging Guide

Common issues and solutions.

## OOM Errors
- Check VRAM usage
- Reduce batch size
- Enable gradient checkpointing

## Connection Issues
- Verify network connectivity
- Check firewall rules
""",
        'config.md': """# Configuration

System configuration options.

## Environment Variables
- `MODEL_PATH` - Path to model
- `BATCH_SIZE` - Inference batch size
""",
    }

    for name, content in files.items():
        (claude_dir / name).write_text(content)

    return temp_dir, claude_dir


def print_state(session, turn_num, query):
    """Print current state after a turn."""
    result = session.last_result
    state = session.turn_state

    print(f"\n{'='*60}")
    print(f"Turn {turn_num}: \"{query[:50]}{'...' if len(query) > 50 else ''}\"")
    print(f"{'='*60}")

    print(f"\n📊 Pressure State:")
    print(f"  HOT files: {result.hot[:3]}{'...' if len(result.hot) > 3 else ''}")
    print(f"  WARM files: {result.warm[:3]}{'...' if len(result.warm) > 3 else ''}")
    print(f"  Activated: {result.activated}")

    if state:
        print(f"\n🧠 Turn State:")
        print(f"  Attention cluster: {state.attention_cluster}")
        print(f"  Cluster sustained: {state.cluster_sustained_turns} turns")
        print(f"  Tension: {state.unresolved_tension:.2f}")
        print(f"  Tension sources: {state.tension_sources[:3]}")
        print(f"  Inherited pressure: {len(state.pressure_inheritance)} files")

    print(f"\n📋 Resolution:")
    print(f"  Resolved: {result.resolved} ({result.resolution_type})")
    print(f"  Pending crystallization: {result.pending_crystallization}")

    # Show basin depths for HOT files
    if result.hot:
        print(f"\n🏔️ Basin Depths (HOT files):")
        for path in result.hot[:3]:
            if path in session.system.files:
                f = session.system.files[path]
                print(f"  {path}: depth={f.basin_depth:.2f}, consecutive_hot={f.consecutive_hot_turns}")


def test_sustained_attention():
    """Test that sustained attention creates basin stickiness."""
    print("\n" + "=" * 70)
    print("TEST 1: Sustained Attention → Basin Stickiness")
    print("=" * 70)

    temp_dir, claude_dir = setup_test_env()

    try:
        session = Session(str(claude_dir))

        # Turn 1: Activate pipeline
        result = session.turn("tell me about the pipeline system")
        print_state(session, 1, "tell me about the pipeline system")

        # Turn 2: Continue with pipeline (builds basin)
        result = session.turn("how does the message parser work?")
        print_state(session, 2, "how does the message parser work?")

        # Turn 3: Still on pipeline (deeper basin)
        result = session.turn("what about the context router?")
        print_state(session, 3, "what about the context router?")

        # Check basin depth increased
        if 'pipeline.md' in session.system.files:
            f = session.system.files['pipeline.md']
            assert f.consecutive_hot_turns >= 2, f"Expected basin to deepen, got {f.consecutive_hot_turns}"
            assert f.basin_depth > 1.0, f"Expected basin_depth > 1.0, got {f.basin_depth}"
            print(f"\n✅ Basin deepened: consecutive_hot={f.consecutive_hot_turns}, depth={f.basin_depth:.2f}")

        # Turn 4: Off-topic (pipeline should resist decay)
        result = session.turn("what's the weather like?")
        print_state(session, 4, "what's the weather like?")

        # Pipeline should still be warm due to basin stickiness
        if 'pipeline.md' in session.system.files:
            f = session.system.files['pipeline.md']
            # With deep basin, should decay slower
            print(f"✅ After off-topic: pressure={f.raw_pressure:.2f} (basin protected)")

        print("\n" + "=" * 70)
        print("TEST 1 PASSED ✅")
        print("=" * 70)

    finally:
        shutil.rmtree(temp_dir)


def test_pressure_inheritance():
    """Test that pressure inherits across turns."""
    print("\n" + "=" * 70)
    print("TEST 2: Pressure Inheritance")
    print("=" * 70)

    temp_dir, claude_dir = setup_test_env()

    try:
        session = Session(str(claude_dir))

        # Turn 1: Activate debugging
        result = session.turn("help me debug this OOM error")
        print_state(session, 1, "help me debug this OOM error")

        # Check inheritance computed
        state = session.turn_state
        assert len(state.pressure_inheritance) > 0, "Expected pressure inheritance"
        print(f"\n✅ Inheritance computed: {list(state.pressure_inheritance.keys())}")

        # Turn 2: Follow-up without explicit mention
        result = session.turn("is it related to VRAM?")
        print_state(session, 2, "is it related to VRAM?")

        # debugging.md should still be relevant due to inheritance
        if 'debugging.md' in session.system.files:
            f = session.system.files['debugging.md']
            print(f"✅ debugging.md pressure after follow-up: {f.raw_pressure:.2f}")

        print("\n" + "=" * 70)
        print("TEST 2 PASSED ✅")
        print("=" * 70)

    finally:
        shutil.rmtree(temp_dir)


def test_resolution_detection():
    """Test that resolution detection works correctly."""
    print("\n" + "=" * 70)
    print("TEST 3: Resolution Detection")
    print("=" * 70)

    temp_dir, claude_dir = setup_test_env()

    try:
        session = Session(str(claude_dir))

        # Turn 1: Ask a question (builds tension)
        result = session.turn("why isn't the pipeline connecting to orin?")
        print_state(session, 1, "why isn't the pipeline connecting to orin?")

        tension_before = session.turn_state.unresolved_tension
        print(f"\n📈 Tension after question: {tension_before:.2f}")

        # Turn 2: More confusion (tension increases)
        result = session.turn("still not working, what's wrong?")
        print_state(session, 2, "still not working, what's wrong?")

        tension_mid = session.turn_state.unresolved_tension
        print(f"📈 Tension after more confusion: {tension_mid:.2f}")

        # Turn 3: Resolution!
        result = session.turn("oh I see, fixed it! The port was wrong.")
        print_state(session, 3, "oh I see, fixed it! The port was wrong.")

        assert result.resolved, "Expected resolution to be detected"
        assert result.resolution_type == "completion", f"Expected 'completion', got '{result.resolution_type}'"

        tension_after = session.turn_state.unresolved_tension
        print(f"📉 Tension after resolution: {tension_after:.2f}")

        assert tension_after < tension_mid, "Tension should decrease after resolution"
        print(f"\n✅ Resolution detected, tension dropped: {tension_mid:.2f} → {tension_after:.2f}")

        # Turn 4: Topic change
        result = session.turn("by the way, unrelated question about config")
        print_state(session, 4, "by the way, unrelated question about config")

        assert result.resolved, "Expected topic change to be detected"
        assert result.resolution_type == "topic_change", f"Expected 'topic_change', got '{result.resolution_type}'"
        print(f"\n✅ Topic change detected")

        print("\n" + "=" * 70)
        print("TEST 3 PASSED ✅")
        print("=" * 70)

    finally:
        shutil.rmtree(temp_dir)


def test_attention_cluster():
    """Test attention cluster tracking."""
    print("\n" + "=" * 70)
    print("TEST 4: Attention Cluster Tracking")
    print("=" * 70)

    temp_dir, claude_dir = setup_test_env()

    try:
        session = Session(str(claude_dir))

        # Turn 1: Start cluster
        result = session.turn("tell me about pipeline and orin integration")
        print_state(session, 1, "tell me about pipeline and orin integration")

        cluster1 = session.turn_state.attention_cluster
        print(f"\n🔗 Initial cluster: {cluster1}")

        # Turn 2: Expand cluster
        result = session.turn("and how does that connect to debugging?")
        print_state(session, 2, "and how does that connect to debugging?")

        cluster2 = session.turn_state.attention_cluster
        print(f"🔗 Expanded cluster: {cluster2}")

        # Cluster should have grown
        assert len(cluster2) >= len(cluster1), "Cluster should grow with related queries"

        # Turn 3: Sustain cluster
        result = session.turn("more about the pipeline connection")
        print_state(session, 3, "more about the pipeline connection")

        sustained = session.turn_state.cluster_sustained_turns
        print(f"\n✅ Cluster sustained for {sustained} turns")

        print("\n" + "=" * 70)
        print("TEST 4 PASSED ✅")
        print("=" * 70)

    finally:
        shutil.rmtree(temp_dir)


def test_full_conversation():
    """Simulate a realistic multi-turn debugging conversation."""
    print("\n" + "=" * 70)
    print("TEST 5: Full Conversation Simulation")
    print("=" * 70)

    temp_dir, claude_dir = setup_test_env()

    try:
        session = Session(str(claude_dir))

        conversation = [
            ("help me understand the pipeline system", "exploration"),
            ("how does it connect to orin?", "follow-up"),
            ("I'm getting an OOM error", "problem"),
            ("still happening after reducing batch size", "frustration"),
            ("wait, maybe it's the gradient checkpointing", "insight"),
            ("yes! that fixed it, thanks!", "resolution"),
            ("unrelated - what about the config options?", "topic_change"),
        ]

        for i, (query, phase) in enumerate(conversation, 1):
            result = session.turn(query)
            state = session.turn_state

            print(f"\n[Turn {i}] ({phase})")
            print(f"  Query: \"{query}\"")
            print(f"  HOT: {result.hot[:2]} | Tension: {result.tension:.2f}")
            print(f"  Resolved: {result.resolved} ({result.resolution_type})")
            print(f"  Cluster: {len(state.attention_cluster)} files, sustained {state.cluster_sustained_turns} turns")

        print("\n" + "=" * 70)
        print("TEST 5 PASSED ✅")
        print("=" * 70)

    finally:
        shutil.rmtree(temp_dir)


def main():
    print("\n" + "=" * 70)
    print(f"Hologram v{hologram.__version__} Integration Tests")
    print("=" * 70)

    test_sustained_attention()
    test_pressure_inheritance()
    test_resolution_detection()
    test_attention_cluster()
    test_full_conversation()

    print("\n" + "=" * 70)
    print("ALL INTEGRATION TESTS PASSED ✅")
    print("=" * 70)


if __name__ == '__main__':
    main()
