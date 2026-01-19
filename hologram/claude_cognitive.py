"""
Integration adapter for claude-cognitive ecosystem.

This module provides an adapter that allows claude-cognitive's context-router-v2.py
to use hologram-cognitive as its backend memory/routing engine.

Usage in context-router-v2.py:
    from hologram.claude_cognitive import HologramBackend

    backend = HologramBackend(claude_dir='.claude')
    result = backend.route_message(user_prompt)
    print(result['injection'])
"""

import sys
import json
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any

from .session import Session, get_session, TurnResult
from .system import CognitiveSystem


class HologramBackend:
    """
    Backend adapter for claude-cognitive ecosystem.

    Provides the same interface as context-router-v2.py but uses
    hologram-cognitive's pressure-based routing under the hood.

    This allows claude-cognitive hooks to seamlessly use hologram
    as the routing engine without changing hook scripts.
    """

    def __init__(
        self,
        claude_dir: str = '.claude',
        auto_save: bool = True,
        max_injection_chars: int = 25000
    ):
        """
        Initialize hologram backend for claude-cognitive.

        Args:
            claude_dir: Path to .claude directory
            auto_save: Automatically save state after each turn
            max_injection_chars: Maximum characters for injection
        """
        self.claude_dir = Path(claude_dir)
        self.auto_save = auto_save
        self.max_injection_chars = max_injection_chars
        self.session = get_session(claude_dir)
        self.history_file = self.claude_dir / 'hologram_history.jsonl'

    def route_message(
        self,
        user_prompt: str,
        return_format: str = 'claude-cognitive'
    ) -> Dict[str, Any]:
        """
        Route user message through hologram and return injection context.

        Args:
            user_prompt: The user's message
            return_format: 'claude-cognitive' or 'hologram' format

        Returns:
            Dict with injection context in requested format
        """
        # Process through hologram
        result = self.session.turn(user_prompt)

        # Save state if auto_save enabled
        if self.auto_save:
            self.session.save()
            self._append_history(result, user_prompt)

        # Format output based on requested format
        if return_format == 'claude-cognitive':
            return self._format_for_claude_cognitive(result)
        else:
            return self._format_for_hologram(result)

    def _format_for_claude_cognitive(self, result: TurnResult) -> Dict[str, Any]:
        """
        Format hologram result in claude-cognitive's expected format.

        This maintains compatibility with existing claude-cognitive hooks.
        """
        # Truncate injection if needed
        injection = result.injection
        if len(injection) > self.max_injection_chars:
            injection = injection[:self.max_injection_chars] + "\n\n... (truncated for length)"

        # Build tiered structure (claude-cognitive format)
        hot_files = []
        warm_files = []
        cold_files = []

        for name in result.hot:
            cf = self.session.system.files.get(name)
            if cf:
                hot_files.append({
                    'path': name,
                    'pressure': cf.raw_pressure,
                    'content': cf.content
                })

        for name in result.warm:
            cf = self.session.system.files.get(name)
            if cf:
                # Extract headers for warm files
                lines = cf.content.split('\n')
                headers = [l for l in lines if l.startswith('#')]
                warm_files.append({
                    'path': name,
                    'pressure': cf.raw_pressure,
                    'headers': headers[:10]  # First 10 headers
                })

        for name in result.cold:
            cf = self.session.system.files.get(name)
            if cf:
                cold_files.append({
                    'path': name,
                    'pressure': cf.raw_pressure
                })

        # Return in claude-cognitive format
        return {
            'injection': injection,
            'turn': result.turn_number,
            'activated': result.activated,
            'tiers': {
                'hot': hot_files,
                'warm': warm_files,
                'cold': cold_files
            },
            'stats': {
                'hot_count': len(hot_files),
                'warm_count': len(warm_files),
                'cold_count': len(cold_files),
                'total_files': len(self.session.system.files),
                'injection_chars': len(injection)
            },
            'backend': 'hologram-cognitive',
            'version': '0.2.0'
        }

    def _format_for_hologram(self, result: TurnResult) -> Dict[str, Any]:
        """Format in hologram's native format."""
        return {
            'injection': result.injection,
            'turn': result.turn_number,
            'activated': result.activated,
            'hot': result.hot,
            'warm': result.warm,
            'cold': result.cold,
            'backend': 'hologram-cognitive',
            'version': '0.2.0'
        }

    def get_status(self) -> Dict[str, Any]:
        """Get memory system status."""
        status = self.session.status()

        # Add pressure statistics
        hot_count = len([n for n, p in self.session.files_by_pressure(0.8)])
        warm_count = len([n for n, p in self.session.files_by_pressure(0.5)]) - hot_count
        cold_count = len(self.session.system.files) - hot_count - warm_count

        return {
            **status,
            'hot_count': hot_count,
            'warm_count': warm_count,
            'cold_count': cold_count,
            'backend': 'hologram-cognitive',
            'version': '0.2.0'
        }

    def _append_history(self, result: TurnResult, query: str):
        """
        Append turn record to history file for learning system.

        Args:
            result: TurnResult from the turn
            query: Original user query
        """
        import time
        try:
            entry = {
                'turn': result.turn_number,
                'timestamp': time.time(),
                'query': query,
                'activated': result.activated,
                'hot': result.hot,
                'warm': result.warm,
                'cold_count': len(result.cold),
                'injection_chars': len(result.injection),
            }
            with open(self.history_file, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception as e:
            # Don't fail the hook if history write fails
            import sys
            print(f"Warning: Could not write history: {e}", file=sys.stderr)


def create_claude_cognitive_hook(
    claude_dir: str = '.claude',
    stdin_json: bool = True
) -> str:
    """
    Create a claude-cognitive compatible hook using hologram backend.

    This can be called from a UserPromptSubmit hook script to replace
    context-router-v2.py with hologram-cognitive.

    Args:
        claude_dir: Path to .claude directory
        stdin_json: Read JSON from stdin (claude-cognitive format)

    Returns:
        Formatted injection string for Claude Code
    """
    # Read input
    if stdin_json:
        try:
            data = json.load(sys.stdin)
            user_prompt = data.get('prompt', '')
        except Exception:
            user_prompt = ""
    else:
        user_prompt = sys.stdin.read().strip()

    # Route through hologram
    backend = HologramBackend(claude_dir=claude_dir)
    result = backend.route_message(user_prompt, return_format='claude-cognitive')

    # Format for output
    return result['injection']


def migrate_from_context_router(
    old_state_file: str,
    claude_dir: str = '.claude'
) -> Dict[str, Any]:
    """
    Migrate state from context-router-v2.py to hologram-cognitive.

    Reads old context-router state and converts pressure/attention
    scores to hologram's pressure system.

    Args:
        old_state_file: Path to context-router-v2's state JSON
        claude_dir: Target .claude directory for hologram

    Returns:
        Migration report dict
    """
    # Read old state
    with open(old_state_file, 'r') as f:
        old_state = json.load(f)

    # Create hologram session
    session = Session(claude_dir)

    # Convert attention scores to pressure
    # context-router uses 0.0-1.0 "attention" that decays
    # hologram uses 0.0-1.0 "pressure" with similar semantics

    migrated = 0
    for file_path, file_data in old_state.get('files', {}).items():
        attention = file_data.get('attention', 0.0)

        # Map directly: attention ≈ pressure
        # Both use same scale and decay semantics
        if session.system.files.get(file_path):
            cf = session.system.files[file_path]
            cf.raw_pressure = attention
            migrated += 1

    # Save migrated state
    session.save()

    return {
        'success': True,
        'files_migrated': migrated,
        'old_format': 'context-router-v2',
        'new_format': 'hologram-cognitive-v0.2.0',
        'note': 'Attention scores mapped 1:1 to pressure values'
    }


# ============================================================================
# CLI Interface for Testing
# ============================================================================

def main():
    """CLI for testing hologram backend with claude-cognitive."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Hologram backend adapter for claude-cognitive'
    )
    parser.add_argument(
        'action',
        choices=['route', 'status', 'migrate', 'create-hook'],
        help='Action to perform'
    )
    parser.add_argument(
        '--claude-dir',
        default='.claude',
        help='Path to .claude directory'
    )
    parser.add_argument(
        '--message',
        help='Message to route (for "route" action)'
    )
    parser.add_argument(
        '--old-state',
        help='Old state file path (for "migrate" action)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output JSON'
    )

    args = parser.parse_args()

    if args.action == 'route':
        backend = HologramBackend(claude_dir=args.claude_dir)

        # Get message
        if args.message:
            message = args.message
        elif not sys.stdin.isatty():
            message = sys.stdin.read().strip()
        else:
            message = ""

        result = backend.route_message(message, return_format='claude-cognitive')

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(result['injection'])

    elif args.action == 'status':
        backend = HologramBackend(claude_dir=args.claude_dir)
        status = backend.get_status()
        print(json.dumps(status, indent=2))

    elif args.action == 'migrate':
        if not args.old_state:
            print("Error: --old-state required for migrate action", file=sys.stderr)
            sys.exit(1)

        report = migrate_from_context_router(args.old_state, args.claude_dir)
        print(json.dumps(report, indent=2))

    elif args.action == 'create-hook':
        # Output a hook script
        print(f"""#!/usr/bin/env python3
\"\"\"
UserPromptSubmit hook using hologram-cognitive backend.

Replaces context-router-v2.py with hologram-cognitive.
\"\"\"
import sys
sys.path.insert(0, '/path/to/hologram-cognitive')

from hologram.claude_cognitive import create_claude_cognitive_hook

# Route message and output injection
injection = create_claude_cognitive_hook(claude_dir='{args.claude_dir}')
print(injection)
""")


if __name__ == '__main__':
    main()
