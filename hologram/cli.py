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
    
    # Use relative tiers (top 5 = HOT, next 10 = WARM, etc.)
    files_sorted = session.files_by_pressure(0.0)
    hot_count = min(5, len(files_sorted))
    warm_count = min(10, max(0, len(files_sorted) - hot_count))

    if args.json:
        files_data = [
            {'name': name, 'pressure': pressure, 'tier': 'HOT' if i < hot_count else ('WARM' if i < hot_count + warm_count else 'COLD')}
            for i, (name, pressure) in enumerate(files_sorted)
        ]
        print(json.dumps(files_data, indent=2))
    else:
        print("Files by pressure (relative tiers):")
        for i, (name, pressure) in enumerate(files_sorted):
            if i < hot_count:
                tier = '🔥'
            elif i < hot_count + warm_count:
                tier = '⭐'
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
    """`hologram init <project>`: make the project one the hooks route, which is its state
    directory `<project>/.hologram/` (the hooks fill it from the first prompt on). Pointing it
    at a `.claude` or `.hologram` directory keeps the older meaning: that directory is the
    memory folder and gets a MEMORY.md and a state file."""
    from .session import Session

    claude_dir = Path(args.claude_dir).expanduser()
    if claude_dir.name not in ('.claude', '.hologram'):
        root = claude_dir.resolve()
        state = root / '.hologram'
        if state.exists() and not args.force:
            print(f"{root} is already initialized ({state} exists).")
            return
        state.mkdir(parents=True, exist_ok=True)
        print(f"Initialized: {state}")
        print(f"Every prompt under {root} now gets its working set of files; the state stays in that directory.")
        print("For the project's causal graph and guards: hologram crg init --root " + str(root))
        return

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



def cmd_crg(args: argparse.Namespace) -> None:
    """The causal research graph's tooling (hologram/crg.py) behind the installed command, so a
    mod or a hook can run `hologram crg check` without knowing where the package lives."""
    from .crg import main as crg_main
    sys.exit(crg_main(args.args))


def cmd_board(args: argparse.Namespace) -> None:
    """The blackboard between sessions on this machine (hologram/board.py)."""
    from .board import main as board_main
    sys.exit(board_main(args.args))


def cmd_hook(args: argparse.Namespace) -> None:
    """A harness hook event: JSON on stdin, the context or refusal on stdout (hologram/hook.py)."""
    from .hook import run
    if args.event == 'hermes' and getattr(args, 'subevent', None) == 'serve':
        from .harness.hermes import serve
        sys.exit(serve())
    try:
        data = json.loads(sys.stdin.read() or '{}')
    except ValueError:
        data = {}
    sys.exit(run(args.event, data if isinstance(data, dict) else {}, args.format,
                 getattr(args, 'subevent', None)))


def cmd_license(args) -> None:
    """License activation and status (pro)."""
    from hologram import licensing
    if args.action == 'terms':
        # The EULA ships in the wheel; the canonical copy lives at hologram-pro.dev/terms/.
        print((Path(__file__).parent / 'data' / 'EULA.md').read_text())
        sys.exit(0)
    if args.action == 'activate':
        if not args.key:
            print("usage: hologram license activate <key>")
            sys.exit(2)
        st = licensing.activate(args.key)
        print(licensing.status_line(st))
        if st.licensed and licensing.index_url():
            print(f"your package index (pipx install --index-url ... 'hologram-cognitive-pro[mcp,hooks,memory]'):\n    {licensing.index_url()}")
        sys.exit(0 if st.licensed else 1)
    elif args.action == 'deactivate':
        licensing.remove_key()
        print("license removed — core mode")
    else:  # status
        st = licensing.check(force=args.force)
        print(licensing.status_line(st))
        if args.json:
            print(json.dumps(st.__dict__, indent=2))



def cmd_upgrade(args) -> None:
    """Download and install the latest licensed wheel."""
    import shutil
    import subprocess
    from hologram import licensing

    st = licensing.check(force=True)
    if not st.licensed:
        print(f"upgrade requires an active license (current: {st.status}).")
        sys.exit(1)
    if sys.version_info < (3, 11):
        print(f"Hologram 0.5 and later need Python 3.11 or newer; this install runs on "
              f"{sys.version_info.major}.{sys.version_info.minor}, so the new wheel cannot be installed here.")
        print("Install a newer Python, then reinstall into it, for example:")
        print("    pipx install --python python3.12 --force 'hologram-cognitive-pro[mcp,hooks,memory]'")
        print("(or `hologram upgrade --print-only` to download the wheel and finish by hand).")
        if not args.print_only:
            sys.exit(1)

    newer = licensing.update_available(st)
    if not newer and not args.force:
        print(f"already on the latest version (v{licensing._package_version()}).")
        sys.exit(0)

    # Installed through the licensed index (pipx install --index-url .../v1/pypi/<key>/simple/)?
    # Then pipx already knows where the wheel comes from: upgrade in place and keep that.
    pipx = shutil.which("pipx")
    if pipx and licensing.pipx_uses_index():
        if args.print_only:
            print("installed from the licensed index; to finish, run:\n    pipx upgrade hologram-cognitive-pro")
            sys.exit(0)
        print("upgrading with pipx from the licensed index…")
        rc = subprocess.run([pipx, "upgrade", "hologram-cognitive-pro"]).returncode
        if rc == 0:
            print(f"✅ upgraded to v{st.latest_version}. Restart any running MCP sessions.")
        else:
            print("pipx upgrade failed; finish by hand:\n    pipx upgrade hologram-cognitive-pro")
        sys.exit(rc)

    print(f"downloading v{st.latest_version or 'latest'}…")
    wheel = licensing.fetch_wheel()
    if not wheel:
        print("could not download the wheel (check your license / connection).")
        sys.exit(1)
    print(f"downloaded: {wheel}")

    if pipx and not args.print_only:
        print("installing with pipx…")
        rc = subprocess.run(
            [pipx, "install", "--force", f"{wheel}[mcp,hooks,memory]"],
        ).returncode
        if rc == 0:
            print(f"✅ upgraded to v{st.latest_version}. Restart any running MCP sessions.")
        else:
            print(f"pipx install failed. Finish manually:\n"
                  f"    pipx install --force '{wheel}[mcp,hooks,memory]'")
        sys.exit(rc)
    else:
        print("To finish, run:")
        print(f"    pipx install --force '{wheel}[mcp,hooks,memory]'")
        print(f"  or, in your venv:  pip install --force-reinstall '{wheel}[mcp,hooks,memory]'")


def cmd_install(args) -> None:
    """Register editor integrations (explicit, reversible)."""
    from hologram import installer
    from .edition import EDITION, pro_only
    if EDITION != 'pro':
        # The core: Claude Code's hooks (no MCP server, no mod) and the Hermes provider.
        if args.target == 'claude-code':
            sys.exit(installer._install_claude_hooks(args.yes, input, print))
        if args.target == 'hermes':
            sys.exit(installer.install_hermes(assume_yes=args.yes))
        print(pro_only(f'{args.target} support'))
        sys.exit(0)
    if args.target == 'claude-code':
        sys.exit(installer.install_claude_code(
            scope=args.scope, with_hooks=not args.no_hooks, assume_yes=args.yes))
    if args.target in ('gemini', 'codex'):
        sys.exit(installer.install_simple_mcp(args.target, assume_yes=args.yes, with_hooks=not args.no_hooks))
    if args.target == 'grok':
        sys.exit(installer.install_grok(assume_yes=args.yes))
    if args.target == 'antigravity':
        sys.exit(installer.install_antigravity(assume_yes=args.yes))
    if args.target == 'hermes':
        sys.exit(installer.install_hermes(assume_yes=args.yes))
    if args.target == 'cursor':
        sys.exit(installer.print_cursor_instructions())
    print(f"unknown install target: {args.target}")
    sys.exit(2)


def cmd_uninstall(args) -> None:
    """Reverse everything `hologram install` did."""
    from hologram import installer
    sys.exit(installer.uninstall(purge=args.purge, assume_yes=args.yes))


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='hologram',
        description='Pressure-based context routing for LLMs',
        epilog='For more info: https://github.com/mirrorethic/hologram-cognitive'
    )
    from .edition import version as _edition_version
    _v = _edition_version()
    parser.add_argument(
        '--version', '-V',
        action='version',
        version=f'%(prog)s {_v}'
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
    p_init = subparsers.add_parser('init', help='Make a project one the hooks route (creates <project>/.hologram)')
    p_init.add_argument('claude_dir', metavar='project', help='Project root (or a .claude/.hologram directory, the older meaning)')
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

    # crg: the graph's own command line, unchanged (`hologram crg check --root .`)
    p_crg = subparsers.add_parser(
        'crg', help='The causal research graph: check, pin, verify, current, brief, line, packet, find, register, mesh')
    p_crg.add_argument('args', nargs=argparse.REMAINDER)
    p_crg.set_defaults(func=cmd_crg)

    # board: notes between sessions on this machine, and who is live
    p_board = subparsers.add_parser('board', help='The blackboard: post, read, topics, peers')
    p_board.add_argument('args', nargs=argparse.REMAINDER)
    p_board.set_defaults(func=cmd_board)

    # hook: the one entry a harness calls (prompt, session start, before a tool, end of turn)
    from .hook import ANTIGRAVITY, CODEX, EVENTS, FORMATS, GROK, HERMES
    p_hook = subparsers.add_parser(
        'hook', help='Handle a harness hook event (JSON on stdin)')
    p_hook.add_argument('event', choices=sorted(EVENTS) + [ANTIGRAVITY, CODEX, GROK, HERMES])
    p_hook.add_argument('subevent', nargs='?', default=None,
                        help="the harness's own event name, for adapters whose payloads do not carry one (antigravity)")
    p_hook.add_argument('--format', choices=FORMATS, default='hook',
                        help='hook: the JSON Claude Code and Codex CLI read (default); text: plain text')
    p_hook.set_defaults(func=cmd_hook)

    # license
    p_license = subparsers.add_parser('license', help='Manage pro license')
    p_license.add_argument('action', choices=['status', 'activate', 'deactivate', 'terms'], help='License action')
    p_license.add_argument('key', nargs='?', help='License key (for activate)')
    p_license.add_argument('--force', '-f', action='store_true', help='Force server recheck')
    p_license.add_argument('--json', '-j', action='store_true', help='Output full state as JSON')
    p_license.set_defaults(func=cmd_license)

    # install / uninstall
    p_install = subparsers.add_parser('install', help='Register editor integration (prints changes first)')
    p_install.add_argument('target', choices=['antigravity', 'claude-code', 'codex', 'grok', 'gemini', 'cursor', 'hermes'], help='Integration target')
    p_install.add_argument('--scope', default='user', choices=['user', 'local', 'project'], help='Claude Code scope')
    p_install.add_argument('--no-hooks', action='store_true', help='Claude Code, Codex: register the MCP server only, skip the hooks')
    p_install.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    p_install.set_defaults(func=cmd_install)

    p_upgrade = subparsers.add_parser('upgrade', help='Download and install the latest licensed version')
    p_upgrade.add_argument('--force', action='store_true', help='Reinstall even if already latest')
    p_upgrade.add_argument('--print-only', action='store_true', help="Download only; print the install command, don't run it")
    p_upgrade.set_defaults(func=cmd_upgrade)

    p_uninstall = subparsers.add_parser('uninstall', help='Reverse everything hologram install did')
    p_uninstall.add_argument('--purge', action='store_true', help='Also delete ~/.hologram (incl. license key)')
    p_uninstall.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    p_uninstall.set_defaults(func=cmd_uninstall)

    args = parser.parse_args()
    from .edition import EDITION, pro_only
    pro_commands = {cmd_crg: 'The project graph and its guards', cmd_board: 'The blackboard',
                    cmd_license: 'Licensing', cmd_upgrade: 'In-app upgrades'}
    if EDITION != 'pro' and args.func in pro_commands:
        print(pro_only(pro_commands[args.func]))
        sys.exit(0)
    args.func(args)


if __name__ == '__main__':
    main()
