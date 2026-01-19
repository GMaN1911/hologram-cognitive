#!/usr/bin/env python3
"""
hologram-daemon.py - Universal memory routing for any LLM

Usage:
    python hologram-daemon.py <claude_dir> <message>
    python hologram-daemon.py .claude "What about the T3 architecture?"

Or import as module:
    from hologram_daemon import MemorySession
    session = MemorySession('.claude')
    context = session.pre_response("user message here")
    # ... generate response ...
    session.post_response(significant=True, note_title="Topic discussed")
"""

import os
import sys
import re
import datetime
from pathlib import Path

class MemorySession:
    def __init__(self, claude_dir: str = '.claude'):
        self.claude_dir = Path(claude_dir)
        self._ensure_hologram()
        
        from hologram.router import create_router_from_directory
        self.router = create_router_from_directory(str(self.claude_dir))
        self.system = self.router.system
        self.last_result = None
    
    def _ensure_hologram(self):
        """Install hologram-cognitive if missing."""
        try:
            import hologram
        except ImportError:
            import subprocess
            subprocess.run([
                sys.executable, '-m', 'pip', 'install', 
                'hologram-cognitive', '--quiet'
            ], check=True)
    
    def pre_response(self, message: str) -> str:
        """Route message, return injection context."""
        from hologram.system import process_turn, get_context
        
        self.last_result = process_turn(self.system, message)
        context = get_context(self.system)
        return context
    
    def post_response(self, significant: bool = False, note_title: str = None, note_body: str = None):
        """Save state, optionally write memory note."""
        if significant and note_title:
            self.write_note(note_title, note_body or "")
        self.system.save_state(str(self.claude_dir / 'hologram_state.json'))
    
    def write_note(self, title: str, body: str, subdir: str = 'notes'):
        """Write a memory note to the knowledge base."""
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:48]
        
        notes_dir = self.claude_dir / subdir
        notes_dir.mkdir(parents=True, exist_ok=True)
        
        path = notes_dir / f"{ts}_{slug}.md"
        content = f"# {title}\n\n**Captured:** {datetime.datetime.now().isoformat()}\n\n{body}\n"
        
        path.write_text(content)
        self.system.add_file(str(path), content)
        return path
    
    def get_hot_files(self, n: int = 5) -> list:
        """Return top N files by pressure."""
        return sorted(
            self.system.files.items(),
            key=lambda x: -x[1].raw_pressure
        )[:n]
    
    def status(self) -> dict:
        """Current memory status."""
        return {
            'files': len(self.system.files),
            'turn': self.system.current_turn,
            'hot': [name for name, _ in self.get_hot_files(5)]
        }


def main():
    if len(sys.argv) < 3:
        print("Usage: python hologram_daemon.py <claude_dir> <message>")
        sys.exit(1)
    
    claude_dir = sys.argv[1]
    message = ' '.join(sys.argv[2:])
    
    session = MemorySession(claude_dir)
    context = session.pre_response(message)
    
    print("=== STATUS ===")
    status = session.status()
    print(f"Files: {status['files']} | Turn: {status['turn']}")
    print(f"HOT: {', '.join(status['hot'])}")
    
    print("\n=== ACTIVATED ===")
    for f in session.last_result.activated[:7]:
        print(f"  → {f}")
    
    print("\n=== CONTEXT (truncated) ===")
    print(str(context)[:1500])
    
    session.post_response()
    print("\n[State saved]")


if __name__ == '__main__':
    main()
