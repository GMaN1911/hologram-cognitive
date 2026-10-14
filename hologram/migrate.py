"""One-time migration of a project's state built before the fixed budget (0.4 and the research
tree before 2026-10-03), run by the router the first time it loads such a state.

A state file without a `schema` key was built under the corpus-scaled budget (0.5 per file:
with 119 files, 59.5 of pressure, everything warm and nothing hot) and, where the learner ran,
with constants learned from keyword overlap (falsified; HOLOGRAM_WORKLOG.md 2026-10-03). So:

  pressure    scaled so the total is the budget of 10, order preserved; buckets requantized
  constants   `t3_file_state.json` set aside (the files take the defaults again), only where
              the pressure needed scaling: that is the sign of a 0.4 state. A state already
              under the budget (this tree since 2026-10-03) keeps constants the current rule learned
  content     `.hologram_content_cache.npz` built under the salted word hashing (its own
              schema marker says so) set aside; it is rebuilt by `hologram_init` or the learner

Each is done once: the state is written back with `schema` = STATE_SCHEMA, the set-aside files
keep a `.pre-0.5` suffix beside the state, nothing is deleted that cannot be rebuilt.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

STATE_SCHEMA = 2        # the fixed budget of 10, competitive conservation (2026-10-03)
CONSTANTS_FILE = 't3_file_state.json'
CONTENT_CACHE = '.hologram_content_cache.npz'
SET_ASIDE = '.pre-0.5'


def needs_migration(state: dict) -> bool:
    return int(state.get('schema', 1) or 1) < STATE_SCHEMA


def scale_pressure(files: dict, budget: float) -> float:
    """Scale every file's raw pressure by one factor so the total is the budget (only when it
    exceeds it), requantizing the buckets. Returns the factor."""
    from .coordinates import quantize_pressure
    total = sum(max(0.0, float(f.get('raw_pressure', 0.0))) for f in files.values())
    if total <= budget or total <= 0:
        return 1.0
    factor = budget / total
    for f in files.values():
        f['raw_pressure'] = max(0.0, float(f.get('raw_pressure', 0.0))) * factor
        f['pressure_bucket'] = quantize_pressure(f['raw_pressure'])
    return factor


def migrate_state(state: dict, state_file: Optional[str], budget: float = 10.0) -> list[str]:
    """Migrate a loaded state in place and the files beside it. Returns what was done."""
    done = []
    if not needs_migration(state):
        return done
    factor = scale_pressure(state.get('files', {}), budget)
    if factor != 1.0:
        done.append(f'pressure scaled by {factor:.3f} to the budget of {budget:g}')
    state['schema'] = STATE_SCHEMA
    if state_file:
        here = Path(state_file).parent
        constants = here / CONSTANTS_FILE
        if factor != 1.0 and constants.exists():
            os.replace(constants, here / (CONSTANTS_FILE + SET_ASIDE))
            done.append(f'learned constants set aside ({CONSTANTS_FILE}{SET_ASIDE}); defaults apply')
        cache = here / CONTENT_CACHE
        if cache.exists() and _cache_schema(cache) < 2:
            os.replace(cache, here / (CONTENT_CACHE + SET_ASIDE))
            done.append('content cache from the salted hashing set aside; rebuilt on the next init')
    return done


def _cache_schema(path: Path) -> int:
    try:
        import numpy as np
        with np.load(str(path)) as data:
            return int(data['_meta_hash_schema'][0]) if '_meta_hash_schema' in data else 1
    except Exception:
        return 1


LEGACY_FILES = ('hologram_state.json', 'hologram_history.jsonl', '.hologram_dag_cache.json', CONSTANTS_FILE, CONTENT_CACHE)


def adopt_legacy_layout(root, state_dir) -> list[str]:
    """0.4's hook kept a project's state at the project root (`<root>/hologram_state.json`, the
    history, the DAG cache); 0.5 keeps it in `<root>/.hologram/`. The first time 0.5 opens such
    a project, the root-level files move into the state directory, so what the project learned
    under 0.4 carries over (and is then migrated like any 0.4 state) instead of starting over
    beside litter. Done once: nothing moves when the state directory already has a state."""
    root, state_dir = Path(root), Path(state_dir)
    if root == state_dir or (state_dir / 'hologram_state.json').exists() or not (root / 'hologram_state.json').exists():
        return []
    done = []
    state_dir.mkdir(parents=True, exist_ok=True)
    for name in LEGACY_FILES:
        src, dst = root / name, state_dir / name
        if src.is_file() and not dst.exists():
            try:
                os.replace(src, dst)
                done.append(name)
            except OSError:
                pass
    return [f"0.4 state adopted from the project root into {state_dir.name}/: {', '.join(done)}"] if done else []
