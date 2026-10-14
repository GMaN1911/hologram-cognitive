"""
The [HOLOGRAM] layer: what a harness adds to the model's context on every prompt.

Routes the prompt against the project, picks the working set by pressure rank
(`working_set.select`), renders each file as a slice (t3-doc/v1 types get a typed slice, anything
else a preview plus excerpts around the prompt's words), appends project memories, and returns one
block under a byte cap (schema t3-ctx/v1).

`build_layer` is the single implementation. `hologram hook prompt` calls it for every harness,
and the Claude Code hook script (hooks/claude/hologram-typed-injector.py) is a thin wrapper around
it. `main` is the `hologram-hook-inject` console entry.
"""
from __future__ import annotations

import sys
import time
import os
import json
import re
import signal
import threading
from contextlib import contextmanager
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # typed slicing degrades to the plain preview

from . import working_set
from .route_policy import is_harness_message


@contextmanager
def route_budget(seconds: int):
    """Raise TimeoutError inside the block after `seconds`, where an alarm can be set: a POSIX
    main thread. Windows has no SIGALRM and a worker thread cannot own one; there the block runs
    unbounded and the harness's own hook timeout is the limit."""
    alarm = hasattr(signal, 'SIGALRM') and threading.current_thread() is threading.main_thread()
    if not alarm or seconds <= 0:
        yield
        return

    def _timeout(signum, frame):
        raise TimeoutError('route exceeded budget')
    prev = signal.signal(signal.SIGALRM, _timeout)
    try:
        signal.alarm(seconds)
        yield
    finally:
        signal.alarm(0)
        if prev is not None:
            signal.signal(signal.SIGALRM, prev)

INSTANCE_ID = 'hook-typed'
ROUTE_TIMEOUT_SEC = 10  # must stay BELOW the harness's own hook timeout (Claude Code wrapper: 12s)
DAG_BUDGET_SEC = 5      # DAG recompute share of ROUTE_TIMEOUT_SEC; the rest is file load + dynamics

# Claude Code passes a UserPromptSubmit hook's merged output inline only while it is small: a
# 12.7KB output arrived as a 2KB preview plus a file path (2026-10-03). This layer shares that
# output with whatever else the harness merges in, so it stays well under.
HOLOGRAM_LAYER_CAP = int(os.environ.get('HOLOGRAM_LAYER_CAP', '7000'))
SUMMARY_MAX = 200
LEGACY_PREVIEW_CHARS = 300
SECTIONS_MAX = 12
MEMORY_LIMIT = int(os.environ.get('HOLOGRAM_MEMORY_LIMIT', '5'))
MEMORY_PREVIEW_CHARS = 180
# The hybrid memory engine (cortex_v2) is queried through its own interpreter, so its
# dependencies stay out of this package's. Absent on a machine: the legacy index answers.
CORTEX_PYTHON = os.environ.get('HOLOGRAM_CORTEX_PYTHON', '~/CVMP/T3_sims/venv/bin/python3')
CORTEX_RECALL_CLI = os.environ.get('HOLOGRAM_CORTEX_RECALL_CLI', '~/group-chat-mcp/cortex_recall_cli.py')
# Where a memory backend's failure is noted (silent fallbacks hid a stale primary for months,
# 2026-07-09 audit). Under Hologram's own directory, never ~/.claude.
FALLBACK_LOG = os.environ.get('HOLOGRAM_FALLBACK_LOG', '~/.hologram/injector_fallback.log')
# The reranker (hologram/rerank.py), read from HOLOGRAM_RERANK when a prompt arrives:
#   linear   the reranker chooses the working set from the wider pool (the default since
#            2026-10-06: held out, 0.696/0.663/0.866 against pressure's 0.519/0.599/0.862 on
#            hologram-mesh, t3-pet and d2-rally-build; HOLOGRAM_WORKLOG.md 2026-10-05), and
#            the T3v4-R rerank is not applied.
#   shadow   the reranker's choice is computed and written to the injection log; nothing the
#            model sees changes. For judging it on live sessions (hologram.eval.shadow_report).
#   off      pressure alone chooses the working set.
# In shadow and linear the end of a turn also records what the session touched
# (hologram/session_touches.py).
RERANK_MODES = ('off', 'shadow', 'linear')
RERANK_DEFAULT = 'linear'


def rerank_mode() -> str:
    mode = os.environ.get('HOLOGRAM_RERANK', RERANK_DEFAULT).strip().lower()
    return mode if mode in RERANK_MODES else RERANK_DEFAULT


def _load_lineage() -> dict:
    """Optional: project name -> ancestor project names, used to broaden a thin memory recall.
    Configured in ~/.hologram/config.json under "project_lineage"."""
    try:
        cfg_path = os.environ.get('HOLOGRAM_CONFIG') or str(Path.home() / '.hologram' / 'config.json')
        return dict(json.loads(Path(cfg_path).read_text()).get('project_lineage', {}))
    except Exception:
        return {}


PROJECT_LINEAGE = _load_lineage()


class RouteFailed(Exception):
    """Routing raised or ran out of time. The caller decides whether the model is told."""


def _memory_enabled() -> bool:
    """The mesh's memory (the recall CLI, the legacy index over ~/.claude/memory) is shared state
    outside the project. A build that ships integration flags keeps it off until the machine
    opts in; a tree without flags has it on. The hologram-cortex package's store is Hologram's
    own (~/.hologram/memory) and needs no flag."""
    try:
        from .integrations import enabled
    except ImportError:
        return True
    return enabled('cortex')


def find_project_root(start: Path) -> Path | None:
    cur = start.resolve()
    home = Path.home().resolve()
    claude_home = (home / '.claude').resolve()
    while cur != cur.parent and cur != home:
        # Never treat ~/.claude or its subtree as a project. It's the shared
        # knowledge base, and its .hologram content-cache dir is a false-positive
        # project marker — routing here pulls the whole home megagraph. When the
        # session cwd wanders into ~/.claude (e.g. editing hooks), walk up past it
        # so the CLAUDE_PROJECT_DIR fallback can resolve the real project instead.
        if cur == claude_home or claude_home in cur.parents:
            cur = cur.parent
            continue
        if (cur / '.claude').exists() or (cur / '.hologram').exists():
            return cur
        cur = cur.parent
    return None


def parse_frontmatter(content: str):
    if not content.startswith('---\n'):
        return None, content
    end = content.find('\n---\n', 4)
    if end < 0 or yaml is None:
        return None, content
    try:
        fm = yaml.safe_load(content[4:end])
    except yaml.YAMLError:
        return None, content
    if not isinstance(fm, dict) or fm.get('schema') != 't3-doc/v1':
        return None, content
    return fm, content[end + 5:]


def first_sentence(body: str) -> str:
    body = body.lstrip('# \n')
    m = re.search(r'[^.\n]{20,200}[.!?]', body)
    return m.group(0).strip() if m else body[:200].strip()


def last_h2_or_bold(body: str) -> str:
    matches = re.findall(r'^(##\s+.+|\*\*.+\*\*)$', body, re.MULTILINE)
    return matches[-1].strip() if matches else ''


def slice_architecture(fm, body):
    out = [f"  summary: {(fm.get('summary') or '').strip()}"]
    secs = fm.get('sections') or []
    if secs:
        shown = secs[:SECTIONS_MAX]
        extra = len(secs) - len(shown)
        line = '  sections: ' + ' | '.join(s.strip() for s in shown)
        if extra > 0:
            line += f' (+{extra} more)'
        out.append(line)
    return '\n'.join(out)


def slice_snapshot(fm, body):
    out = [f"  summary: {(fm.get('summary') or '').strip()}"]
    keys = fm.get('keystone_results') or []
    if keys:
        out.append('  keystone: ' + ' | '.join(k.strip() for k in keys[:2]))
    secs = fm.get('sections') or []
    if secs:
        out.append('  sections: ' + ' | '.join(s.strip() for s in secs[:6]))
    return '\n'.join(out)


def slice_design(fm, body):
    out = [
        f"  summary: {(fm.get('summary') or '').strip()}",
        f"  status: {fm.get('status', 'unknown')}",
    ]
    thesis = first_sentence(body)
    if thesis:
        out.append(f"  thesis: {thesis[:200]}")
    return '\n'.join(out)


def slice_worklog(fm, body):
    out = [f"  summary: {(fm.get('summary') or '').strip()}"]
    tail_bytes = int(fm.get('tail_bytes') or 600)
    # Strip leading/trailing whitespace, then take tail. Collapse multiple
    # blank lines so we get more signal per byte. Indent 4-space to fit
    # within the t3-ctx HOLOGRAM block visually.
    cleaned = re.sub(r'\n{3,}', '\n\n', body.rstrip())
    tail = cleaned[-tail_bytes:]
    # Snap to nearest line boundary so we don't cut a sentence mid-word
    nl = tail.find('\n')
    if 0 < nl < 100:
        tail = tail[nl + 1:]
    indented = '\n'.join('    ' + ln for ln in tail.splitlines())
    out.append(f"  tail ({len(tail)}B):\n{indented}")
    return '\n'.join(out)


def slice_experiment(fm, body):
    out = [f"  summary: {(fm.get('summary') or '').strip()}"]
    keys = fm.get('keystone_results') or []
    joined = ' | '.join(k.strip() for k in keys)
    if joined and len(joined) <= 500:
        out.append(f"  keystone: {joined}")
    elif keys:
        out.append('  keystone: ' + ' | '.join(k.strip() for k in keys[:2]))
    return '\n'.join(out)


def slice_memo(fm, body):
    bullets = re.findall(r'^[\-\*]\s+(.+)$', body, re.MULTILINE)
    out = [f"  summary: {(fm.get('summary') or '').strip()}"]
    if bullets:
        out.append('  bullets: ' + ' | '.join(b.strip()[:80] for b in bullets[:3]))
    return '\n'.join(out)


def slice_todo(fm, body):
    open_count = len(re.findall(r'^[\-\*]\s+\[\s\]', body, re.MULTILINE))
    return f"  summary: {(fm.get('summary') or '').strip()}\n  open: {open_count}"


def slice_project_hub(fm, body):
    out = [f"  summary: {(fm.get('summary') or '').strip()}"]
    m = re.search(r'^\*\*Status:\*\*\s*(.+)$', body, re.MULTILINE)
    if m:
        out.append(f"  status_line: {m.group(1).strip()[:200]}")
    secs = fm.get('sections') or re.findall(r'^##\s+(.+)$', body, re.MULTILINE)
    if secs:
        shown = [s.strip() for s in secs[:SECTIONS_MAX]]
        extra = len(secs) - len(shown)
        line = '  sections: ' + ' | '.join(shown)
        if extra > 0:
            line += f' (+{extra} more)'
        out.append(line)
    return '\n'.join(out)


def slice_log(fm, body):
    tail = body.rstrip().splitlines()[-2:]
    out = [f"  summary: {(fm.get('summary') or '').strip()}"]
    if tail:
        out.append('  tail: ' + ' | '.join(t.strip()[:120] for t in tail))
    return '\n'.join(out)


SLICERS = {
    'architecture': slice_architecture,
    'snapshot': slice_snapshot,
    'design': slice_design,
    'worklog': slice_worklog,
    'experiment': slice_experiment,
    'memo': slice_memo,
    'todo': slice_todo,
    'log': slice_log,
    # aliases — existing docs use richer type names; map them to the nearest
    # slicer instead of forcing a rename (2026-07-09 backfill)
    'architecture-spec': slice_architecture,
    'paradigm-statement': slice_design,
    'pretrain-strategy': slice_design,
    'protocol': slice_design,
    'rebuild-plan': slice_design,
    'testing-suite': slice_design,
    'project-hub': slice_project_hub,
}


def _content_is_unanchored(content: str) -> bool:
    """T1/T2 check on recalled memory previews (Context Grounding Program I2:
    legacy pollution is annotated at injection, not rewritten). Fail-open —
    a missing hologram tree just means no flag."""
    try:
        from .okf.lint import lint_text
        return any(f.code in ('T1', 'T2') for f in lint_text(content))
    except Exception:
        return False


def _note_fallback(line: str) -> None:
    try:
        path = Path(os.path.expanduser(FALLBACK_LOG))
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {line}\n")
    except Exception:
        pass


def _package_recall(prompt: str, project_name: str, limit: int):
    """The hologram-cortex package (the `memory` extra): semantic once `hologram-cortex setup` has
    run, keyword recall before that. None when the package is not installed."""
    try:
        from hologram_cortex import recall as cortex_recall
    except ImportError:
        return None
    return cortex_recall.recall(project_name, prompt, limit)


def edition_is_pro() -> bool:
    """Project memory is Pro: the core's layer carries no memory section at all."""
    from .edition import EDITION
    return EDITION == 'pro'


def query_memories(prompt: str, project_name: str, limit: int):
    """Project-scoped memory query with lineage fallback.

    On a machine with the mesh's recall CLI: cortex_v2 through its own interpreter.
    Otherwise the hologram-cortex package when it is installed (what a customer has).
    FALLBACK: the legacy MemoryIndex over ~/.claude/memory on empty/error, so injection never
    breaks. Returns list of {id, topic, category, content, project, ...} dicts.
    """
    from .edition import EDITION
    if EDITION != 'pro':
        return [], None      # project memory is Pro; the core's prompt is the working set alone
    # --- cortex_v2 primary (flag CORTEX_V2=0 to disable) ---
    primary_answered = False   # cortex_v2 ran and found nothing: an answer, not an outage
    _cli = os.path.expanduser(CORTEX_RECALL_CLI)
    mesh = _memory_enabled()
    if os.environ.get("CORTEX_V2", "1") != "0" and not (mesh and os.path.exists(_cli)):
        # The package's store is the only store on a customer's machine: its answer, empty
        # or not, is the answer. The legacy index below is the mesh's (~/.claude/memory).
        try:
            _mems = _package_recall(prompt, project_name, limit)
            if _mems is not None:
                return _mems, None
        except Exception as _e:
            _note_fallback(f"hologram-cortex fallback: {type(_e).__name__}: {_e}")
    elif os.environ.get("CORTEX_V2", "1") != "0":
        try:
            import subprocess, json as _json
            _venv = os.path.expanduser(CORTEX_PYTHON)
            # warm daemon path is ~1.5s even under load; 8s covers a daemon-down
            # cold fallback. Must stay below ROUTE_TIMEOUT_SEC (10) / wrapper cap (12).
            _r = subprocess.run([_venv, _cli, f"proj_{project_name}", prompt, str(limit)],
                                capture_output=True, text=True, timeout=8)
            _mems = _json.loads(_r.stdout or "[]")
            if _mems:
                return _mems, None
            primary_answered = _r.returncode == 0
        except Exception as _e:
            _note_fallback(f"cortex_v2 fallback: {type(_e).__name__}: {_e}")

    # --- legacy Cortex-Memory (fallback) ---
    # memory_index uses package-relative imports, so it must load as hologram.mcp.memory_index
    # (the bare-module import failed on every empty cortex_v2 answer and rendered as an outage).
    def _legacy_failed(msg):
        _note_fallback(f"legacy fallback: {msg}")
        return [], (None if primary_answered else msg)

    if not mesh or not (Path.home() / '.claude' / 'memory' / 'entries.jsonl').exists():
        return [], None      # no store is no memory, not an outage (and no ~/.claude path is opened)

    try:
        from .mcp.memory_index import MemoryIndex
    except ImportError as e:
        return _legacy_failed(f"import: {e}")

    try:
        idx = MemoryIndex()
        idx.refresh_if_stale()
    except Exception as e:
        return _legacy_failed(f"init: {e}")

    lineage = PROJECT_LINEAGE.get(project_name, [project_name])
    seen_ids = set()
    results = []
    for proj in lineage:
        try:
            mems = idx.query(query=prompt, project=proj, limit=limit * 2)
        except Exception:
            continue
        for m in mems:
            mid = m.get('id', '')
            if mid in seen_ids:
                continue
            # Filter daemon noise
            if m.get('project') == 'research-daemon':
                continue
            if m.get('category', '').upper() == 'RESEARCH' and 'daemon' in (m.get('topic', '') or '').lower():
                continue
            seen_ids.add(mid)
            results.append(m)
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    return results, None


def slice_legacy(content: str) -> str:
    preview = content.replace('\n', ' ')[:LEGACY_PREVIEW_CHARS]
    return f"  preview: {preview}"


def slice_file(path: str, content: str) -> str:
    fm, body = parse_frontmatter(content)
    name = path  # project-relative: the model can open it, and two files with one basename stay distinct
    if fm is None:
        return f"- {name} [legacy/unknown]\n" + slice_legacy(content)
    typ = fm.get('type', 'unknown')
    status = fm.get('status', 'unknown')
    version = fm.get('version', '')
    head = f"- {name} [{typ}/{status}" + (f"/{version}" if version else '') + "]"
    slicer = SLICERS.get(typ)
    if slicer is None:
        return head + '\n' + slice_legacy(content)
    return head + '\n' + slicer(fm, body)


def _apply_t3_state(system, state_dir):
    """Load learned per-file T³ decay/boost into the router's files BEFORE pressure
    dynamics run — mirrors Session._load_t3_state. HologramRouter has no t3-load path
    of its own, so without this the injector always routes with default boost/decay
    even though the Stop-hook learning trains t3_file_state.json every turn."""
    try:
        t3_path = Path(state_dir) / 't3_file_state.json'
        if not t3_path.exists():
            return 0
        data = json.loads(t3_path.read_text())
        n = 0
        for path, state in data.items():
            f = system.files.get(path)
            if f is not None:
                f.learned_decay = state.get('learned_decay', 0.85)
                f.learned_boost = state.get('learned_boost', 0.6)
                n += 1
        return n
    except Exception:
        return 0


def _apply_predictor_rerank(system, prompt, state_dir):
    """Blend the trained T3v4-R predictor into the pressure ranking, matching the
    MCP hologram_route re-rank (warmup-gated, max 30% influence). Boosts raw_pressure
    then re-quantizes pressure_bucket so get_context() re-tiers on the new order.

    Uses the ENGINE's hologram.learning classes (not the ~/.claude/scripts standalone
    copies, which drift). Fully defensive: any failure returns None and leaves the
    pure-pressure ranking untouched, so the [HOLOGRAM] layer never breaks on this.
    """
    from .edition import pro
    if pro('learning') is None:
        return None          # the learned predictor is Pro
    try:
        import numpy as np
        from .learning import (
            T4RPredictor, extract_file_features, CoactivationMatrix, ContentEmbedder,
        )
        from .coordinates import quantize_pressure

        sd = Path(state_dir)
        # The product's place first (the license worker delivers the weights there), then
        # the mesh's.
        frozen = next((str(c) for c in (Path.home() / '.hologram' / 'models' / 't3v4r_frozen.npz',
                                        Path.home() / '.claude' / 't3v4r_frozen.npz') if c.exists()), None)
        if frozen is None or T4RPredictor is None:   # no weights, or a wheel without the module
            return None
        predictor = T4RPredictor.load(frozen, str(sd / 'predictor_w.npz'))
        if not (predictor.is_ready() and predictor.warmup_weight > 0):
            return None

        files = system.files
        hot_set = {n for n, f in files.items() if getattr(f, 'raw_pressure', 0) >= 0.8}

        hist_path = sd / 'hologram_history.jsonl'
        coact = (CoactivationMatrix.load(str(hist_path), str(sd / '.hologram_coact_cache.json'))
                 if hist_path.exists() else None)
        norm = coact.norm_stats() if coact else None

        content_emb = None
        cc = sd / '.hologram_content_cache.npz'
        if cc.exists():
            try:
                content_emb = ContentEmbedder.load(str(cc))
            except Exception:
                content_emb = None
        has_content = bool(
            content_emb is not None
            and getattr(content_emb, 'svd_components', None) is not None
            and len(getattr(content_emb, 'file_embeddings', {})) > 0
        )
        q_embed = content_emb.embed_query(prompt) if has_content else None

        file_list = []
        for name, cf in files.items():
            out_edges = getattr(cf, 'outgoing_edges', [])
            in_edges = getattr(cf, 'incoming_edges', [])
            dag_to_hot = sum(1 for e in list(out_edges) + list(in_edges) if e in hot_set)
            ca = coact.features_for(name, hot_set) if coact else {}
            cosine_sim = 0.0
            content_vec = None
            if has_content and q_embed is not None:
                f_embed = content_emb.get_file_embedding(name)
                cosine_sim = float(np.dot(q_embed, f_embed))
                content_vec = f_embed
            features = extract_file_features(
                name,
                hot_freq=ca.get('hot_freq', 0) or getattr(cf, 'activation_count', 0),
                warm_freq=ca.get('warm_freq', 0),
                dag_out=len(out_edges), dag_in=len(in_edges),
                coact_with_hot=ca.get('coact_with_hot', 0),
                coact_max=ca.get('coact_max', 0),
                dag_to_hot=dag_to_hot,
                cosine_sim=cosine_sim,
                content_embedding=content_vec,
                norm=norm,
            )
            file_list.append((name, features))

        if not file_list:
            return None
        scores = predictor.predict(prompt, file_list)
        w = predictor.warmup_weight * 0.30  # max 30% influence (matches MCP re-rank)
        for name, score in scores.items():
            cf = files.get(name)
            if cf is None:
                continue
            boost = (score - 0.5) * 2.0 * w  # [-0.3, +0.3]
            cf.raw_pressure = max(0.0, min(1.0, getattr(cf, 'raw_pressure', 0.0) + boost))
            cf.pressure_bucket = quantize_pressure(cf.raw_pressure)  # re-tier
        return f"t3v4r w={w:.2f} files={len(scores)}"
    except Exception as e:
        print(f"[predictor] skip: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _reranked(router, root: Path, prompt: str, typed: bool, activated, state_dir: str, session_id):
    """The reranker's working set for this prompt: (files, next names, what brought each into
    the pool), or None when it cannot answer. Called before the T3v4-R rerank moves pressure,
    so the reranker sees the pressures it was trained on."""
    from .edition import pro
    rerank = pro('rerank')
    if rerank is None:
        return None          # the linear reranker is Pro; the core ranks by pressure
    try:
        from . import session_touches
        from .lexical import Lexical
        model = rerank.load_model()
        if model is None:
            return None
        files = router.system.files
        is_routable = working_set.routable(router, prompt)
        pool = rerank.build_pool(files, working_set.select(files, root, is_routable),
                                 session_touches.load(state_dir, session_id), Lexical(files),
                                 prompt, typed, activated, is_routable)
        picked, after = rerank.choose(pool, model, working_set.WORKING_SET_MAX, working_set.NEXT_NAMES_MAX)
        return picked, after, pool.source
    except Exception as e:
        print(f"[rerank] skip: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def project_root(data: dict, find_root=None) -> Path | None:
    """The project a hook event belongs to: the nearest one above its working directory, else
    above the harness's own project directory. Every hook event resolves its project here, so
    what a prompt routes and what the end of the turn reinforces are the same project."""
    find_root = find_root or find_project_root
    cwd = data.get('cwd') or os.environ.get('PWD') or os.getcwd()
    root = find_root(Path(cwd))
    if root is None:
        # cwd may have wandered (agent `cd` to scratchpad/tmp follows into the
        # session cwd and silently killed the whole layer — 2026-07-09). Fall
        # back to the harness project dir before giving up.
        alt = os.environ.get('CLAUDE_PROJECT_DIR')
        if alt:
            root = find_root(Path(alt))
    return root


def _size(text: str) -> int:
    return len(text.encode('utf-8'))


def build_layer(data: dict, *, find_root=None, memories=None, instance_id=None,
                route_timeout=None, cap=None) -> str:
    """The layer for one prompt event (`data` carries `prompt` and `cwd`), or '' when there is
    nothing to inject: no prompt, or no project above the working directory. Raises RouteFailed.

    The keywords are the seams a harness adapter needs: how the project root is found, where
    memories come from, the routing instance id, the time budget, and the size the layer must
    stay under (UTF-8 bytes). Each defaults to this module's own."""
    recall = memories or query_memories
    instance_id = instance_id or INSTANCE_ID
    route_timeout = ROUTE_TIMEOUT_SEC if route_timeout is None else route_timeout
    cap = HOLOGRAM_LAYER_CAP if cap is None else cap

    prompt = (data.get('prompt') or '').strip()
    # "go", "yes", "ok" still get the working set: a short prompt is where continuity matters most.
    if not prompt:
        return ''

    root = project_root(data, find_root)
    if root is None:
        return ''

    from . import create_router_from_directory
    # A task notification, a subagent's hand-back or another session's message is not a prompt:
    # it gets the working set as it stands, and pressure, the turn counter and memory recall
    # are left alone.
    held = is_harness_message(prompt)
    mode = rerank_mode()
    session_id = data.get('session_id')

    # A cold or mostly-invalidated DAG cache on a large project must degrade to stale edges
    # inside the route budget rather than be killed by the alarm with nothing saved.
    os.environ.setdefault('HOLOGRAM_DAG_BUDGET_SEC', str(DAG_BUDGET_SEC))
    # Canonical per-project state dir: <root>/.hologram (scan the project root forward, keep
    # pressure/history/predictor state out of the tree and convergent with the observe-stop
    # and learning hooks). No state_dir -> legacy root-level layout that litters the repo and
    # forks the store.
    state_dir = str(root / '.hologram')

    def _route():
        try:
            router = create_router_from_directory(
                str(root), instance_id=instance_id, state_dir=state_dir)
        except TypeError:
            try:
                router = create_router_from_directory(str(root), state_dir=state_dir)
            except TypeError:
                router = create_router_from_directory(str(root))
        # Load learned T³ decay/boost before dynamics (HologramRouter won't on its own).
        _apply_t3_state(router.system, state_dir)
        activated = set()
        if held:
            router.hold('harness-message')
        else:
            activated = set(router.process_query(prompt).activated)
        ranked = None
        if mode != 'off':
            ranked = _reranked(router, root, prompt, not held, activated, state_dir, session_id)
        if not held and not (mode == 'linear' and ranked):
            # Blend the trained T3v4-R predictor into the ranking BEFORE tiering — this
            # is the primary inference surface the predictor was training for but never
            # reached (it lived only in the dead HOLOGRAM_TYPED else-branch). Defensive:
            # returns None and leaves pure-pressure order intact on any failure.
            pred_status = _apply_predictor_rerank(router.system, prompt, state_dir)
            if pred_status:
                print(f"[predictor] {pred_status}", file=sys.stderr)
        stale = getattr(router.system, 'dag_stale_sources', 0)
        if stale:
            print(f"[dag] {stale} sources on stale edges (budget {DAG_BUDGET_SEC}s); converges over later prompts",
                  file=sys.stderr)
        return router, ranked

    try:
        with route_budget(route_timeout):
            router, reranked = _route()
            ctx = router.get_context_dict()
            system_files = router.system.files
    except Exception as e:
        raise RouteFailed(f"route failed: {type(e).__name__}: {e}") from e

    # Route policy: fixture/test-data trees stay indexed but are never injected unless the
    # prompt names them (activation already skips them; this covers pressure that reached
    # them by propagation or before the gate existed).
    chosen = working_set.select(system_files, root, working_set.routable(router, prompt))
    by_pressure_alone = list(chosen.files)
    sources = {}
    if mode == 'linear' and reranked:
        chosen.files, chosen.next, sources = list(reranked[0]), list(reranked[1]), reranked[2]
        chosen.by_pressure = sum(1 for path in chosen.files if sources.get(path) == 'pressure')
        chosen.by_recency = len(chosen.files) - chosen.by_pressure
    n_hot, n_warm = len(ctx.get('hot', [])), len(ctx.get('warm', []))

    parts = [
        f"[HOLOGRAM] (cap={cap}B, schema=t3-ctx/v1, project={root.name})",
        f"  tier_counts: hot={n_hot} warm={n_warm} cold={ctx.get('cold_count', 0)}"
        f" (working set {len(chosen.files)}: {chosen.by_pressure} by pressure,"
        f" {chosen.by_recency} by recency)",
    ]
    if held:
        parts.append("  held: harness message (no activation, no decay, no memory recall)")
    if sources:
        # The line above keeps its two counts for the tools that parse it; this one says what
        # the places not held by pressure were given for.
        count = lambda source: sum(1 for path in chosen.files if sources.get(path) == source)
        parts.append(f"  reranked: {count('pressure')} by pressure, {count('session')} from this session,"
                     f" {count('lexical')} by the prompt's words, {count('recency')} by recency")
    used = sum(_size(p) + 1 for p in parts)

    # Query-matched excerpts: slices carry a doc's summary/tail, but an answer
    # buried mid-document (append-only logs) is invisible to any tier logic.
    # The original hologram put FULL files in context; the surgical version is a
    # grep-window around query-token match clusters — full-file recall at ~2% of
    # the token cost. (2026-07-09 cross-project eval, needle-in-log finding.)
    _qtok = set() if held else {t for t in re.findall(r'[a-z0-9_]+', prompt.lower()) if len(t) > 3}

    def query_excerpts(body, already_shown, max_windows=2, ctx_lines=2, max_chars=700):
        if not _qtok or not body:
            return []
        lines = body.split('\n')
        # In-doc IDF: rare terms ("geodesic") must outrank ubiquitous ones
        # ("training" appears hundreds of times in a training log) — without
        # this, 3 generic hits beat 2 specific ones and the needle line loses.
        import math
        body_low = body.lower()
        w = {t: len(t) / (1.0 + math.log2(1 + body_low.count(t))) for t in _qtok}
        scored = []
        for i, ln in enumerate(lines):
            low = ln.lower()
            hits = [t for t in _qtok if t in low]
            if len(hits) >= 2:
                scored.append((sum(w[t] for t in hits), i))
        scored.sort(reverse=True)
        out, taken = [], []
        for n, i in scored:
            if any(abs(i - j) <= ctx_lines * 2 for j in taken):
                continue
            win = '\n'.join(l for l in lines[max(0, i - ctx_lines):i + ctx_lines + 1])
            win = win.strip()
            if not win or win[:80] in already_shown:
                continue
            out.append('  match: ' + win.replace('\n', ' ¶ ')[:max_chars // max_windows])
            taken.append(i)
            if len(out) >= max_windows:
                break
        return out

    truncated = 0
    typed_count = 0
    legacy_count = 0
    for path in chosen.files:
        cf = system_files.get(path)
        content = getattr(cf, 'content', '') if cf else ''
        slice_text = slice_file(path, content)
        if '[legacy/' in slice_text.splitlines()[0]:
            legacy_count += 1
        else:
            typed_count += 1
        cost = _size(slice_text) + 1
        if used + cost > cap - 200:
            truncated += 1
            continue
        parts.append(slice_text)
        used += cost
        for exc in query_excerpts(content, slice_text):
            if used + _size(exc) + 1 > cap - 200:
                break
            parts.append(exc)
            used += _size(exc) + 1

    # MEMORY block — project-scoped Cortex-Memory working memory
    memories, mem_err = ([], None) if held else recall(prompt, root.name, MEMORY_LIMIT)
    if memories:
        parts.append(f"  MEMORIES ({len(memories)} project-scoped, by relevance):")
        mem_used = 0
        for m in memories:
            cat = m.get('category', '?') or '?'
            topic = (m.get('topic') or '').strip()
            age = m.get('age_days', 0)
            refs = m.get('reinforcements', 0)
            proj = m.get('project') or '?'
            content = (m.get('content') or '').replace('\n', ' ').strip()[:MEMORY_PREVIEW_CHARS]
            ref_str = f" ref{refs}" if refs else ""
            # E1 stamp: full ISO anchor + pre-computed delta (grounding probe
            # 2026-07-17: models read anchors but fumble day-crossing math —
            # the emitter does the subtraction). Dateless renders as 'undated',
            # never as ambient present. Legacy unanchored content gets flagged.
            as_of = m.get('as_of')
            stamp = f"{as_of} ({age}d ago)" if as_of else f"undated (~{age}d ago)"
            tref = m.get('temporal_reference')
            tref_str = f", {tref}" if tref else ""
            flag = " ⚠unanchored-content" if _content_is_unanchored(content) else ""
            line = f"  - [{cat}] {topic} ({proj}, {stamp}{tref_str}{ref_str}){flag}"
            if content:
                line += f": {content}"
            if used + mem_used + _size(line) + 1 > cap - 120:
                break
            parts.append(line)
            mem_used += _size(line) + 1
        used += mem_used
    elif mem_err:
        parts.append(f"  MEMORIES: (unavailable: {mem_err})")
        used += _size(parts[-1]) + 1
    elif not held and edition_is_pro():
        parts.append("  MEMORIES: (none matched)")
        used += _size(parts[-1]) + 1

    if chosen.next:
        warm_line = "  next: " + ' | '.join(Path(path).name for path in chosen.next)
        if used + _size(warm_line) + 1 <= cap - 80:
            parts.append(warm_line)
            used += _size(warm_line) + 1

    if truncated > 0:
        parts.append(f"  (+{truncated} HOT files dropped to fit cap)")

    parts.append(
        f"  bytes_used: {used}/{cap} | "
        f"typed={typed_count} legacy={legacy_count} mem={len(memories)}"
    )

    # One line per prompt: what was injected and from which source. It is the live record the
    # graph's probes read (never empty, size under the cap) and the basis for judging recency.
    try:
        with open(Path(state_dir) / 'injection_log.jsonl', 'a') as log:
            log.write(json.dumps({
                'ts': time.time(), 'turn': ctx.get('turn'), 'by_pressure': chosen.by_pressure,
                'by_recency': chosen.by_recency, 'files': list(chosen.files),
                'next': len(chosen.next), 'bytes': used, 'cap': cap,
                **({'held': True} if held else {}),
                **({'session': session_id} if session_id and mode != 'off' else {}),
                **({'rerank': mode, 'reranked': list(reranked[0]), 'pressure_set': by_pressure_alone}
                   if reranked else {}),
            }) + '\n')
    except OSError:
        pass

    return '\n'.join(parts)


def main():
    """Console entry `hologram-hook-inject`: Claude Code's UserPromptSubmit. Same as
    `hologram hook prompt`."""
    from .hook import main as hook_main
    return hook_main(['prompt'])


if __name__ == '__main__':
    main()
