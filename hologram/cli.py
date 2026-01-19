"""
Command-line interface for hologram-cognitive.

Usage:
    hologram route .claude "What about T3?"
    hologram status .claude
    hologram note .claude "Title" "Body content"
    hologram init .claude
    hologram export .claude output.tar.gz
    hologram import backup.tar.gz .claude
"""

import argparse
import signal
import sys
import json
import tarfile
from pathlib import Path
from typing import List, Optional

# Handle SIGPIPE gracefully (e.g., when piping to head)
signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def cmd_route(args: argparse.Namespace) -> None:
    """Route a message and print injection context."""
    from .session import Session
    
    session = Session(args.claude_dir)
    result = session.turn(args.message)
    
    if args.json:
        output = {
            'turn': result.turn_number,
            'activated': result.activated,
            'hot': result.hot,
            'warm': result.warm,
            'cold': result.cold,
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"Turn {result.turn_number} | Activated: {len(result.activated)} files")
        print(f"HOT: {', '.join(result.hot[:5]) or '(none)'}")
        print(f"WARM: {', '.join(result.warm[:5]) or '(none)'}")
        
        if not args.quiet:
            print("\n" + "=" * 50)
            injection = result.injection
            if len(injection) > 3000:
                injection = injection[:3000] + "\n... (truncated)"
            print(injection)
    
    session.save()


def cmd_status(args: argparse.Namespace) -> None:
    """Show memory status."""
    from .session import Session
    
    session = Session(args.claude_dir)
    # Do an empty turn to load state without affecting pressure much
    session.turn("")
    
    print(f"Directory: {session.claude_dir}")
    print(f"Files: {len(session.system.files)}")
    print(f"Turn: {session.system.current_turn}")
    print()
    
    if args.json:
        files_data = [
            {'name': name, 'pressure': cf.raw_pressure}
            for name, cf in session.system.files.items()
        ]
        print(json.dumps(sorted(files_data, key=lambda x: -x['pressure']), indent=2))
    else:
        print("Files by pressure:")
        for name, pressure in session.files_by_pressure(0.0):
            if pressure >= 0.8:
                tier = '🔥'
            elif pressure >= 0.5:
                tier = '⭐'
            elif pressure >= 0.2:
                tier = '📋'
            else:
                tier = '❄️'
            print(f"  {tier} {pressure:.2f} {name}")


def cmd_note(args: argparse.Namespace) -> None:
    """Write a memory note."""
    from .session import Session
    
    session = Session(args.claude_dir)
    
    # Parse links
    links = args.links or []
    
    path = session.note(
        title=args.title,
        body=args.body or '',
        links=links
    )
    session.save()
    
    print(f"Created: {path}")
    
    if not args.quiet:
        print(f"Content:\n{path.read_text()[:500]}")


def cmd_pin(args: argparse.Namespace) -> None:
    """Append to rolling anchor file."""
    from .session import Session
    
    session = Session(args.claude_dir)
    path = session.pin(args.content, anchor_file=args.file)
    session.save()
    
    print(f"Pinned to: {path}")


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize a new .claude directory."""
    from .session import Session
    
    claude_dir = Path(args.claude_dir)
    
    if claude_dir.exists() and any(claude_dir.iterdir()):
        if not args.force:
            print(f"Error: {claude_dir} already exists and is not empty.")
            print("Use --force to initialize anyway.")
            sys.exit(1)
    
    claude_dir.mkdir(parents=True, exist_ok=True)
    
    # Create MEMORY.md
    memory_md = claude_dir / 'MEMORY.md'
    if not memory_md.exists() or args.force:
        memory_md.write_text(f"""# Memory System Active

This folder contains portable AI working memory powered by `hologram-cognitive`.

## Quick Start
```python
import hologram

session = hologram.Session('{claude_dir}')
result = session.turn("your message")
print(result.injection)
session.save()
```

## CLI
```bash
hologram route {claude_dir} "your message"
hologram status {claude_dir}
```

## Links
Add `[[wiki-links]]` in your .md files to build the knowledge graph.
""")
        print(f"Created: {memory_md}")
    
    # Initialize state
    session = Session(str(claude_dir))
    session.save()
    
    print(f"Initialized: {claude_dir}")
    print(f"State file: {claude_dir}/hologram_state.json")


def cmd_export(args: argparse.Namespace) -> None:
    """Export .claude folder to tar.gz."""
    claude_dir = Path(args.claude_dir)
    output = Path(args.output)
    
    if not claude_dir.exists():
        print(f"Error: {claude_dir} does not exist.")
        sys.exit(1)
    
    # Determine archive name (folder name in archive)
    arcname = args.arcname or '.claude'
    
    with tarfile.open(output, 'w:gz') as tar:
        tar.add(claude_dir, arcname=arcname)
    
    size = output.stat().st_size
    file_count = sum(1 for _ in claude_dir.rglob('*') if _.is_file())
    
    print(f"Exported: {output}")
    print(f"Size: {size:,} bytes")
    print(f"Files: {file_count}")


def cmd_import(args: argparse.Namespace) -> None:
    """Import .claude folder from tar.gz."""
    archive = Path(args.archive)
    target = Path(args.target)
    
    if not archive.exists():
        print(f"Error: {archive} does not exist.")
        sys.exit(1)
    
    if target.exists() and any(target.iterdir()):
        if not args.force:
            print(f"Error: {target} already exists and is not empty.")
            print("Use --force to overwrite.")
            sys.exit(1)
    
    target.mkdir(parents=True, exist_ok=True)
    
    with tarfile.open(archive, 'r:gz') as tar:
        # Extract, stripping the top-level directory
        for member in tar.getmembers():
            # Remove leading .claude/ or similar
            parts = Path(member.name).parts
            if len(parts) > 1:
                member.name = str(Path(*parts[1:]))
                tar.extract(member, target)
            elif member.isdir():
                continue  # Skip top-level dir
            else:
                tar.extract(member, target)
    
    print(f"Imported to: {target}")
    
    # Show status
    from .session import Session
    session = Session(str(target))
    print(f"Files: {len(session.system.files)}")
    print(f"Turn: {session.system.current_turn}")


def cmd_files(args: argparse.Namespace) -> None:
    """List files in memory."""
    from .session import Session

    session = Session(args.claude_dir)

    files = session.files_by_pressure(args.min_pressure)

    if args.json:
        print(json.dumps([{'name': n, 'pressure': p} for n, p in files], indent=2))
    else:
        for name, pressure in files:
            print(f"{pressure:.2f} {name}")


# =============================================================================
# v0.3.0 Commands
# =============================================================================

def cmd_state(args: argparse.Namespace) -> None:
    """Show turn state (v0.3.0)."""
    from .session import Session

    session = Session(args.claude_dir)
    state = session.turn_state

    if state is None:
        print("No turn state found.")
        return

    if args.json:
        data = state.to_dict()
        print(json.dumps(data, indent=2))
    else:
        print(f"Turn: {state.turn}")
        print(f"Timestamp: {state.timestamp}")
        print()
        print(f"Attention Cluster ({len(state.attention_cluster)} files):")
        for path in sorted(state.attention_cluster):
            print(f"  - {path}")
        print()
        print(f"Cluster Formation: Turn {state.cluster_formation_turn}")
        print(f"Cluster Sustained: {state.cluster_sustained_turns} turns")
        print()
        print(f"Tension: {state.unresolved_tension:.2f}")
        if state.tension_sources:
            print(f"Tension Sources: {', '.join(state.tension_sources[:5])}")
        print()
        print(f"Last Resolution: Turn {state.last_resolution_turn}")
        print(f"Pending Crystallization: {state.pending_crystallization}")
        print()

        if state.pressure_inheritance:
            print(f"Pressure Inheritance ({len(state.pressure_inheritance)} files):")
            for path, pressure in sorted(state.pressure_inheritance.items(), key=lambda x: -x[1])[:5]:
                print(f"  {pressure:.2f} {path}")

        # Also show basin depths if available
        print()
        print("Basin Depths (HOT files):")
        for path in sorted(state.attention_cluster):
            cf = session.get_file(path)
            if cf and cf.raw_pressure >= 0.8:
                print(f"  {cf.basin_depth:.2f} {path} (consecutive_hot: {cf.consecutive_hot_turns})")


def cmd_crystallize(args: argparse.Namespace) -> None:
    """Manually trigger crystallization (v0.3.0)."""
    from .session import Session

    session = Session(args.claude_dir)

    # Check state exists
    if session.turn_state is None:
        print("No turn state found. Run some turns first.")
        sys.exit(1)

    if not session.turn_state.attention_cluster:
        print("No attention cluster to crystallize.")
        sys.exit(1)

    # Crystallize
    filepath = session.crystallize(summary=args.summary)

    if filepath:
        print(f"Crystallized to: {filepath}")
        if not args.quiet:
            print()
            content = filepath.read_text()
            if len(content) > 1000:
                content = content[:1000] + "\n... (truncated)"
            print(content)
    else:
        print("Crystallization failed (conditions not met).")


def cmd_sessions(args: argparse.Namespace) -> None:
    """List session notes (v0.3.0)."""
    from .session import Session

    session = Session(args.claude_dir)
    sessions_list = session.sessions(limit=args.limit)

    if not sessions_list:
        print("No session notes found.")
        return

    if args.json:
        data = [
            {
                'path': str(s.path),
                'title': s.title,
                'timestamp': s.timestamp.isoformat(),
                'cluster_size': s.cluster_size,
                'sustained_turns': s.sustained_turns,
            }
            for s in sessions_list
        ]
        print(json.dumps(data, indent=2))
    else:
        print(f"Session Notes ({len(sessions_list)} found):")
        print()
        for s in sessions_list:
            ts = s.timestamp.strftime("%Y-%m-%d %H:%M")
            print(f"  [{ts}] {s.title}")
            print(f"           Cluster: {s.cluster_size} files, Sustained: {s.sustained_turns} turns")
            print(f"           Path: {s.path.name}")
            print()


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='hologram',
        description='Pressure-based context routing for LLMs',
        epilog='For more info: https://github.com/mirrorethic/hologram-cognitive'
    )
    parser.add_argument(
        '--version', '-V',
        action='version',
        version='%(prog)s 0.3.1'
    )
    
    subparsers = parser.add_subparsers(dest='command', required=True)
    
    # route
    p_route = subparsers.add_parser('route', help='Route a message through memory')
    p_route.add_argument('claude_dir', help='Path to .claude directory')
    p_route.add_argument('message', help='Message to route')
    p_route.add_argument('--json', '-j', action='store_true', help='Output as JSON')
    p_route.add_argument('--quiet', '-q', action='store_true', help='Minimal output (no injection)')
    p_route.set_defaults(func=cmd_route)
    
    # status
    p_status = subparsers.add_parser('status', help='Show memory status')
    p_status.add_argument('claude_dir', help='Path to .claude directory')
    p_status.add_argument('--json', '-j', action='store_true', help='Output as JSON')
    p_status.set_defaults(func=cmd_status)
    
    # note
    p_note = subparsers.add_parser('note', help='Write a memory note')
    p_note.add_argument('claude_dir', help='Path to .claude directory')
    p_note.add_argument('title', help='Note title')
    p_note.add_argument('body', nargs='?', default='', help='Note body')
    p_note.add_argument('--link', '-l', dest='links', action='append', help='Add wiki-link (can repeat)')
    p_note.add_argument('--quiet', '-q', action='store_true', help='Minimal output')
    p_note.set_defaults(func=cmd_note)
    
    # pin
    p_pin = subparsers.add_parser('pin', help='Append to rolling anchor file')
    p_pin.add_argument('claude_dir', help='Path to .claude directory')
    p_pin.add_argument('content', help='Content to pin')
    p_pin.add_argument('--file', '-f', default='anchors.md', help='Anchor filename (default: anchors.md)')
    p_pin.set_defaults(func=cmd_pin)
    
    # init
    p_init = subparsers.add_parser('init', help='Initialize .claude directory')
    p_init.add_argument('claude_dir', help='Path to create')
    p_init.add_argument('--force', '-f', action='store_true', help='Overwrite existing files')
    p_init.set_defaults(func=cmd_init)
    
    # export
    p_export = subparsers.add_parser('export', help='Export to tar.gz archive')
    p_export.add_argument('claude_dir', help='Path to .claude directory')
    p_export.add_argument('output', help='Output archive path')
    p_export.add_argument('--arcname', '-n', help='Name in archive (default: .claude)')
    p_export.set_defaults(func=cmd_export)
    
    # import
    p_import = subparsers.add_parser('import', help='Import from tar.gz archive')
    p_import.add_argument('archive', help='Archive file to import')
    p_import.add_argument('target', help='Target directory')
    p_import.add_argument('--force', '-f', action='store_true', help='Overwrite existing')
    p_import.set_defaults(func=cmd_import)
    
    # files
    p_files = subparsers.add_parser('files', help='List files by pressure')
    p_files.add_argument('claude_dir', help='Path to .claude directory')
    p_files.add_argument('--min', '-m', dest='min_pressure', type=float, default=0.0, help='Minimum pressure')
    p_files.add_argument('--json', '-j', action='store_true', help='Output as JSON')
    p_files.set_defaults(func=cmd_files)

    # =========================================================================
    # v0.3.0 Commands
    # =========================================================================

    # state
    p_state = subparsers.add_parser('state', help='Show turn state (v0.3.0)')
    p_state.add_argument('claude_dir', help='Path to .claude directory')
    p_state.add_argument('--json', '-j', action='store_true', help='Output as JSON')
    p_state.set_defaults(func=cmd_state)

    # crystallize
    p_crystallize = subparsers.add_parser('crystallize', help='Manually crystallize attention cluster (v0.3.0)')
    p_crystallize.add_argument('claude_dir', help='Path to .claude directory')
    p_crystallize.add_argument('--summary', '-s', help='Optional summary to include')
    p_crystallize.add_argument('--quiet', '-q', action='store_true', help='Minimal output')
    p_crystallize.set_defaults(func=cmd_crystallize)

    # sessions
    p_sessions = subparsers.add_parser('sessions', help='List session notes (v0.3.0)')
    p_sessions.add_argument('claude_dir', help='Path to .claude directory')
    p_sessions.add_argument('--limit', '-n', type=int, default=20, help='Maximum sessions to show')
    p_sessions.add_argument('--json', '-j', action='store_true', help='Output as JSON')
    p_sessions.set_defaults(func=cmd_sessions)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
