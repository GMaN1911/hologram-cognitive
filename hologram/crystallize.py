"""
Auto-Crystallization for Hologram Cognitive v0.3.0

Automatically creates session notes when sustained attention resolves.
This captures insights and working context before they decay.

Key concepts:
- Crystallization triggers when: resolution + sustained cluster + high pressure
- Session notes go to .claude/sessions/ with auto-linking
- Notes capture the attention cluster, tension sources, and context
"""

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class CrystallizeConfig:
    """Configuration for auto-crystallization."""

    # Trigger conditions
    min_cluster_size: int = 2           # Minimum files in cluster
    min_sustained_turns: int = 3        # Minimum turns cluster was stable
    min_peak_pressure: float = 0.6      # Minimum pressure for crystallization

    # Output
    sessions_subdir: str = 'sessions'   # Subdirectory for session notes
    max_title_length: int = 50          # Max chars in generated title
    include_pressure: bool = True       # Include pressure values in notes
    include_timestamps: bool = True     # Include timestamps

    # Auto-linking
    enable_auto_linking: bool = True    # Convert entity names to [[links]]


# =============================================================================
# Trigger Detection
# =============================================================================

def should_crystallize(
    resolved: bool,
    resolution_type: str,
    cluster_sustained_turns: int,
    attention_cluster: Set[str],
    files: Dict[str, any],  # path -> CognitiveFile
    config: Optional[CrystallizeConfig] = None
) -> bool:
    """
    Determine if crystallization should be triggered.

    Conditions (all must be true):
    1. Resolution detected (completion, not topic_change)
    2. Attention cluster was sustained (≥3 turns by default)
    3. Cluster has enough files (≥2 by default)
    4. Peak pressure was high (≥0.6 by default)

    Args:
        resolved: Whether resolution was detected
        resolution_type: "completion", "topic_change", or "none"
        cluster_sustained_turns: How long cluster was stable
        attention_cluster: Files in the attention cluster
        files: Dict of path -> CognitiveFile
        config: Crystallization configuration

    Returns:
        True if crystallization should trigger
    """
    if config is None:
        config = CrystallizeConfig()

    # Must be a completion (not topic change)
    if not resolved or resolution_type != "completion":
        return False

    # Cluster must be sustained
    if cluster_sustained_turns < config.min_sustained_turns:
        return False

    # Cluster must have enough files
    if len(attention_cluster) < config.min_cluster_size:
        return False

    # Check peak pressure in cluster
    peak_pressure = 0.0
    for path in attention_cluster:
        if path in files:
            pressure = getattr(files[path], 'raw_pressure', 0.0)
            peak_pressure = max(peak_pressure, pressure)

    if peak_pressure < config.min_peak_pressure:
        return False

    return True


# =============================================================================
# Title Generation
# =============================================================================

def infer_title_from_cluster(
    attention_cluster: Set[str],
    tension_sources: List[str],
    config: Optional[CrystallizeConfig] = None
) -> str:
    """
    Generate a descriptive title from the attention cluster and tension sources.

    Heuristics:
    1. Use tension sources if meaningful
    2. Fall back to cluster file names
    3. Capitalize and clean up

    Args:
        attention_cluster: Files in the cluster
        tension_sources: Topics from tension tracking
        config: Crystallization configuration

    Returns:
        Generated title string
    """
    if config is None:
        config = CrystallizeConfig()

    # Try tension sources first (they're what we were working on)
    if tension_sources:
        # Take first few meaningful words
        meaningful = [s for s in tension_sources if len(s) > 3][:3]
        if meaningful:
            title = ' '.join(meaningful).title()
            if len(title) <= config.max_title_length:
                return title

    # Fall back to cluster file names
    if attention_cluster:
        # Extract file stems, sorted by relevance (shorter names first)
        stems = sorted([
            Path(p).stem.replace('-', ' ').replace('_', ' ')
            for p in attention_cluster
        ], key=len)

        # Take first 2-3 stems
        title_parts = stems[:3]
        title = ' + '.join(title_parts).title()

        if len(title) > config.max_title_length:
            title = title[:config.max_title_length - 3] + '...'

        return title

    # Ultimate fallback
    return f"Session {datetime.now().strftime('%H:%M')}"


def slugify(text: str, max_length: int = 50) -> str:
    """
    Convert text to URL-safe slug.

    Args:
        text: Input text
        max_length: Maximum slug length

    Returns:
        Slugified string
    """
    # Lowercase and replace spaces/special chars with dashes
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower())
    # Remove leading/trailing dashes
    slug = slug.strip('-')
    # Collapse multiple dashes
    slug = re.sub(r'-+', '-', slug)
    # Truncate
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit('-', 1)[0]
    return slug


# =============================================================================
# Auto-Linking
# =============================================================================

def get_known_entities(claude_dir: Path) -> Set[str]:
    """
    Get all known entity names from .claude directory.

    Scans for .md files and extracts their stems as entity names.

    Args:
        claude_dir: Path to .claude directory

    Returns:
        Set of entity names (file stems)
    """
    entities = set()

    for md_file in claude_dir.rglob('*.md'):
        # Skip sessions directory
        if 'sessions' in str(md_file):
            continue
        stem = md_file.stem
        if len(stem) > 2:  # Skip very short names
            entities.add(stem)

    return entities


def auto_link_text(text: str, known_entities: Set[str]) -> str:
    """
    Replace known entity names with [[wiki-links]].

    Args:
        text: Input text
        known_entities: Set of known entity names

    Returns:
        Text with entities converted to wiki links
    """
    result = text

    # Sort by length (longest first) to avoid partial matches
    sorted_entities = sorted(known_entities, key=len, reverse=True)

    for entity in sorted_entities:
        # Match word boundaries, case insensitive
        pattern = rf'\b({re.escape(entity)})\b'
        # Only replace if not already a link
        if f'[[{entity}]]' not in result:
            result = re.sub(
                pattern,
                f'[[{entity}]]',
                result,
                flags=re.IGNORECASE,
                count=1  # Only first occurrence
            )

    return result


# =============================================================================
# Session Note Generation
# =============================================================================

def generate_session_note(
    attention_cluster: Set[str],
    tension_sources: List[str],
    files: Dict[str, any],
    cluster_sustained_turns: int,
    summary: Optional[str] = None,
    claude_dir: Optional[Path] = None,
    config: Optional[CrystallizeConfig] = None
) -> str:
    """
    Generate markdown content for a session note.

    Args:
        attention_cluster: Files in the attention cluster
        tension_sources: Topics from tension tracking
        files: Dict of path -> CognitiveFile
        cluster_sustained_turns: How long cluster was stable
        summary: Optional user-provided summary
        claude_dir: Path to .claude directory (for auto-linking)
        config: Crystallization configuration

    Returns:
        Markdown content for the session note
    """
    if config is None:
        config = CrystallizeConfig()

    # Get known entities for auto-linking
    known_entities = set()
    if config.enable_auto_linking and claude_dir:
        known_entities = get_known_entities(claude_dir)

    # Generate title
    title = infer_title_from_cluster(attention_cluster, tension_sources, config)

    # Build content
    lines = [f"# {title}", ""]

    # Metadata
    if config.include_timestamps:
        lines.append(f"**Captured:** {datetime.now().isoformat()}")
    lines.append(f"**Attention Cluster:** {len(attention_cluster)} files")
    lines.append(f"**Sustained Turns:** {cluster_sustained_turns}")
    lines.append("")

    # Summary section
    lines.append("## Context")
    lines.append("")
    if summary:
        if config.enable_auto_linking:
            summary = auto_link_text(summary, known_entities)
        lines.append(summary)
    else:
        lines.append("*Auto-crystallized from sustained attention.*")
    lines.append("")

    # Related files
    lines.append("## Related Files")
    lines.append("")

    # Sort by pressure (highest first)
    sorted_cluster = sorted(
        attention_cluster,
        key=lambda p: getattr(files.get(p), 'raw_pressure', 0) if p in files else 0,
        reverse=True
    )

    for path in sorted_cluster:
        stem = Path(path).stem
        # Auto-link if it's a known entity
        linked_name = f"[[{stem}]]" if stem in known_entities else stem

        if config.include_pressure and path in files:
            pressure = getattr(files[path], 'raw_pressure', 0)
            lines.append(f"- {linked_name} (pressure: {pressure:.2f})")
        else:
            lines.append(f"- {linked_name}")

    lines.append("")

    # Tension sources (topics addressed)
    if tension_sources:
        lines.append("## Topics Addressed")
        lines.append("")
        for source in tension_sources:
            if config.enable_auto_linking:
                source = auto_link_text(source, known_entities)
            lines.append(f"- {source}")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("*Auto-generated by hologram-cognitive v0.3.0*")

    return '\n'.join(lines)


# =============================================================================
# Main Crystallization Function
# =============================================================================

def crystallize(
    attention_cluster: Set[str],
    tension_sources: List[str],
    files: Dict[str, any],
    cluster_sustained_turns: int,
    claude_dir: Path,
    summary: Optional[str] = None,
    config: Optional[CrystallizeConfig] = None
) -> Path:
    """
    Create a session note from the resolved attention cluster.

    Args:
        attention_cluster: Files in the attention cluster
        tension_sources: Topics from tension tracking
        files: Dict of path -> CognitiveFile
        cluster_sustained_turns: How long cluster was stable
        claude_dir: Path to .claude directory
        summary: Optional user-provided summary
        config: Crystallization configuration

    Returns:
        Path to created session note
    """
    if config is None:
        config = CrystallizeConfig()

    # Ensure sessions directory exists
    sessions_dir = claude_dir / config.sessions_subdir
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # Generate content
    content = generate_session_note(
        attention_cluster=attention_cluster,
        tension_sources=tension_sources,
        files=files,
        cluster_sustained_turns=cluster_sustained_turns,
        summary=summary,
        claude_dir=claude_dir,
        config=config
    )

    # Generate filename
    title = infer_title_from_cluster(attention_cluster, tension_sources, config)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    slug = slugify(title)
    filename = f"{timestamp}_{slug}.md"

    # Write file
    filepath = sessions_dir / filename
    filepath.write_text(content)

    return filepath


# =============================================================================
# Session Listing
# =============================================================================

@dataclass
class SessionInfo:
    """Information about a session note."""
    path: Path
    title: str
    timestamp: datetime
    cluster_size: int
    sustained_turns: int


def list_sessions(
    claude_dir: Path,
    config: Optional[CrystallizeConfig] = None,
    limit: int = 20
) -> List[SessionInfo]:
    """
    List recent session notes.

    Args:
        claude_dir: Path to .claude directory
        config: Crystallization configuration
        limit: Maximum sessions to return

    Returns:
        List of SessionInfo, most recent first
    """
    if config is None:
        config = CrystallizeConfig()

    sessions_dir = claude_dir / config.sessions_subdir
    if not sessions_dir.exists():
        return []

    sessions = []

    for md_file in sessions_dir.glob('*.md'):
        try:
            # Parse filename: YYYYMMDD_HHMMSS_slug.md
            name = md_file.stem
            parts = name.split('_', 2)
            if len(parts) >= 2:
                date_str = parts[0]
                time_str = parts[1]
                timestamp = datetime.strptime(f"{date_str}_{time_str}", '%Y%m%d_%H%M%S')
            else:
                timestamp = datetime.fromtimestamp(md_file.stat().st_mtime)

            # Parse content for metadata
            content = md_file.read_text()

            # Extract title
            title_match = re.search(r'^# (.+)$', content, re.MULTILINE)
            title = title_match.group(1) if title_match else name

            # Extract cluster size
            cluster_match = re.search(r'\*\*Attention Cluster:\*\* (\d+)', content)
            cluster_size = int(cluster_match.group(1)) if cluster_match else 0

            # Extract sustained turns
            turns_match = re.search(r'\*\*Sustained Turns:\*\* (\d+)', content)
            sustained_turns = int(turns_match.group(1)) if turns_match else 0

            sessions.append(SessionInfo(
                path=md_file,
                title=title,
                timestamp=timestamp,
                cluster_size=cluster_size,
                sustained_turns=sustained_turns
            ))

        except Exception:
            # Skip malformed files
            continue

    # Sort by timestamp (most recent first)
    sessions.sort(key=lambda s: s.timestamp, reverse=True)

    return sessions[:limit]
