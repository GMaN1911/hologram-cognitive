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
    """
    activated: List[str]
    hot: List[str]
    warm: List[str]
    cold: List[str]
    injection: str
    turn_number: int
    
    def __str__(self) -> str:
        """String representation returns injection text."""
        return self.injection
    
    def __repr__(self) -> str:
        return f"TurnResult(turn={self.turn_number}, hot={len(self.hot)}, warm={len(self.warm)}, activated={len(self.activated)})"


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
        instance_id: str = 'default'
    ):
        self.claude_dir = Path(claude_dir).resolve()
        self.instance_id = instance_id
        self._router = None
        self._system = None
        self._last_result: Optional[TurnResult] = None
        self._config: Dict[str, Any] = {}
        
        if auto_bootstrap:
            self._load_memory_config()
        
        self._init_router()
    
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
    
    def turn(self, message: str) -> TurnResult:
        """
        Process a conversation turn.
        
        Routes the message through the pressure system, activates relevant files,
        propagates pressure, and returns formatted context for injection.
        
        Args:
            message: User message to route
            
        Returns:
            TurnResult containing injection text and metadata
        """
        # Process through the system
        result = _process_turn(self._system, message)
        context = _get_context(self._system)
        
        # Categorize files by pressure tier
        hot, warm, cold = [], [], []
        for name, cf in self._system.files.items():
            if cf.raw_pressure >= 0.8:
                hot.append(name)
            elif cf.raw_pressure >= 0.5:
                warm.append(name)
            else:
                cold.append(name)
        
        # Sort by pressure within each tier
        hot = sorted(hot, key=lambda n: -self._system.files[n].raw_pressure)
        warm = sorted(warm, key=lambda n: -self._system.files[n].raw_pressure)
        cold = sorted(cold, key=lambda n: -self._system.files[n].raw_pressure)
        
        self._last_result = TurnResult(
            activated=list(result.activated) if hasattr(result.activated, '__iter__') else result.activated,
            hot=hot,
            warm=warm,
            cold=cold,
            injection=self._format_injection(context),
            turn_number=self._system.current_turn
        )
        
        return self._last_result
    
    def _format_injection(self, context: Any) -> str:
        """
        Format context for injection into prompt.
        
        Converts the raw context dict into a formatted string suitable
        for including in an LLM prompt.
        """
        if isinstance(context, str):
            return context
        
        # Handle dict format from get_context
        if isinstance(context, dict):
            parts = []
            
            if 'HOT' in context and context['HOT']:
                parts.append("=== ACTIVE MEMORY ===\n")
                for cf in context['HOT'][:5]:  # Limit to top 5
                    parts.append(f"## {cf.path}\n{cf.content}\n")
            
            if 'WARM' in context and context['WARM']:
                parts.append("\n=== RELATED CONTEXT ===\n")
                for cf in context['WARM'][:3]:  # Limit to top 3
                    # Headers only for warm files
                    lines = cf.content.split('\n')
                    headers = [l for l in lines if l.startswith('#')]
                    parts.append(f"## {cf.path}\n" + '\n'.join(headers[:5]) + "\n")
            
            if 'COLD' in context and context['COLD']:
                parts.append("\n=== AVAILABLE (inactive) ===\n")
                cold_names = [cf.path for cf in context['COLD'][:10]]
                parts.append(', '.join(cold_names) + "\n")
            
            return '\n'.join(parts)
        
        return str(context)
    
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
        
        notes_dir = self.claude_dir / subdir
        notes_dir.mkdir(parents=True, exist_ok=True)
        
        path = notes_dir / f"{ts}_{slug}.md"
        
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
        path = self.claude_dir / anchor_file
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
        
        # Update in router
        self._system.add_file(anchor_file, full_content)
        
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
