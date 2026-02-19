"""
High-level session management for hologram-cognitive.

Provides the Session class and convenience functions for easy integration
with any LLM platform.

Usage:
    from hologram import Session, route
    
    # One-liner
    ctx = route('.claude', "message")
    
    # Session-based
    session = Session('.claude')
    result = session.turn("message")
    session.note("Title", "Body")
    session.save()
"""

import os
import re
import json
import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass, field

from .router import create_router_from_directory
from .system import process_turn as _process_turn, get_context as _get_context
from .turn_state import (
    TurnState,
    TurnStateConfig,
    load_turn_state,
    save_turn_state,
    apply_inherited_pressure,
    compute_next_state,
)
from .resolution import detect_resolution, analyze_query
from .crystallize import (
    CrystallizeConfig,
    should_crystallize,
    crystallize as _crystallize,
    list_sessions,
    SessionInfo,
)


@dataclass
class TurnResult:
    """
    Result of processing a conversation turn.

    Attributes:
        activated: Files activated by this turn's message
        hot: Files at CRITICAL pressure (≥0.8)
        warm: Files at HIGH pressure (≥0.5, <0.8)
        cold: Files below HIGH pressure (<0.5)
        injection: Formatted context string ready for prompt injection
        turn_number: Current turn count

        # v0.3.0 additions
        resolved: Whether resolution was detected
        resolution_type: "completion", "topic_change", or "none"
        tension: Current tension level (0.0-1.0)
        cluster_size: Number of files in attention cluster
        pending_crystallization: Whether crystallization should be triggered
    """
    activated: List[str]
    hot: List[str]
    warm: List[str]
    cold: List[str]
    injection: str
    turn_number: int

    # v0.3.0 - turn state metadata
    resolved: bool = False
    resolution_type: str = "none"
    tension: float = 0.0
    cluster_size: int = 0
    pending_crystallization: bool = False

    def __str__(self) -> str:
        """String representation returns injection text."""
        return self.injection

    def __repr__(self) -> str:
        return f"TurnResult(turn={self.turn_number}, hot={len(self.hot)}, warm={len(self.warm)}, activated={len(self.activated)}, tension={self.tension:.2f})"


class Session:
    """
    High-level memory session for any LLM platform.
    
    Manages the full lifecycle of pressure-based context routing:
    - Initialize from .claude directory
    - Route messages and get injection context
    - Write memory notes with auto-linking
    - Save state for persistence
    
    Usage:
        session = Session('.claude')
        
        # Each conversation turn
        result = session.turn("user message")
        # Use result.injection in your prompt/context
        
        # Write important things to memory
        session.note("Topic", "Content here", links=['[[related.md]]'])
        
        # Save at end of session
        session.save()
    
    Args:
        claude_dir: Path to .claude directory (created if missing)
        auto_bootstrap: If True, read MEMORY.md for configuration
        instance_id: Identifier for this session instance
    """
    
    def __init__(
        self,
        claude_dir: str = '.claude',
        auto_bootstrap: bool = False,
        instance_id: str = 'default',
        enable_turn_state: bool = True,  # v0.3.0
        auto_crystallize: bool = True,   # v0.3.0
    ):
        self.claude_dir = Path(claude_dir).resolve()
        self.instance_id = instance_id
        self._router = None
        self._system = None
        self._last_result: Optional[TurnResult] = None
        self._config: Dict[str, Any] = {}

        # v0.3.0 - turn state inheritance
        self._enable_turn_state = enable_turn_state
        self._turn_state: Optional[TurnState] = None
        self._turn_state_config = TurnStateConfig()

        # v0.3.0 - auto-crystallization
        self._auto_crystallize = auto_crystallize
        self._crystallize_config = CrystallizeConfig()
        self._last_crystallization: Optional[Path] = None

        if auto_bootstrap:
            self._load_memory_config()

        self._init_router()

        # Load turn state after router init
        if self._enable_turn_state:
            self._turn_state = load_turn_state(self.claude_dir)

    def _safe_path(self, *parts: str) -> Path:
        """
        Safely join path parts and ensure the result is within claude_dir.

        Args:
            *parts: Path parts to join

        Returns:
            Resolved Path object

        Raises:
            ValueError: If the resulting path is outside claude_dir
        """
        # Join parts and resolve to absolute path
        path = self.claude_dir.joinpath(*parts).resolve()

        try:
            # is_relative_to ensures the path is under claude_dir
            if not path.is_relative_to(self.claude_dir):
                raise ValueError(f"Path traversal detected: {path} is outside {self.claude_dir}")
        except ValueError:
            # Handle cases where path is on a different drive or other issues
            raise ValueError(f"Path traversal detected: {path} is outside {self.claude_dir}")

        return path

    def _load_memory_config(self) -> None:
        """Load configuration from MEMORY.md if present."""
        memory_file = self.claude_dir / 'MEMORY.md'
        if memory_file.exists():
            content = memory_file.read_text()
            self._config['memory_md_present'] = True
            self._config['memory_md_content'] = content
            # Future: parse YAML frontmatter for settings
    
    def _init_router(self) -> None:
        """Initialize the router from directory."""
        if not self.claude_dir.exists():
            self.claude_dir.mkdir(parents=True)
        
        self._router = create_router_from_directory(str(self.claude_dir))
        self._system = self._router.system
    
    @property
    def system(self):
        """Access the underlying CognitiveSystem."""
        return self._system
    
    @property
    def router(self):
        """Access the underlying HologramRouter."""
        return self._router
    
    @property
    def last_result(self) -> Optional[TurnResult]:
        """Get the result from the most recent turn."""
        return self._last_result

    @property
    def turn_state(self) -> Optional[TurnState]:
        """Get the current turn state (v0.3.0)."""
        return self._turn_state
    
    def turn(self, message: str) -> TurnResult:
        """
        Process a conversation turn.

        Routes the message through the pressure system, activates relevant files,
        propagates pressure, and returns formatted context for injection.

        v0.3.0: Now includes turn-state inheritance:
        - Applies inherited pressure from previous turn
        - Detects resolution (completion, topic change)
        - Computes next turn state
        - Tracks attention clusters and tension

        Args:
            message: User message to route

        Returns:
            TurnResult containing injection text and metadata
        """
        # v0.3.0 - Apply inherited pressure before processing
        if self._enable_turn_state and self._turn_state:
            apply_inherited_pressure(
                self._system.files,
                self._turn_state.pressure_inheritance,
                self._turn_state_config
            )

        # v0.3.0 - Detect resolution before processing
        prev_tension = self._turn_state.unresolved_tension if self._turn_state else 0.0
        resolved, resolution_type = detect_resolution(message, prev_tension)

        # Process through the system
        result = _process_turn(self._system, message)
        context = _get_context(self._system)

        # Categorize files by RELATIVE pressure tier (top N by pressure)
        # This aligns with injection format and scales with any file count
        all_files_sorted = sorted(
            self._system.files.items(),
            key=lambda x: x[1].raw_pressure,
            reverse=True
        )

        # Relative tier sizes (same as injection)
        hot_count = min(5, len(all_files_sorted))
        warm_count = min(10, max(0, len(all_files_sorted) - hot_count))

        hot = [name for name, _ in all_files_sorted[:hot_count]]
        warm = [name for name, _ in all_files_sorted[hot_count:hot_count + warm_count]]
        cold = [name for name, _ in all_files_sorted[hot_count + warm_count:]]

        # v0.3.0 - Compute next turn state
        next_state = None
        if self._enable_turn_state:
            prev_state = self._turn_state or TurnState()
            activated_set = set(result.activated) if hasattr(result.activated, '__iter__') else set()

            next_state = compute_next_state(
                prev_state=prev_state,
                activated_files=activated_set,
                files=self._system.files,
                query=message,
                resolved=resolved,
                resolution_type=resolution_type,
                config=self._turn_state_config
            )

            # Save turn state
            self._turn_state = next_state
            save_turn_state(next_state, self.claude_dir)

            # v0.3.0 - Auto-crystallization on resolution
            if self._auto_crystallize and should_crystallize(
                resolved=resolved,
                resolution_type=resolution_type,
                cluster_sustained_turns=next_state.cluster_sustained_turns,
                attention_cluster=next_state.attention_cluster,
                files=self._system.files,
                config=self._crystallize_config
            ):
                # Trigger crystallization
                filepath = _crystallize(
                    attention_cluster=next_state.attention_cluster,
                    tension_sources=next_state.tension_sources,
                    files=self._system.files,
                    cluster_sustained_turns=next_state.cluster_sustained_turns,
                    claude_dir=self.claude_dir,
                    config=self._crystallize_config
                )
                self._last_crystallization = filepath

                # Register the new session note with the router
                rel_path = str(filepath.relative_to(self.claude_dir))
                content = filepath.read_text()
                self._system.add_file(rel_path, content)

                # Mark crystallization complete
                next_state.pending_crystallization = False

        self._last_result = TurnResult(
            activated=list(result.activated) if hasattr(result.activated, '__iter__') else result.activated,
            hot=hot,
            warm=warm,
            cold=cold,
            injection=self._format_injection(context),
            turn_number=self._system.current_turn,
            # v0.3.0 additions
            resolved=resolved,
            resolution_type=resolution_type,
            tension=next_state.unresolved_tension if next_state else 0.0,
            cluster_size=len(next_state.attention_cluster) if next_state else 0,
            pending_crystallization=next_state.pending_crystallization if next_state else False,
        )

        return self._last_result
    
    def _format_injection(self, context: Any) -> str:
        """
        Format context for injection into prompt.

        Uses RELATIVE tiers based on pressure ranking (top N = HOT, next M = WARM).
        This scales properly regardless of file count or conservation budget.

        Files with '<!-- WARM CONTEXT ENDS ABOVE THIS LINE -->' markers
        will only have their summary (above the marker) injected for HOT,
        preserving the designed summary/full-content structure.
        """
        if isinstance(context, str):
            return context

        WARM_MARKER = "<!-- WARM CONTEXT ENDS ABOVE THIS LINE -->"

        def get_hot_content(cf) -> str:
            """Get HOT content - summary if marker exists, else full."""
            if WARM_MARKER in cf.content:
                # Use designed summary (content above marker)
                return cf.content.split(WARM_MARKER)[0].strip()
            # No marker - use full content but cap at 3000 chars
            if len(cf.content) > 3000:
                return cf.content[:3000] + "\n\n... (truncated, use Read for full content)"
            return cf.content

        # Use RELATIVE tiers: sort all files by pressure and take top N
        # This scales properly with any number of files
        all_files = sorted(
            self._system.files.values(),
            key=lambda f: f.raw_pressure,
            reverse=True
        )

        # Relative tier sizes (configurable)
        hot_count = min(5, len(all_files))
        warm_count = min(10, max(0, len(all_files) - hot_count))

        hot_files = all_files[:hot_count]
        warm_files = all_files[hot_count:hot_count + warm_count]
        cold_files = all_files[hot_count + warm_count:]

        parts = []

        if hot_files:
            parts.append("=== ACTIVE MEMORY ===\n")
            for cf in hot_files:
                hot_content = get_hot_content(cf)
                parts.append(f"## {cf.path}\n{hot_content}\n")

        if warm_files:
            parts.append("\n=== RELATED CONTEXT ===\n")
            for cf in warm_files:
                # Headers only for warm files
                lines = cf.content.split('\n')
                headers = [l for l in lines if l.startswith('#')]
                parts.append(f"## {cf.path}\n" + '\n'.join(headers[:5]) + "\n")

        if cold_files:
            parts.append("\n=== AVAILABLE (inactive) ===\n")
            cold_names = [cf.path for cf in cold_files[:10]]
            parts.append(', '.join(cold_names) + "\n")

        return '\n'.join(parts)
    
    def note(
        self, 
        title: str, 
        body: str = '', 
        links: Optional[List[str]] = None,
        subdir: str = 'notes'
    ) -> Path:
        """
        Write a memory note to the knowledge base.
        
        Creates a timestamped markdown file and registers it with the router
        for immediate routing availability.
        
        Args:
            title: Note title (also used in filename)
            body: Main content of the note
            links: List of [[wiki-links]] to append (auto-formatted)
            subdir: Subdirectory under .claude/ (default: 'notes')
            
        Returns:
            Path to the created file
        """
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:48] or 'note'
        
        # Safely resolve subdirectory and final path
        notes_dir = self._safe_path(subdir)
        notes_dir.mkdir(parents=True, exist_ok=True)
        
        path = self._safe_path(subdir, f"{ts}_{slug}.md")
        
        content_parts = [
            f"# {title}",
            f"\n**Captured:** {datetime.datetime.now().isoformat()}\n",
        ]
        
        if body:
            content_parts.append(body)
        
        if links:
            content_parts.append("\n## Links")
            for link in links:
                # Ensure [[bracket]] format
                if not link.startswith('[['):
                    if not link.endswith(']]'):
                        link = f"[[{link}]]"
                content_parts.append(f"- {link}")
        
        content = '\n'.join(content_parts)
        path.write_text(content)
        
        # Register with router immediately (no reload needed)
        rel_path = str(path.relative_to(self.claude_dir))
        self._system.add_file(rel_path, content)
        
        return path
    
    def pin(self, content: str, anchor_file: str = 'anchors.md') -> Path:
        """
        Append content to a rolling anchor file.
        
        Unlike note(), this appends to a single file rather than creating
        new files. Useful for accumulating related information.
        
        Args:
            content: Content to append
            anchor_file: Filename for the anchor (default: 'anchors.md')
            
        Returns:
            Path to the anchor file
        """
        path = self._safe_path(anchor_file)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        entry = f"\n---\n**{ts}**\n\n{content}\n"
        
        if path.exists():
            with open(path, 'a') as f:
                f.write(entry)
            # Re-read full content for router update
            full_content = path.read_text()
        else:
            full_content = f"# Anchors\n\nRolling notes and pinned content.\n{entry}"
            path.write_text(full_content)
        
        # Update in router using relative path
        rel_path = str(path.relative_to(self.claude_dir))
        self._system.add_file(rel_path, full_content)
        
        return path
    
    def save(self) -> None:
        """
        Save state to disk.
        
        Persists the current pressure state and turn history to JSON files
        in the .claude directory.
        """
        state_file = self.claude_dir / 'hologram_state.json'
        self._system.save_state(str(state_file))
    
    def status(self) -> Dict[str, Any]:
        """
        Get current memory status.
        
        Returns:
            Dict with directory, file count, turn number, and hot files
        """
        return {
            'directory': str(self.claude_dir),
            'files': len(self._system.files),
            'turn': self._system.current_turn,
            'instance': self.instance_id,
            'hot': self._last_result.hot[:5] if self._last_result else [],
            'warm': self._last_result.warm[:5] if self._last_result else [],
        }
    
    def files_by_pressure(self, min_pressure: float = 0.0) -> List[tuple]:
        """
        Get files sorted by pressure.
        
        Args:
            min_pressure: Minimum pressure threshold (default: 0.0)
            
        Returns:
            List of (filename, pressure) tuples, sorted descending
        """
        return [
            (name, cf.raw_pressure)
            for name, cf in sorted(
                self._system.files.items(),
                key=lambda x: -x[1].raw_pressure
            )
            if cf.raw_pressure >= min_pressure
        ]
    
    def get_file(self, name: str) -> Optional[Any]:
        """
        Get a specific file by name.

        Args:
            name: Filename (relative to .claude/)

        Returns:
            CognitiveFile or None if not found
        """
        return self._system.files.get(name)

    # =========================================================================
    # v0.3.0 - Crystallization
    # =========================================================================

    def crystallize(self, summary: Optional[str] = None) -> Optional[Path]:
        """
        Crystallize the current attention cluster into a session note.

        Creates a markdown file in .claude/sessions/ capturing the current
        working context. Usually called automatically when resolution is
        detected after sustained attention.

        Args:
            summary: Optional user-provided summary to include

        Returns:
            Path to created session note, or None if conditions not met
        """
        if not self._enable_turn_state or not self._turn_state:
            return None

        state = self._turn_state

        # Check if crystallization is warranted
        if not state.attention_cluster:
            return None

        # Force crystallization even if conditions not fully met
        # (manual call overrides automatic thresholds)
        filepath = _crystallize(
            attention_cluster=state.attention_cluster,
            tension_sources=state.tension_sources,
            files=self._system.files,
            cluster_sustained_turns=state.cluster_sustained_turns,
            claude_dir=self.claude_dir,
            summary=summary,
            config=self._crystallize_config
        )

        self._last_crystallization = filepath

        # Register the new file with the router
        rel_path = str(filepath.relative_to(self.claude_dir))
        content = filepath.read_text()
        self._system.add_file(rel_path, content)

        return filepath

    def sessions(self, limit: int = 20) -> List[SessionInfo]:
        """
        List recent session notes.

        Args:
            limit: Maximum sessions to return (default: 20)

        Returns:
            List of SessionInfo, most recent first
        """
        return list_sessions(self.claude_dir, self._crystallize_config, limit)

    @property
    def last_crystallization(self) -> Optional[Path]:
        """Get the path to the most recent crystallization (if any)."""
        return self._last_crystallization


# Module-level default session for convenience functions
_default_session: Optional[Session] = None


def get_session(claude_dir: str = '.claude') -> Session:
    """
    Get or create the default session.
    
    Reuses existing session if the directory matches.
    
    Args:
        claude_dir: Path to .claude directory
        
    Returns:
        Session instance
    """
    global _default_session
    target = Path(claude_dir).resolve()
    
    if _default_session is None or _default_session.claude_dir != target:
        _default_session = Session(claude_dir)
    
    return _default_session


def route(claude_dir: str = '.claude', message: str = '') -> Dict[str, Any]:
    """
    One-shot routing convenience function.
    
    Creates/reuses a session, processes the message, saves state,
    and returns results as a dict.
    
    Args:
        claude_dir: Path to .claude directory
        message: Message to route
        
    Returns:
        Dict with 'injection', 'hot', 'warm', 'cold', 'activated', 'turn'
    """
    session = get_session(claude_dir)
    result = session.turn(message)
    session.save()
    
    return {
        'injection': result.injection,
        'hot': result.hot,
        'warm': result.warm,
        'cold': result.cold,
        'activated': result.activated,
        'turn': result.turn_number,
    }


def bootstrap(claude_dir: str = '.claude') -> Session:
    """
    Initialize a session with auto-bootstrap from MEMORY.md.
    
    Args:
        claude_dir: Path to .claude directory
        
    Returns:
        Configured Session instance
    """
    return Session(claude_dir, auto_bootstrap=True)
