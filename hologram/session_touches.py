"""What one session has touched: its docs, most recent first, and how many of its turns ago.

Pressure lets go of a doc about nine prompts after its last use. A session often comes back to
one later, and in replay a third to a half of the docs the working set missed were docs the same
session had touched before (HOLOGRAM_WORKLOG.md, 2026-10-05). Giving such docs pressure or fixed
places costs more than it finds, so this only remembers them: the reranker (hologram/rerank.py)
decides which are worth a place.

One small file per session under <state dir>/sessions/, written at the end of a turn and read
when the next prompt arrives. Concurrent sessions in one project each have their own.
"""

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

DIRECTORY = 'sessions'
KEEP_DOCS = 60          # per session
KEEP_DAYS = 14          # a session file not written for this long is removed


@dataclass
class SessionTouches:
    turns: int = 0                                         # turns of this session that touched a tracked doc
    order: List[str] = field(default_factory=list)         # docs, most recently touched first
    last: Dict[str, int] = field(default_factory=dict)     # doc -> `turns` when it was last touched

    def age(self, doc: str) -> Optional[int]:
        """How many touching turns ago the session last touched `doc` (1: the last one)."""
        return self.turns - self.last[doc] if doc in self.last else None

    def record(self, docs: Iterable[str]) -> None:
        docs = sorted(set(docs))
        if not docs:
            return
        for doc in docs:
            if doc in self.order:
                self.order.remove(doc)
            self.order.insert(0, doc)
            self.last[doc] = self.turns
        for doc in self.order[KEEP_DOCS:]:
            self.last.pop(doc, None)
        del self.order[KEEP_DOCS:]
        self.turns += 1


def _path(state_dir, session_id: str) -> Path:
    return Path(state_dir) / DIRECTORY / (re.sub(r'[^A-Za-z0-9_.-]', '_', session_id)[:120] + '.json')


def load(state_dir, session_id: Optional[str]) -> SessionTouches:
    """The session's record, or an empty one (no session id, first turn, unreadable file)."""
    if not session_id:
        return SessionTouches()
    try:
        data = json.loads(_path(state_dir, session_id).read_text())
        return SessionTouches(int(data['turns']), [str(d) for d in data['order']],
                              {str(k): int(v) for k, v in data['last'].items()})
    except (OSError, ValueError, KeyError, TypeError):
        return SessionTouches()


def save(state_dir, session_id: Optional[str], touches: SessionTouches) -> None:
    if not session_id:
        return
    path = _path(state_dir, session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'turns': touches.turns, 'order': touches.order, 'last': touches.last}))
        os.replace(tmp, path)
        cutoff = time.time() - KEEP_DAYS * 86400
        for other in path.parent.glob('*.json'):
            if other.stat().st_mtime < cutoff:
                other.unlink()
    except OSError:
        pass
