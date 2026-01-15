"""
Claude Code integration hooks for hologram-cognitive.

This module provides hook functions that can be called by Claude Code's
hook system to automatically inject memory context during conversations.

Installation:
    1. Create .claude/hooks/ directory in your project
    2. Create hook files that import and call these functions
    3. Claude Code will automatically execute hooks at appropriate times

Example .claude/hooks/user-prompt-submit.sh:
    #!/usr/bin/env python3
    import sys; sys.path.insert(0, '/path/to/hologram-cognitive')
    from hologram.hooks import user_prompt_submit_hook
    user_prompt_submit_hook()
"""

import os
import sys
import json
from pathlib import Path
from typing import Optional, Dict, Any

from .session import Session, get_session


def find_claude_dir(start_path: Optional[str] = None) -> Optional[Path]:
    """
    Find .claude directory by searching up from current directory.

    Args:
        start_path: Starting directory (defaults to cwd)

    Returns:
        Path to .claude directory, or None if not found
    """
    current = Path(start_path or os.getcwd()).resolve()

    # Search up the directory tree
    for parent in [current] + list(current.parents):
        claude_dir = parent / '.claude'
        if claude_dir.exists() and claude_dir.is_dir():
            return claude_dir

    return None


def session_start_hook(claude_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Hook called when Claude Code session starts.

    Loads memory state and returns high-level status for injection.

    Args:
        claude_dir: Path to .claude directory (auto-detected if not provided)

    Returns:
        Dict with status information for injection
    """
    # Find .claude directory
    if claude_dir is None:
        found = find_claude_dir()
        if found is None:
            return {
                'enabled': False,
                'message': 'No .claude directory found'
            }
        claude_dir = str(found)

    # Initialize session
    try:
        session = get_session(claude_dir)
        status = session.status()

        # Get top files by pressure
        hot_files = [name for name, _ in session.files_by_pressure(0.8)[:5]]
        warm_files = [name for name, _ in session.files_by_pressure(0.5)[:5] if name not in hot_files]

        # Format injection message
        injection = f"""╔══ MEMORY SYSTEM ACTIVE ══╗

📁 Directory: {status['directory']}
📄 Files: {status['files']} | Turn: {status['turn']}

🔥 HOT: {', '.join(hot_files[:3]) if hot_files else '(none)'}
🌡️  WARM: {', '.join(warm_files[:3]) if warm_files else '(none)'}

Memory context will be injected automatically as you work.
Use `hologram status .claude` to view full memory state.

╚════════════════════════════╝"""

        # Return for injection
        return {
            'enabled': True,
            'injection': injection,
            'status': status,
            'hot': hot_files,
            'warm': warm_files
        }

    except Exception as e:
        return {
            'enabled': False,
            'error': str(e),
            'message': f'Failed to initialize memory: {e}'
        }


def user_prompt_submit_hook(
    user_message: Optional[str] = None,
    claude_dir: Optional[str] = None,
    max_injection_chars: int = 25000
) -> Dict[str, Any]:
    """
    Hook called when user submits a prompt in Claude Code.

    Routes the message through memory and returns injection context.

    Args:
        user_message: The user's message (from stdin if not provided)
        claude_dir: Path to .claude directory (auto-detected if not provided)
        max_injection_chars: Maximum characters for injection

    Returns:
        Dict with injection text and metadata
    """
    # Read user message from stdin if not provided
    if user_message is None:
        if not sys.stdin.isatty():
            user_message = sys.stdin.read().strip()
        else:
            user_message = ""

    # Find .claude directory
    if claude_dir is None:
        found = find_claude_dir()
        if found is None:
            return {
                'enabled': False,
                'injection': '',
                'message': 'No .claude directory found'
            }
        claude_dir = str(found)

    # Process turn
    try:
        session = get_session(claude_dir)
        result = session.turn(user_message)
        session.save()

        # Truncate injection if too long
        injection = result.injection
        if len(injection) > max_injection_chars:
            injection = injection[:max_injection_chars] + "\n\n... (truncated for length)"

        # Format for Claude Code injection
        formatted = f"""╔══ ATTENTION STATE [Turn {result.turn_number}] ══╗

║ 🔥 Hot: {len(result.hot)} │ 🌡️ Warm: {len(result.warm)} │ ❄️ Cold: {len(result.cold)} ║

║ Total chars: {len(injection):,} / {max_injection_chars:,} ║

╚══════════════════════════════════════╝

{injection}
"""

        return {
            'enabled': True,
            'injection': formatted,
            'turn': result.turn_number,
            'activated': result.activated,
            'hot': result.hot,
            'warm': result.warm,
            'cold': result.cold
        }

    except Exception as e:
        return {
            'enabled': False,
            'error': str(e),
            'injection': '',
            'message': f'Failed to process turn: {e}'
        }


def assistant_response_hook(
    assistant_message: Optional[str] = None,
    claude_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Hook called after Claude Code generates a response.

    Can be used to save important information to memory.

    Args:
        assistant_message: The assistant's response (from stdin if not provided)
        claude_dir: Path to .claude directory (auto-detected if not provided)

    Returns:
        Dict with status information
    """
    # This is a placeholder for future functionality
    # Could auto-extract important concepts and save as notes

    return {
        'enabled': True,
        'message': 'Response hook placeholder (not yet implemented)'
    }


def main():
    """
    CLI entry point for testing hooks.

    Usage:
        python -m hologram.hooks session-start
        python -m hologram.hooks user-prompt-submit "your message"
        echo "your message" | python -m hologram.hooks user-prompt-submit
    """
    import argparse

    parser = argparse.ArgumentParser(description='Test hologram-cognitive hooks')
    parser.add_argument('hook', choices=['session-start', 'user-prompt-submit', 'assistant-response'])
    parser.add_argument('message', nargs='?', help='Message for user-prompt-submit')
    parser.add_argument('--claude-dir', help='Path to .claude directory')
    parser.add_argument('--json', action='store_true', help='Output JSON')

    args = parser.parse_args()

    # Execute hook
    if args.hook == 'session-start':
        result = session_start_hook(args.claude_dir)
    elif args.hook == 'user-prompt-submit':
        result = user_prompt_submit_hook(args.message, args.claude_dir)
    elif args.hook == 'assistant-response':
        result = assistant_response_hook(args.message, args.claude_dir)
    else:
        print(f"Unknown hook: {args.hook}", file=sys.stderr)
        sys.exit(1)

    # Output result
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result.get('injection'):
            print(result['injection'])
        elif result.get('message'):
            print(result['message'])
        else:
            print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
