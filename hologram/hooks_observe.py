"""
End of a turn: close the hologram route -> use -> reinforce loop, project-scoped.

Reads the Stop event (transcript_path, cwd), extracts the files actually
touched in the turn that just ended (Read = used, Edit/Write/MultiEdit/NotebookEdit
= edited), resolves the project root from cwd, and calls router.observe() so those
files get a pressure boost in THAT project's .hologram state.

A doc a shell command names counts as used (since 2026-10-05): most work goes through the shell,
and reinforcing only what a file tool opened left pressure behind the session (replay, recall
inside the working set with and without: t3-pet 0.60 against 0.53, hologram-mesh 0.52 against
0.43, d2-rally-build 0.86 against 0.86).

Only the last turn counts. Stop fires after every turn, so walking the whole
transcript re-boosted every file the session had ever touched on every turn: in
hologram-mesh 221 of 224 observe records repeated the previous one's files, the
same 11 for three days (2026-07-19..22).

Without this, per-project pressure only ever decays (WARM->COLD) and nothing
reaches the HOT tier -- the long-standing "no hot files" symptom. The hot tier
is computed entirely in hologram-pro (pressure.py); the hook only feeds it.

Designed to be fast and silent: it never runs SVD or any heavy build, is bounded
by the Stop hook's outer `timeout`, and degrades to a no-op on any error.

`observe_turn` is the single implementation. `hologram hook stop` calls it, and the Claude Code
hook script (hooks/claude/hologram-observe-stop.py) is a thin wrapper around it. `main` is the
`hologram-hook-observe` console entry.
"""
from __future__ import annotations

import sys
import json
import time
from pathlib import Path

from .hooks_inject import find_project_root, project_root, rerank_mode  # noqa: F401  (find_project_root: the wrapper's seam)
from .lexical import named_in_commands

# Tool name -> bucket. Read-like tools mean "used"; write-like mean "edited".
USED_TOOLS = {'Read', 'Grep', 'Glob', 'NotebookRead'}
EDIT_TOOLS = {'Edit', 'Write', 'MultiEdit', 'NotebookEdit'}
SHELL_TOOLS = {'Bash'}
PATH_KEYS = ('file_path', 'notebook_path', 'path')


def _tool_path(inp):
    if not isinstance(inp, dict):
        return None
    for k in PATH_KEYS:
        v = inp.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _starts_turn(rec, content):
    """A row that begins a turn: something arrived for the model to act on (a typed prompt, a
    notification, a peer's message). Tool results and the meta rows injected mid-turn do not."""
    if rec.get('type') != 'user' or rec.get('isMeta') or rec.get('isSidechain'):
        return False
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False
    return not any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in content)


def extract_files(transcript_path):
    """The (used, edited) absolute file paths of the last turn."""
    used, edited, _ = extract_turn(transcript_path)
    return used, edited


def extract_turn(transcript_path):
    """Walk the transcript JSONL: the absolute paths the last turn used and edited with file
    tools, and the shell commands it ran."""
    used, edited, commands = set(), set(), []
    try:
        with open(transcript_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = rec.get('message', rec)
                content = msg.get('content') if isinstance(msg, dict) else None
                if _starts_turn(rec, content):
                    used, edited, commands = set(), set(), []
                    continue
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get('type') != 'tool_use':
                        continue
                    name = block.get('name', '')
                    given = block.get('input', {})
                    if name in SHELL_TOOLS and isinstance(given, dict) and isinstance(given.get('command'), str):
                        commands.append(given['command'])
                        continue
                    p = _tool_path(given)
                    if not p:
                        continue
                    if name in EDIT_TOOLS:
                        edited.add(p)
                    elif name in USED_TOOLS:
                        used.add(p)
    except (OSError, FileNotFoundError):
        pass
    return used, edited, commands


def _relativize(paths, root):
    """Map paths to root-relative form (hologram keys files relative to the
    project root, e.g. 'mesh_graph/DATA_CONTRACT.md'). Paths outside the project
    are dropped — they belong to a different scope and aren't this project's
    files."""
    root = root.resolve()
    out = set()
    for p in paths:
        pp = Path(p)
        pp = pp if pp.is_absolute() else (root / pp)
        try:
            rel = pp.resolve().relative_to(root)
        except ValueError:
            continue  # outside this project root
        out.add(str(rel))
    return out


def observe_turn(data: dict, *, find_root=None, extract=None):
    """Reinforce the files the last turn touched. Returns (project root, files reinforced), or
    None when there was nothing to do. Never raises: a failure is one line on stderr.

    `extract(transcript_path)` reads the harness's transcript into (used, edited, commands);
    the default reads Claude Code's, and a harness adapter passes its own."""
    transcript = data.get('transcript_path')
    if not transcript:
        return None

    root = project_root(data, find_root)
    if root is None:
        return None

    used, edited, commands = (extract or extract_turn)(transcript)
    if not used and not edited and not commands:
        return None
    used = _relativize(used, root)
    edited = _relativize(edited, root)
    state_dir = root / '.hologram'

    try:
        from . import create_router_from_directory
        # Reinforce into the same canonical state dir the injector/learning use
        # (<root>/.hologram), so the pressure this raises is the state inference reads.
        try:
            router = create_router_from_directory(str(root), state_dir=str(state_dir))
        except TypeError:
            router = create_router_from_directory(str(root))
        tracked = set(router.system.files)
        named = named_in_commands(commands, tracked, str(root)) - used - edited
        touched = (used | edited | named) & tracked
        rec = router.observe(sorted(used | named), sorted(edited), query='') if touched else None
    except Exception as e:
        print(f"[hologram-observe] {type(e).__name__}: {e}", file=sys.stderr)
        return None

    if rec is None:
        return None
    _remember(state_dir, data.get('session_id'), touched)
    n = len(getattr(rec, 'activated', []) or [])
    print(f"[hologram-observe] {root.name}: reinforced {n} file(s)", file=sys.stderr)
    return root, n


def _remember(state_dir: Path, session_id, touched) -> None:
    """With the reranker in shadow or on: add the turn's docs to the session's record, and to
    the log its live judgement reads (hologram.eval.shadow_report)."""
    if rerank_mode() == 'off' or not session_id:
        return
    try:
        from . import session_touches
        record = session_touches.load(state_dir, session_id)
        record.record(touched)
        session_touches.save(state_dir, session_id, record)
        with open(state_dir / 'touch_log.jsonl', 'a') as log:
            log.write(json.dumps({'ts': time.time(), 'session': session_id, 'touched': sorted(touched)}) + '\n')
    except Exception as e:
        print(f"[hologram-observe] session record: {type(e).__name__}: {e}", file=sys.stderr)


def main():
    """Console entry `hologram-hook-observe`: Claude Code's Stop. Same as `hologram hook stop`."""
    from .hook import main as hook_main
    return hook_main(['stop'])


if __name__ == '__main__':
    main()
