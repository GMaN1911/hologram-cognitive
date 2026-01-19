#!/usr/bin/env python3
"""
SessionStart hook for Claude Code using hologram-cognitive.

Installation:
    1. Copy to .claude/hooks/session-start.py
    2. chmod +x .claude/hooks/session-start.py
    3. Ensure hologram-cognitive is installed: pip install hologram-cognitive

Usage:
    Called automatically by Claude Code when a new session starts.
    Displays memory status and top hot files.
"""

import sys
import traceback
from pathlib import Path

try:
    from hologram import Session

    # Find .claude directory
    claude_dir = None
    for potential_dir in [Path.cwd()] + list(Path.cwd().parents):
        test_dir = potential_dir / '.claude'
        if test_dir.exists() and test_dir.is_dir():
            claude_dir = test_dir
            break

    if claude_dir is None:
        print("# (No .claude directory found - memory disabled)", file=sys.stderr)
        sys.exit(0)

    # Load session
    session = Session(str(claude_dir))
    status = session.status()

    # Get top files
    hot_files = [name for name, _ in session.files_by_pressure(0.8)[:5]]
    warm_files = [name for name, _ in session.files_by_pressure(0.5)[:5] if name not in hot_files]

    # Format injection
    injection = f"""╔══ MEMORY SYSTEM ACTIVE ══╗

📁 Directory: {claude_dir.name}
📄 Files: {status['files']} | Turn: {status['turn']}

🔥 HOT: {', '.join(hot_files[:3]) if hot_files else '(none)'}
🌡️  WARM: {', '.join(warm_files[:3]) if warm_files else '(none)'}

Memory context will be injected automatically as you work.
Use `hologram status .claude` to view full memory state.

╚════════════════════════════╝"""

    print(injection)

    # Debug info
    print(f"[hologram] Session loaded: {status['files']} files, turn {status['turn']}", file=sys.stderr)

except ImportError as e:
    print(f"# (hologram-cognitive not installed: {e})", file=sys.stderr)

except Exception as e:
    print(f"# (Memory system error: {e})", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
