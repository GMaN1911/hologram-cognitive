"""The working set: the files Hologram puts in front of the model on every prompt.

Chosen by pressure RANK, never by a threshold that can leave it empty (HOLOGRAM_ROADMAP.md rule 1,
graph node hologram.tiers.rank-based-working-set). Absolute tiers left most prompts with nothing:
a budget tuned against fixed thresholds only trades "everything warm" for "nothing hot" (January
2026 and October 2026 both). Every surface that injects files (the Claude Code hook, `hologram
hook`, the other harness adapters) calls `select`.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List

# Rendered as slices on every prompt.
WORKING_SET_MAX = int(os.environ.get('HOLOGRAM_WORKING_SET_MAX', '6'))
# Below this many files holding pressure, the set is filled from the most recently modified docs.
WORKING_SET_MIN = int(os.environ.get('HOLOGRAM_WORKING_SET_MIN', '3'))
# Pressure under this is not membership: a never-activated file starts at 0.2, and decayed files
# are clamped near 0.05. One strong activation (to about 0.8) stays above it for roughly 9 prompts.
WORKING_SET_FLOOR = 0.25
# Listed by name after the rendered ones.
NEXT_NAMES_MAX = 10
# Copies of the project instructions file, which the harness already loads on its own.
CLAUDEMD_DUPS = re.compile(r'(?:^|/)CLAUDE(\s*\(\d+\))?\.md$')


@dataclass
class WorkingSet:
    files: List[str] = field(default_factory=list)   # rendered, in rank order, recency fill last
    next: List[str] = field(default_factory=list)    # listed by name
    by_pressure: int = 0
    by_recency: int = 0


def routable(router, prompt: str) -> Callable[[str], bool]:
    """Whether a path may be injected for this prompt: not a CLAUDE.md copy, and not a fixture or
    test-data path unless the prompt names it (route policy, `route_policy.py`)."""
    return lambda path: not CLAUDEMD_DUPS.search(path) and router._demotion_factor(path, prompt) == 1.0


def select(files: Dict[str, object], root: Path, is_routable: Callable[[str], bool],
           size: int = WORKING_SET_MAX, minimum: int = WORKING_SET_MIN,
           floor: float = WORKING_SET_FLOOR, named: int = NEXT_NAMES_MAX) -> WorkingSet:
    """Rank every routable file that holds pressure. The prompt's activation is already in the
    pressure, so the order is query-aware; a prompt that activates nothing ("yes, do that")
    inherits the set the previous prompts built. Nested copies of one doc (a log and an audit
    snapshot of it) are collapsed by basename so they cannot fill the set."""
    ranked, seen = [], set()
    for cf in sorted(files.values(), key=lambda f: f.raw_pressure, reverse=True):
        if cf.raw_pressure < floor:
            break
        name = Path(cf.path).name
        if not is_routable(cf.path) or name in seen:
            continue
        seen.add(name)
        ranked.append(cf.path)
    chosen = WorkingSet(files=ranked[:size], next=ranked[size:size + named])
    chosen.by_pressure = len(chosen.files)

    # Cold start, or a project whose pressure has drained: fall back to what was worked on last.
    if chosen.by_pressure < minimum:
        recent = []
        for path in files:
            if Path(path).name in seen or not is_routable(path):
                continue
            try:
                recent.append(((root / path).stat().st_mtime, path))
            except OSError:
                continue
        for _, path in sorted(recent, reverse=True):
            if len(chosen.files) >= minimum:
                break
            if Path(path).name not in seen:
                seen.add(Path(path).name)
                chosen.files.append(path)
    chosen.by_recency = len(chosen.files) - chosen.by_pressure
    return chosen
