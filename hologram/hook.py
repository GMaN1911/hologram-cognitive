"""`hologram hook <event>`: the one entry a harness calls on its hook events.

    hologram hook prompt     a prompt was submitted: the [HOLOGRAM] layer, then the graph's line
    hologram hook session    a session started, resumed or was compacted: the graph's brief
    hologram hook pretool    a tool is about to run: refuse it if a graph guard forbids it
    hologram hook stop       a turn ended: reinforce the files it touched

The event arrives as JSON on stdin in the shape Claude Code and Codex CLI both send (cwd, prompt,
source, tool_name, tool_input, transcript_path). The answer goes to stdout in the shape both read
(`hookSpecificOutput`), or with `--format text` as plain text for a wrapper that merges layers
itself. A harness whose hooks differ gets an adapter that calls the functions below.

Nothing here decides anything: the working set is `working_set.select`, the layer is
`hooks_inject.build_layer`, the graph's words are `crg.grounding`, the guard rule is `crg.judge`,
and reinforcement is `hooks_observe.observe_turn`. A failure never blocks the harness: it is one
line on stderr and no output.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

EVENTS = {'prompt': 'UserPromptSubmit', 'session': 'SessionStart', 'pretool': 'PreToolUse', 'stop': 'Stop'}
# Codex sends every event to one command and needs a per-turn record of tool calls (its own
# transcript cannot be read for files), so it gets the runtime in hologram/codex_hooks with the
# product profile: `hologram hook codex` on SessionStart, UserPromptSubmit, PreToolUse,
# PostToolUse, Stop and SessionEnd alike.
CODEX = 'codex'
# Grok discards what a prompt or session-start hook prints, so it gets its own adapter
# (hologram/harness/grok.py): `hologram hook grok` on every event.
GROK = 'grok'
# Antigravity sends no event name or prompt text in its payloads, so its adapter
# (hologram/harness/antigravity.py) takes the event as an argument:
# `hologram hook antigravity <Event>` for SessionStart, PreInvocation, PreToolUse,
# PostToolUse and Stop.
ANTIGRAVITY = 'antigravity'
# Hermes calls through its memory-provider shim (hologram/data/hermes_plugin), which relays
# plain text: `hologram hook hermes <prefetch|sync|brief>`.
HERMES = 'hermes'
FORMATS = ('hook', 'text')
# Everything a prompt gets from Hologram stays under this many UTF-8 bytes. Past about 10 KB
# Claude Code hands the model a 2 KB preview and a file path instead, and Codex spills what is
# over its own limit (about 2,500 tokens) to a file.
OUTPUT_CAP = int(os.environ.get('HOLOGRAM_HOOK_CAP', '9000'))
# Tool names as Claude Code sends them; guards are written against these.
EDIT_TOOLS = ('Edit', 'Write', 'NotebookEdit')
SHELL_TOOL = 'Bash'


HINT_DEDUPE_DAYS = 7


def first_run_hint(cwd: Path) -> str:
    """A prompt from a project Hologram knows nothing about (a VCS root with no `.hologram` and
    no `.claude`) gets one line saying how to turn it on, at most once a week per directory.
    Never in $HOME, and nothing is created for the project: `hologram init` is the user's act.
    The note of what was hinted lives in Hologram's own directory."""
    try:
        cwd = cwd.resolve()
        if cwd == Path.home().resolve() or not any((cwd / m).exists() for m in ('.git', '.hg', '.svn')):
            return ''
        cfg_dir = Path(os.environ.get('HOLOGRAM_LICENSE_DIR') or Path.home() / '.hologram')
        hints_path = cfg_dir / 'init_hints.json'
        try:
            hints = json.loads(hints_path.read_text())
        except (OSError, ValueError):
            hints = {}
        now = time.time()
        if now - float(hints.get(str(cwd), 0)) < HINT_DEDUPE_DAYS * 86400:
            return ''
        hints[str(cwd)] = now
        cfg_dir.mkdir(parents=True, exist_ok=True)
        tmp = hints_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(hints))
        tmp.replace(hints_path)
        return (f'[hologram] This project has no hologram state yet, so no routed context was '
                f'injected. Enable it once with: `hologram init {cwd}` — after that, every prompt '
                f'here gets its working set of files automatically. (This notice repeats at most '
                f'once per {HINT_DEDUPE_DAYS} days per project.)')
    except Exception:
        return ''


def agent_name() -> str:
    """Which harness this hook serves, for the board's how-to-post line: Claude Code unless a
    harness adapter says otherwise (the Codex runtime and the Grok adapter set the variable)."""
    return os.environ.get('HOLOGRAM_HOOK_CLIENT') or 'claude-code'


def prompt_context(data: dict) -> str:
    """Everything a prompt gets: the routed files and memories, then the graph's line. The graph
    goes last: it is outnumbered by construction, and recency and repetition are the only levers
    the emit side has."""
    from . import hooks_inject
    from .edition import pro
    crg, board = pro('crg'), pro('board')
    if (data.get('prompt') or '').strip() and hooks_inject.project_root(data) is None:
        return first_run_hint(Path(data.get('cwd') or os.getcwd()))
    line = layer = ''
    try:
        line = crg.grounding(data, 'prompt') if crg else ''
    except Exception as e:  # a broken graph must not break the prompt
        print(f'[hologram hook] graph: {type(e).__name__}: {e}', file=sys.stderr)
    # What other sessions posted since this one's last prompt: a few lines, delivered once.
    notes = ''
    try:
        root = hooks_inject.project_root(data)
        notes = '' if board is None else board.prompt_block(data.get('session_id') or '', root.name if root else '', agent=agent_name())
    except Exception as e:
        print(f'[hologram hook] board: {type(e).__name__}: {e}', file=sys.stderr)
    # The graph's line and the notes are small and bounded, so the routed layer takes what is left.
    room = OUTPUT_CAP - sum(len(part.encode('utf-8')) + 2 for part in (line, notes) if part)
    try:
        layer = hooks_inject.build_layer(data, cap=min(hooks_inject.HOLOGRAM_LAYER_CAP, room))
    except hooks_inject.RouteFailed as e:
        print(f'[hologram hook] {e}', file=sys.stderr)
    return '\n\n'.join(part for part in (layer, notes, line) if part)


def session_context(data: dict) -> str:
    """The graph's brief, then what other sessions on this machine left on the blackboard."""
    from . import hooks_inject
    from .edition import pro
    crg, board = pro('crg'), pro('board')
    parts = [crg.grounding(data, 'session') if crg else '']
    try:
        root = hooks_inject.project_root(data)
        parts.append('' if board is None else board.brief(root.name if root else '', data.get('session_id') or '', agent=agent_name()))
    except Exception as e:
        print(f'[hologram hook] board: {type(e).__name__}: {e}', file=sys.stderr)
    return '\n\n'.join(part for part in parts if part)


def presence(data: dict, status: str) -> None:
    """This session's presence for the others: working with its prompt, or idle. Never fatal."""
    session = data.get('session_id') or ''
    if not session:
        return
    try:
        from . import hooks_inject
        from .edition import pro
        board = pro('board')
        if board is None:
            return
        root = hooks_inject.project_root(data)
        board.heartbeat(session, root.name if root else '', str(root or ''), status,
                        ' '.join((data.get('prompt') or '').split())[:120] if status == 'working' else '')
    except Exception as e:
        print(f'[hologram hook] presence: {type(e).__name__}: {e}', file=sys.stderr)


def guard_root(data: dict) -> Optional[Path]:
    """The project whose guards apply. The harness's own project directory comes first: the
    working directory follows a `cd`, and a guard must not be left behind by one."""
    from .edition import pro
    crg = pro('crg')
    if crg is None:
        return None
    for start in (os.environ.get('CLAUDE_PROJECT_DIR'), data.get('cwd'), os.getcwd()):
        root = crg.find_root(Path(start)) if start else None
        if root is not None:
            return root
    return None


def pretool_refusal(data: dict, waived: Optional[dict] = None, how_to_waive: str = '') -> Optional[str]:
    """Why this tool call is refused, or None when it may go ahead."""
    from .edition import pro
    crg = pro('crg')
    if crg is None:
        return None
    tool = str(data.get('tool_name') or '')
    given = data.get('tool_input') if isinstance(data.get('tool_input'), dict) else {}
    path = given.get('file_path') or given.get('notebook_path')
    command = given.get('command')
    root = guard_root(data)
    if root is None:
        return None
    return crg.judge(
        root, tool,
        path=path if isinstance(path, str) and tool in EDIT_TOOLS else None,
        command=command if tool == SHELL_TOOL and isinstance(command, str) else None,
        waived=waived, how_to_waive=how_to_waive, cwd=data.get('cwd'))


def end_of_turn(data: dict) -> None:
    from . import hooks_observe
    hooks_observe.observe_turn(data)


def run(event: str, data: dict, fmt: str = 'hook', subevent: Optional[str] = None) -> int:
    """Handle one event and write the answer. Returns the process exit status."""
    if event in (CODEX, GROK, ANTIGRAVITY):
        from .edition import pro, pro_only
        module = {CODEX: 'codex_hooks.runtime', GROK: 'harness.grok', ANTIGRAVITY: 'harness.antigravity'}[event]
        if pro(module) is None:
            # A hook must never block its harness: say so once on stderr, answer nothing.
            print(f'[hologram] {pro_only(event.capitalize() + " support")}', file=sys.stderr)
            if event == ANTIGRAVITY and subevent == 'PreToolUse':
                print(json.dumps({'decision': 'allow'}))   # in agy, printing nothing denies
            return 0
    if event == CODEX:
        from .codex_hooks.runtime import main as codex_main
        return codex_main(['--profile', 'product'], data=data)
    if event == GROK:
        from .harness.grok import main as grok_main
        try:
            return grok_main(data)
        except Exception as e:
            print(f'[hologram hook grok] {type(e).__name__}: {e}', file=sys.stderr)
            return 0
    if event == ANTIGRAVITY:
        from .harness.antigravity import main as agy_main
        return agy_main(data, subevent)
    if event == HERMES:
        from .harness.hermes import main as hermes_main
        return hermes_main(data, subevent)
    try:
        if event == 'stop':
            end_of_turn(data)
            presence(data, 'idle')
            return 0
        if event == 'prompt':
            presence(data, 'working')
        if event == 'pretool':
            refusal = pretool_refusal(data)
            if refusal is None:
                return 0
            if fmt == 'text':
                # The convention for a hook without JSON: status 2, and stderr goes to the model.
                print(refusal, file=sys.stderr)
                return 2
            print(json.dumps({'hookSpecificOutput': {
                'hookEventName': EVENTS[event], 'permissionDecision': 'deny',
                'permissionDecisionReason': refusal}}))
            return 0
        context = prompt_context(data) if event == 'prompt' else session_context(data)
    except Exception as e:
        print(f'[hologram hook {event}] {type(e).__name__}: {e}', file=sys.stderr)
        return 0
    if not context:
        return 0
    if fmt == 'text':
        print(context)
    else:
        print(json.dumps({'hookSpecificOutput': {
            'hookEventName': EVENTS[event], 'additionalContext': context}}))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='hologram hook', description=__doc__.split('\n\n')[0],
                                     epilog='The hook event is read as JSON from stdin.')
    parser.add_argument('event', choices=sorted(EVENTS) + [ANTIGRAVITY, CODEX, GROK, HERMES])
    parser.add_argument('subevent', nargs='?', default=None,
                        help="the harness's own event name, for adapters whose payloads do not carry one (antigravity)")
    parser.add_argument('--format', choices=FORMATS, default='hook',
                        help='hook: the JSON Claude Code and Codex CLI read (default); text: plain text')
    args = parser.parse_args(argv)
    if args.event == HERMES and args.subevent == 'serve':
        from .harness.hermes import serve
        return serve()
    try:
        data = json.loads(sys.stdin.read() or '{}')
    except ValueError:
        data = {}
    return run(args.event, data if isinstance(data, dict) else {}, args.format, args.subevent)


if __name__ == '__main__':
    sys.exit(main())
