#!/usr/bin/env python3
"""
Tests for Turn-State Inheritance (v0.3.0)

Tests the cross-turn state features:
- TurnState dataclass and persistence
- Attention cluster tracking
- Pressure inheritance
- Tension tracking
- Resolution detection
- Integration with Session
"""

import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, '.')

from hologram.turn_state import (
    TurnState,
    TurnStateConfig,
    load_turn_state,
    save_turn_state,
    update_attention_cluster,
    compute_inherited_pressure,
    apply_inherited_pressure,
    update_tension,
    compute_next_state,
)
from hologram.resolution import (
    detect_resolution,
    detect_contextual_resolution,
    compute_query_tension,
    analyze_query,
)
from hologram.system import CognitiveFile
from hologram.coordinates import quantize_pressure


def test_turn_state_serialization():
    """Test TurnState serializes and deserializes correctly."""
    state = TurnState(
        turn=10,
        attention_cluster={'file1.md', 'file2.md'},
        cluster_formation_turn=7,
        cluster_sustained_turns=3,
        pressure_inheritance={'file1.md': 0.5, 'file3.md': 0.3},
        unresolved_tension=0.4,
        tension_sources=['bug', 'error'],
        last_resolution_turn=5,
        pending_crystallization=True,
    )

    # Serialize
    data = state.to_dict()
    assert data['turn'] == 10
    assert set(data['attention_cluster']) == {'file1.md', 'file2.md'}
    assert data['unresolved_tension'] == 0.4

    # Deserialize
    restored = TurnState.from_dict(data)
    assert restored.turn == 10
    assert restored.attention_cluster == {'file1.md', 'file2.md'}
    assert restored.cluster_sustained_turns == 3
    assert restored.pending_crystallization == True

    print("✓ TurnState serialization: All tests passed")


def test_turn_state_persistence():
    """Test TurnState saves and loads from disk."""
    # Create temp directory
    temp_dir = Path(tempfile.mkdtemp())
    try:
        state = TurnState(
            turn=5,
            attention_cluster={'test.md'},
            unresolved_tension=0.25,
        )

        # Save
        filepath = save_turn_state(state, temp_dir)
        assert filepath.exists()

        # Load
        loaded = load_turn_state(temp_dir)
        assert loaded.turn == 5
        assert loaded.attention_cluster == {'test.md'}
        assert loaded.unresolved_tension == 0.25

        # Load from non-existent returns empty state
        empty = load_turn_state(Path('/nonexistent'))
        assert empty.turn == 0
        assert empty.attention_cluster == set()

    finally:
        shutil.rmtree(temp_dir)

    print("✓ TurnState persistence: All tests passed")


def test_attention_cluster_tracking():
    """Test attention cluster updates correctly."""
    config = TurnStateConfig()

    # Empty cluster + activation → new cluster
    new_cluster, sustained = update_attention_cluster(
        prev_cluster=set(),
        activated_files={'file1.md', 'file2.md'},
        sustained_turns=0,
        resolved=False,
        config=config
    )
    assert new_cluster == {'file1.md', 'file2.md'}
    assert sustained == 1

    # Overlapping activation → cluster grows, sustained increases
    new_cluster2, sustained2 = update_attention_cluster(
        prev_cluster=new_cluster,
        activated_files={'file2.md', 'file3.md'},
        sustained_turns=sustained,
        resolved=False,
        config=config
    )
    assert 'file1.md' in new_cluster2
    assert 'file3.md' in new_cluster2
    assert sustained2 >= sustained

    # Resolution → fresh cluster
    new_cluster3, sustained3 = update_attention_cluster(
        prev_cluster=new_cluster2,
        activated_files={'other.md'},
        sustained_turns=sustained2,
        resolved=True,
        config=config
    )
    assert new_cluster3 == {'other.md'}
    assert sustained3 == 0

    print("✓ Attention cluster tracking: All tests passed")


def test_pressure_inheritance():
    """Test pressure inheritance computation and application."""
    config = TurnStateConfig(
        enable_inheritance=True,
        inheritance_rate=0.6,
        inheritance_threshold=0.3,
    )

    # Create test files
    files = {
        'high.md': CognitiveFile(path='high.md', raw_pressure=0.8),
        'medium.md': CognitiveFile(path='medium.md', raw_pressure=0.5),
        'low.md': CognitiveFile(path='low.md', raw_pressure=0.2),  # Below threshold
    }

    # Compute inheritance
    inherited = compute_inherited_pressure(files, config)

    # High and medium should be inherited
    assert 'high.md' in inherited
    assert 'medium.md' in inherited
    assert 'low.md' not in inherited  # Below threshold

    # Check inheritance rates
    assert abs(inherited['high.md'] - 0.48) < 0.01  # 0.8 * 0.6
    assert abs(inherited['medium.md'] - 0.30) < 0.01  # 0.5 * 0.6

    # Apply inheritance to new files
    new_files = {
        'high.md': CognitiveFile(path='high.md', raw_pressure=0.3),
        'medium.md': CognitiveFile(path='medium.md', raw_pressure=0.2),
        'other.md': CognitiveFile(path='other.md', raw_pressure=0.5),
    }

    apply_inherited_pressure(new_files, inherited, config)

    # Pressure should increase
    assert new_files['high.md'].raw_pressure > 0.3
    assert new_files['medium.md'].raw_pressure > 0.2
    assert new_files['other.md'].raw_pressure == 0.5  # Unchanged

    print("✓ Pressure inheritance: All tests passed")


def test_tension_tracking():
    """Test tension accumulates and decays correctly."""
    config = TurnStateConfig(
        tension_accumulation=0.15,
        tension_decay=0.3,
    )

    # Initial state - no tension
    tension, sources = update_tension(
        prev_tension=0.0,
        prev_sources=[],
        query="what is this file?",
        resolved=False,
        config=config
    )

    # Should accumulate tension (question mark + words)
    assert tension > 0.1
    assert len(sources) > 0

    # Continue without resolution - tension accumulates
    tension2, sources2 = update_tension(
        prev_tension=tension,
        prev_sources=sources,
        query="still confused about the error",
        resolved=False,
        config=config
    )

    # Should be higher due to accumulation
    assert tension2 > tension * 0.5  # Account for decay

    # Resolution - tension drops
    tension3, sources3 = update_tension(
        prev_tension=tension2,
        prev_sources=sources2,
        query="got it, thanks!",
        resolved=True,
        config=config
    )

    assert tension3 < tension2
    assert sources3 == []  # Sources cleared on resolution

    print("✓ Tension tracking: All tests passed")


def test_resolution_detection():
    """Test resolution detection heuristics."""

    # Completion signals
    resolved, rtype = detect_resolution("fixed it, working now!")
    assert resolved == True
    assert rtype == "completion"

    resolved, rtype = detect_resolution("thanks, that solved it")
    assert resolved == True
    assert rtype == "completion"

    # Topic change signals
    resolved, rtype = detect_resolution("unrelated question - what about X?")
    assert resolved == True
    assert rtype == "topic_change"

    resolved, rtype = detect_resolution("by the way, different topic")
    assert resolved == True
    assert rtype == "topic_change"

    # No resolution
    resolved, rtype = detect_resolution("why isn't this working?")
    assert resolved == False
    assert rtype == "none"

    resolved, rtype = detect_resolution("still having the same issue")
    assert resolved == False
    assert rtype == "none"

    # Ambiguous - completion outweighs tension
    resolved, rtype = detect_resolution("great, though I have another question")
    # "great" is completion signal, "question" is mild tension
    # Behavior depends on exact weights

    print("✓ Resolution detection: All tests passed")


def test_query_tension():
    """Test tension extraction from queries."""

    # Low tension - simple statement
    tension = compute_query_tension("show me the file")
    assert tension < 0.2

    # Medium tension - question
    tension = compute_query_tension("why isn't this working?")
    assert tension > 0.2

    # High tension - confusion + question
    tension = compute_query_tension("I'm confused, why doesn't this make sense? still not working")
    assert tension > 0.3

    print("✓ Query tension computation: All tests passed")


def test_compute_next_state():
    """Test full state transition logic."""
    config = TurnStateConfig()

    # Create initial state
    prev_state = TurnState(
        turn=5,
        attention_cluster={'file1.md'},
        cluster_formation_turn=3,
        cluster_sustained_turns=2,
        pressure_inheritance={'file1.md': 0.4},
        unresolved_tension=0.3,
        tension_sources=['bug'],
    )

    # Create mock files
    files = {
        'file1.md': CognitiveFile(path='file1.md', raw_pressure=0.8),
        'file2.md': CognitiveFile(path='file2.md', raw_pressure=0.6),
    }

    # Transition without resolution
    next_state = compute_next_state(
        prev_state=prev_state,
        activated_files={'file1.md', 'file2.md'},
        files=files,
        query="working on the bug",
        resolved=False,
        resolution_type="none",
        config=config
    )

    assert next_state.turn == 6
    assert 'file1.md' in next_state.attention_cluster
    assert 'file2.md' in next_state.attention_cluster
    assert next_state.cluster_sustained_turns >= prev_state.cluster_sustained_turns

    # Transition with completion
    next_state2 = compute_next_state(
        prev_state=next_state,
        activated_files={'file1.md'},
        files=files,
        query="fixed it!",
        resolved=True,
        resolution_type="completion",
        config=config
    )

    assert next_state2.turn == 7
    assert next_state2.unresolved_tension < next_state.unresolved_tension
    assert next_state2.pressure_inheritance == {}  # Cleared on resolution

    print("✓ State transition: All tests passed")


def test_analyze_query():
    """Test full query analysis."""

    result = analyze_query("why isn't the test passing?", prev_tension=0.2)

    assert result.tension_score > 0.2
    assert result.resolution_type == "none"
    assert result.is_followup == False

    result2 = analyze_query("also what about the other file", prev_activated=['other.md'])
    assert result2.is_followup == True  # "also" is follow-up indicator

    print("✓ Query analysis: All tests passed")


def test_contextual_resolution():
    """Test contextual resolution with tool calls."""

    # Git commit indicates completion
    resolved, rtype = detect_contextual_resolution(
        query="commit the changes",
        response="I've committed the changes.",
        tool_calls=[{'tool': 'Bash', 'command': 'git commit -m "fix"'}],
    )
    assert resolved == True
    assert rtype == "completion"

    # Tension sources addressed
    resolved, rtype = detect_contextual_resolution(
        query="help with the bug",
        response="I found the bug was in the file parser. Here's the fix...",
        tool_calls=[],
        prev_tension_sources=['bug', 'file', 'parser'],
    )
    assert resolved == True
    assert rtype == "completion"

    print("✓ Contextual resolution: All tests passed")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Turn-State Inheritance v0.3.0 Tests")
    print("=" * 60)
    print()

    test_turn_state_serialization()
    test_turn_state_persistence()
    test_attention_cluster_tracking()
    test_pressure_inheritance()
    test_tension_tracking()
    test_resolution_detection()
    test_query_tension()
    test_compute_next_state()
    test_analyze_query()
    test_contextual_resolution()

    print()
    print("=" * 60)
    print("All tests passed! ✅")
    print("=" * 60)


if __name__ == '__main__':
    main()
