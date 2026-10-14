"""Hermes Agent (Nous Research): Hologram as its memory provider.

Hermes has no hook files; it has a pluggable `MemoryProvider` (one active at a time) whose
methods are Hologram's loop under other names: `prefetch(query)` runs before each API call and
its return reaches the model, `sync_turn(user, assistant, messages)` runs after each turn on a
background worker, `system_prompt_block()` joins the system prompt, and `initialize(cwd=...)`
hands the session its project — per session, which the global-scoped MCP never could.

The provider itself is a thin shim that lives in Hermes's world (it imports
`agent.memory_provider` from the Hermes install): `hologram/data/hermes_plugin/`, installed to
`~/.hermes/plugins/hologram/`. It subprocesses to this adapter so every decision stays in the
package — `hologram hook hermes <prefetch|sync|brief>`, JSON on stdin:

  prefetch   {prompt, cwd, session_id}              → the [HOLOGRAM] layer and the graph's line,
                                                      plain text on stdout
  brief      {cwd, session_id}                      → the graph's brief (the shim serves it as
                                                      the system prompt block), plain text
  sync       {user, assistant, messages, cwd,
              session_id}                           → reinforce the turn; nothing on stdout

The turn's receipts are read from Hermes's own messages (OpenAI-shaped tool calls): any call
whose arguments carry a path is a file touch — an edit when the tool's name says write, edit,
patch or replace, a read otherwise — and `command` arguments are the turn's commands. Tool names
are not pinned: Hermes's tool set moves release to release, the shapes don't.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

COMMAND = 'hologram hook hermes'
EVENTS = ('prefetch', 'sync', 'brief')
PATH_KEYS = ('path', 'file_path', 'filename', 'abs_path', 'absolute_path', 'target_file')
EDIT_WORDS = ('write', 'edit', 'patch', 'replace', 'create', 'append', 'blob')


def _calls(messages) -> list:
    """Every tool call in the turn's messages, as (name, args) with args a dict."""
    out = []
    if not isinstance(messages, list):
        return out
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        for call in (msg.get('tool_calls') or []):
            if not isinstance(call, dict):
                continue
            fn = call.get('function') if isinstance(call.get('function'), dict) else call
            name = str(fn.get('name') or '')
            args = fn.get('arguments')
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            out.append((name, args if isinstance(args, dict) else {}))
    return out


def messages_turn(messages) -> Tuple[Set[str], Set[str], List[str]]:
    """The turn's receipts in observe's terms: files read, files edited, commands run."""
    used, edited, commands = set(), set(), []
    for name, args in _calls(messages):
        if isinstance(args.get('command'), str):
            commands.append(args['command'])
        path = next((args[k] for k in PATH_KEYS if isinstance(args.get(k), str) and args[k]), None)
        if path:
            (edited if any(w in name.lower() for w in EDIT_WORDS) else used).add(path)
    return used, edited, commands


def _normalized(data: dict) -> dict:
    out = dict(data)
    out['session_id'] = data.get('session_id') or ''
    out['cwd'] = data.get('cwd') or os.getcwd()
    out['source'] = 'startup'
    # Hermes has no transcript file: the receipts ride in `messages`, and observe_turn's
    # extract gets them from there. The path only has to be non-empty.
    out['transcript_path'] = 'hermes:messages'
    return out


def handle(event: str, data: dict) -> Optional[str]:
    """One call in, the text Hermes relays out (None for nothing to say)."""
    from .. import hook, hooks_inject, hooks_observe
    from ..edition import pro
    board = pro('board')
    os.environ.setdefault('HOLOGRAM_HOOK_CLIENT', 'hermes')
    data = _normalized(data)
    root = hooks_inject.project_root(data)
    if root is None:
        return None

    if event == 'brief':
        if board is not None:
            board.heartbeat(data['session_id'], root.name, str(root), 'idle', board_seen=board.unseen())
        return hook.session_context(data) or None

    if event == 'prefetch':
        hook.presence(data, 'working')
        return hook.prompt_context(data) or None

    if event == 'sync':
        receipts = messages_turn(data.get('messages'))
        hooks_observe.observe_turn(data, extract=lambda _: receipts)
        hook.presence(data, 'idle')
        return None
    return None


def capabilities() -> dict:
    """What this installation answers, so the shim degrades by asking instead of failing."""
    from ..edition import EDITION, PRO_URL
    features = ['prefetch', 'sync', 'brief'] if EDITION == 'pro' else ['prefetch', 'sync']
    return {'edition': EDITION, 'features': features, 'pro_url': PRO_URL, 'protocol': 1}


def serve(stdin=None, stdout=None) -> int:
    """The warm worker: one JSON request per line in, one JSON answer per line out, until EOF.
    Each request is `{"event": ..., "data": {...}}`; each answer `{"ok": bool, "text": str}`.
    Project state is read from disk on every request as in a one-shot call; what stays warm is
    what is expensive to load (the memory index, the embedder), so a session pays it once.
    Anything the package prints goes to stderr so it can never corrupt the protocol."""
    import contextlib
    stdin = stdin or sys.stdin
    out = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            event, data = req.get('event'), req.get('data') or {}
            if event == 'capabilities':
                answer = {'ok': True, 'text': json.dumps(capabilities())}
            elif event in EVENTS and isinstance(data, dict):
                with contextlib.redirect_stdout(sys.stderr):
                    text = handle(event, data)
                answer = {'ok': True, 'text': text or ''}
            else:
                answer = {'ok': False, 'text': f'unknown event: {event!r}'}
        except Exception as e:  # noqa: BLE001 — one bad request never ends the worker
            answer = {'ok': False, 'text': f'{type(e).__name__}: {e}'}
        out.write(json.dumps(answer) + '\n')
        out.flush()
    return 0


def main(data: dict, event: Optional[str]) -> int:
    if event == 'capabilities':
        print(json.dumps(capabilities()))
        return 0
    if event in EVENTS:
        try:
            answer = handle(event, data)
            if answer:
                print(answer)
        except Exception as e:  # noqa: BLE001 — a failure never blocks the agent
            print(f'[hologram hook hermes] {type(e).__name__}: {e}', file=sys.stderr)
    return 0


def install(plugins_dir: Path) -> Tuple[Path, str]:
    """Copy the provider shim to `<plugins_dir>/hologram/` (Hermes discovers it there)."""
    src = Path(__file__).resolve().parent.parent / 'data' / 'hermes_plugin'
    dst = Path(plugins_dir) / 'hologram'
    dst.mkdir(parents=True, exist_ok=True)
    for name in ('__init__.py', 'plugin.yaml'):
        (dst / name).write_text((src / name).read_text())
    return dst, f'wrote {dst}/ (select it: memory.provider: hologram in ~/.hermes/config.yaml)'


def remove(plugins_dir: Path) -> Tuple[Path, str]:
    dst = Path(plugins_dir) / 'hologram'
    if not dst.is_dir():
        return dst, f'nothing at {dst}'
    for name in ('__init__.py', 'plugin.yaml'):
        try:
            (dst / name).unlink()
        except OSError:
            pass
    try:
        dst.rmdir()
    except OSError:
        pass
    return dst, f'removed {dst}'
