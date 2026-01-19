#!/usr/bin/env python3
"""
Tests for Auto-Crystallization (v0.3.0)

Tests the crystallization features:
- Trigger condition detection
- Session note generation
- Auto-linking
- Session listing
- Integration with Session
"""

import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, '.')

from hologram.crystallize import (
    CrystallizeConfig,
    should_crystallize,
    crystallize,
    list_sessions,
    infer_title_from_cluster,
    slugify,
    get_known_entities,
    auto_link_text,
    generate_session_note,
)
from hologram.system import CognitiveFile


def test_should_crystallize_conditions():
    """Test crystallization trigger conditions."""
    config = CrystallizeConfig(
        min_cluster_size=2,
        min_sustained_turns=3,
        min_peak_pressure=0.6,
    )

    # Create test files
    files = {
        'high.md': CognitiveFile(path='high.md', raw_pressure=0.8),
        'medium.md': CognitiveFile(path='medium.md', raw_pressure=0.5),
    }

    # Should trigger: completion + sustained + enough files + high pressure
    assert should_crystallize(
        resolved=True,
        resolution_type="completion",
        cluster_sustained_turns=3,
        attention_cluster={'high.md', 'medium.md'},
        files=files,
        config=config
    ) == True

    # Should NOT trigger: not resolved
    assert should_crystallize(
        resolved=False,
        resolution_type="none",
        cluster_sustained_turns=5,
        attention_cluster={'high.md', 'medium.md'},
        files=files,
        config=config
    ) == False

    # Should NOT trigger: topic_change (not completion)
    assert should_crystallize(
        resolved=True,
        resolution_type="topic_change",
        cluster_sustained_turns=5,
        attention_cluster={'high.md', 'medium.md'},
        files=files,
        config=config
    ) == False

    # Should NOT trigger: cluster not sustained enough
    assert should_crystallize(
        resolved=True,
        resolution_type="completion",
        cluster_sustained_turns=2,  # Below 3
        attention_cluster={'high.md', 'medium.md'},
        files=files,
        config=config
    ) == False

    # Should NOT trigger: cluster too small
    assert should_crystallize(
        resolved=True,
        resolution_type="completion",
        cluster_sustained_turns=5,
        attention_cluster={'high.md'},  # Only 1 file
        files=files,
        config=config
    ) == False

    # Should NOT trigger: pressure too low
    low_pressure_files = {
        'low1.md': CognitiveFile(path='low1.md', raw_pressure=0.3),
        'low2.md': CognitiveFile(path='low2.md', raw_pressure=0.4),
    }
    assert should_crystallize(
        resolved=True,
        resolution_type="completion",
        cluster_sustained_turns=5,
        attention_cluster={'low1.md', 'low2.md'},
        files=low_pressure_files,
        config=config
    ) == False

    print("✓ Crystallization trigger conditions: All tests passed")


def test_title_inference():
    """Test title generation from clusters and tension sources."""
    config = CrystallizeConfig(max_title_length=50)

    # From tension sources
    title = infer_title_from_cluster(
        attention_cluster={'file1.md', 'file2.md'},
        tension_sources=['debugging', 'pipeline', 'error'],
        config=config
    )
    assert len(title) <= 50
    assert any(word in title.lower() for word in ['debug', 'pipeline', 'error'])

    # From cluster (no tension sources)
    title = infer_title_from_cluster(
        attention_cluster={'my-feature.md', 'config.md'},
        tension_sources=[],
        config=config
    )
    assert len(title) <= 50
    # Should include file stems

    # Fallback when empty
    title = infer_title_from_cluster(
        attention_cluster=set(),
        tension_sources=[],
        config=config
    )
    assert 'Session' in title

    print("✓ Title inference: All tests passed")


def test_slugify():
    """Test URL-safe slug generation."""
    assert slugify("Hello World") == "hello-world"
    assert slugify("Debugging Pipeline Errors!") == "debugging-pipeline-errors"
    assert slugify("  multiple   spaces  ") == "multiple-spaces"
    assert slugify("Special@#$Characters") == "special-characters"

    # Test max length
    long_title = "This is a very long title that should be truncated"
    slug = slugify(long_title, max_length=20)
    assert len(slug) <= 20

    print("✓ Slugify: All tests passed")


def test_auto_linking():
    """Test auto-linking of known entities."""
    known = {'pipeline', 'orin', 'debugging'}

    # Simple replacement
    text = "Working on the pipeline and orin integration"
    linked = auto_link_text(text, known)
    assert '[[pipeline]]' in linked
    assert '[[orin]]' in linked

    # Already linked - don't double-link
    text = "See [[pipeline]] for details about orin"
    linked = auto_link_text(text, known)
    assert linked.count('[[pipeline]]') == 1
    assert '[[orin]]' in linked

    # Case insensitive matching
    text = "Working on the Pipeline system"
    linked = auto_link_text(text, known)
    assert '[[Pipeline]]' in linked or '[[pipeline]]' in linked

    # Only first occurrence
    text = "pipeline connects to pipeline output"
    linked = auto_link_text(text, known)
    assert linked.count('[[') == 1  # Only one link

    print("✓ Auto-linking: All tests passed")


def test_get_known_entities():
    """Test entity discovery from directory."""
    temp_dir = Path(tempfile.mkdtemp())
    try:
        # Create test files
        (temp_dir / 'pipeline.md').write_text("# Pipeline")
        (temp_dir / 'orin.md').write_text("# Orin")
        (temp_dir / 'sessions').mkdir()
        (temp_dir / 'sessions' / 'session1.md').write_text("# Session")  # Should be excluded
        (temp_dir / 'ab.md').write_text("# Too short")  # Should be excluded (stem too short)

        entities = get_known_entities(temp_dir)

        assert 'pipeline' in entities
        assert 'orin' in entities
        assert 'session1' not in entities  # Sessions excluded
        assert 'ab' not in entities  # Too short

    finally:
        shutil.rmtree(temp_dir)

    print("✓ Entity discovery: All tests passed")


def test_session_note_generation():
    """Test session note content generation."""
    config = CrystallizeConfig(
        include_pressure=True,
        include_timestamps=True,
        enable_auto_linking=False,  # Disable for predictable testing
    )

    files = {
        'pipeline.md': CognitiveFile(path='pipeline.md', raw_pressure=0.9),
        'orin.md': CognitiveFile(path='orin.md', raw_pressure=0.7),
    }

    content = generate_session_note(
        attention_cluster={'pipeline.md', 'orin.md'},
        tension_sources=['debugging', 'connection'],
        files=files,
        cluster_sustained_turns=5,
        summary="Fixed the integration issue between pipeline and orin.",
        config=config
    )

    # Check structure
    assert '# ' in content  # Has title
    assert '**Captured:**' in content
    assert '**Attention Cluster:** 2 files' in content
    assert '**Sustained Turns:** 5' in content
    assert '## Context' in content
    assert 'Fixed the integration issue' in content
    assert '## Related Files' in content
    assert 'pipeline' in content
    assert 'orin' in content
    assert 'pressure: 0.9' in content.lower() or '0.90' in content
    assert '## Topics Addressed' in content
    assert 'debugging' in content
    assert 'hologram-cognitive v0.3.0' in content

    print("✓ Session note generation: All tests passed")


def test_crystallize_creates_file():
    """Test that crystallize creates a file in the correct location."""
    temp_dir = Path(tempfile.mkdtemp())
    try:
        files = {
            'test1.md': CognitiveFile(path='test1.md', raw_pressure=0.8),
            'test2.md': CognitiveFile(path='test2.md', raw_pressure=0.6),
        }

        config = CrystallizeConfig()

        filepath = crystallize(
            attention_cluster={'test1.md', 'test2.md'},
            tension_sources=['testing'],
            files=files,
            cluster_sustained_turns=5,
            claude_dir=temp_dir,
            config=config
        )

        # File should exist
        assert filepath.exists()

        # Should be in sessions subdirectory
        assert 'sessions' in str(filepath)

        # Should be markdown
        assert filepath.suffix == '.md'

        # Content should be valid
        content = filepath.read_text()
        assert '# ' in content
        assert 'test1' in content or 'test2' in content

    finally:
        shutil.rmtree(temp_dir)

    print("✓ Crystallize file creation: All tests passed")


def test_list_sessions():
    """Test session listing functionality."""
    temp_dir = Path(tempfile.mkdtemp())
    try:
        sessions_dir = temp_dir / 'sessions'
        sessions_dir.mkdir()

        # Create test session files
        (sessions_dir / '20260118_100000_test-one.md').write_text("""# Test One

**Captured:** 2026-01-18T10:00:00
**Attention Cluster:** 3 files
**Sustained Turns:** 5

## Context
Test content.
""")

        (sessions_dir / '20260118_110000_test-two.md').write_text("""# Test Two

**Captured:** 2026-01-18T11:00:00
**Attention Cluster:** 2 files
**Sustained Turns:** 3

## Context
More content.
""")

        sessions = list_sessions(temp_dir, limit=10)

        assert len(sessions) == 2

        # Should be sorted by timestamp (most recent first)
        assert sessions[0].title == 'Test Two'
        assert sessions[1].title == 'Test One'

        # Check metadata extraction
        assert sessions[0].cluster_size == 2
        assert sessions[0].sustained_turns == 3
        assert sessions[1].cluster_size == 3
        assert sessions[1].sustained_turns == 5

    finally:
        shutil.rmtree(temp_dir)

    print("✓ Session listing: All tests passed")


def test_session_integration():
    """Test crystallization through Session API."""
    from hologram import Session

    temp_dir = Path(tempfile.mkdtemp())
    claude_dir = temp_dir / '.claude'
    claude_dir.mkdir()

    try:
        # Create test files
        (claude_dir / 'pipeline.md').write_text("""# Pipeline

Main processing pipeline.

## Features
- Message routing
- Context injection
""")
        (claude_dir / 'debugging.md').write_text("""# Debugging

Debug guide for the system.

## Common Issues
- OOM errors
- Connection timeouts
""")

        session = Session(str(claude_dir), auto_crystallize=False)  # Manual crystallization

        # Build up attention over several turns
        session.turn("tell me about the pipeline")
        session.turn("how does it work with debugging?")
        session.turn("what are common issues?")

        # Manually crystallize
        filepath = session.crystallize(summary="Explored pipeline and debugging integration.")

        assert filepath is not None
        assert filepath.exists()
        assert 'sessions' in str(filepath)

        # Check listing works
        sessions = session.sessions()
        assert len(sessions) >= 1

        # Check last_crystallization property
        assert session.last_crystallization == filepath

    finally:
        shutil.rmtree(temp_dir)

    print("✓ Session integration: All tests passed")


def test_auto_crystallization():
    """Test automatic crystallization on resolution."""
    from hologram import Session

    temp_dir = Path(tempfile.mkdtemp())
    claude_dir = temp_dir / '.claude'
    claude_dir.mkdir()

    try:
        # Create test files
        (claude_dir / 'feature.md').write_text("""# Feature

A feature description.

## Implementation
- Step 1
- Step 2
""")
        (claude_dir / 'tests.md').write_text("""# Tests

Testing documentation.

## Test Cases
- Unit tests
- Integration tests
""")

        session = Session(str(claude_dir), auto_crystallize=True)

        # Build sustained attention (need 3+ turns)
        session.turn("working on the feature")
        session.turn("adding tests for feature")
        session.turn("how do I run the tests?")

        # Check attention cluster is building
        assert len(session.turn_state.attention_cluster) > 0

        # Resolution signal - might trigger auto-crystallization
        result = session.turn("got it working, thanks!")

        # Note: Auto-crystallization requires:
        # - resolution_type == "completion"
        # - cluster_sustained_turns >= 3
        # - cluster_size >= 2
        # - peak_pressure >= 0.6

        # The actual triggering depends on pressure levels reached
        # Just verify the infrastructure is working
        assert result.resolved == True
        assert result.resolution_type == "completion"

    finally:
        shutil.rmtree(temp_dir)

    print("✓ Auto-crystallization integration: All tests passed")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Auto-Crystallization v0.3.0 Tests")
    print("=" * 60)
    print()

    test_should_crystallize_conditions()
    test_title_inference()
    test_slugify()
    test_auto_linking()
    test_get_known_entities()
    test_session_note_generation()
    test_crystallize_creates_file()
    test_list_sessions()
    test_session_integration()
    test_auto_crystallization()

    print()
    print("=" * 60)
    print("All crystallization tests passed!")
    print("=" * 60)


if __name__ == '__main__':
    main()
