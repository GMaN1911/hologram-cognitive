#!/usr/bin/env python3
"""
UserPromptSubmit hook for Claude Code using hologram-cognitive.

Installation:
    1. Copy to .claude/hooks/user-prompt-submit.py
    2. chmod +x .claude/hooks/user-prompt-submit.py
    3. Ensure hologram-cognitive is installed: pip install hologram-cognitive

Usage:
    Called automatically by Claude Code before each user message.
    Injects relevant memory context based on pressure dynamics.
"""

import sys
import json
import traceback
from pathlib import Path

try:
    from hologram.claude_cognitive import HologramBackend

    # Read user prompt (claude-cognitive JSON format)
    try:
        data = json.load(sys.stdin)
        user_prompt = data.get('prompt', '')
    except:
        user_prompt = sys.stdin.read().strip()

    # Find .claude directory (search up from cwd)
    claude_dir = None
    for potential_dir in [Path.cwd()] + list(Path.cwd().parents):
        test_dir = potential_dir / '.claude'
        if test_dir.exists() and test_dir.is_dir():
            claude_dir = test_dir
            break

    if claude_dir is None:
        print("# (No .claude directory found)", file=sys.stderr)
        sys.exit(0)

    # Route through hologram
    backend = HologramBackend(
        claude_dir=str(claude_dir),
        auto_save=True,
        max_injection_chars=25000
    )

    result = backend.route_message(user_prompt, return_format='claude-cognitive')

    # Output injection for Claude Code
    print(result['injection'])

    # Debug info to stderr (visible in Claude Code console)
    print(
        f"[hologram] Turn {result['turn']}: "
        f"{result['stats']['hot_count']} hot, "
        f"{result['stats']['warm_count']} warm, "
        f"{result['stats']['cold_count']} cold "
        f"({result['stats']['injection_chars']:,} chars)",
        file=sys.stderr
    )

except ImportError as e:
    print(f"# (hologram-cognitive not installed: {e})", file=sys.stderr)
    print("# Memory context unavailable")

except Exception as e:
    print(f"# (Memory system error: {e})", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    print("# Memory context unavailable this turn")
