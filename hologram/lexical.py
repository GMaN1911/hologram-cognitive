"""The prompt's words against each doc's path and content (BM25), and whether a text names a doc.

Used by the reranker (hologram/rerank.py) on the hook path and by the offline evaluation that
trains it, so both see the same numbers. Building the index costs about 30 ms for 140 docs and
0.4 s for 750 (content capped at 40,000 characters a doc); it is rebuilt per prompt.
"""

import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Set

from .route_policy import QUERY_STOPWORDS

WORD = re.compile(r'[a-z0-9_]+')
CONTENT_CHARS = 40000


def tokens(text: str) -> List[str]:
    return [w for w in WORD.findall((text or '').lower()) if len(w) > 2 and w not in QUERY_STOPWORDS]


class Lexical:
    """BM25 over each doc's path (weighted three times) and content."""

    def __init__(self, files: Dict[str, object]):
        self.docs = {}
        df = Counter()
        for path, f in files.items():
            words = tokens(path.replace('/', ' ').replace('.', ' ')) * 3 + tokens((getattr(f, 'content', '') or '')[:CONTENT_CHARS])
            self.docs[path] = (Counter(words), len(words))
            df.update(set(words))
        n = len(files)
        self.average = (sum(length for _, length in self.docs.values()) / n) if n else 1.0
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def scores(self, query: str) -> Dict[str, float]:
        """Every doc that shares a word with the query, with its score."""
        words = set(tokens(query))
        out = {}
        for path, (tf, length) in self.docs.items():
            score = sum(self.idf[w] * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * length / self.average))
                        for w in words if w in tf)
            if score > 0:
                out[path] = score
        return out

    def ranked(self, query: str) -> List[str]:
        scores = self.scores(query)
        return sorted(scores, key=scores.get, reverse=True)


def named(text: str, path: str) -> bool:
    """The doc is named in `text`: by its project-relative path, or by a file name long enough
    not to match by accident."""
    name = os.path.basename(path)
    return bool(text) and (path in text or (len(name) >= 8 and re.search(
        r'(?<![\w.-])' + re.escape(name) + r'(?![\w-])', text) is not None))


END = r'(?![\w-])(?!\.\w)'   # the name ends here: not notes.md.bak, not notes.md-old


def named_in_commands(commands: List[str], tracked: Set[str], root: str = '') -> Set[str]:
    """The tracked files a turn's shell commands name: by path, or by a file name that only one
    tracked file has and that is long enough not to match by accident.

    A name several files share credits none of them. Until 2026-10-05 it credited all of them:
    one command mentioning README.md "touched" every README in the corpus (eight vendored copies
    in t3-pet), and that was a large part of what the replay counted as missed."""
    if not commands:
        return set()
    text = '\n'.join(commands)
    shared = {}
    for path in tracked:
        shared[os.path.basename(path)] = shared.get(os.path.basename(path), 0) + 1
    roots = [root.rstrip('/') + '/'] if root else []
    home = str(Path.home()) + '/'
    roots += ['~/' + r[len(home):] for r in roots if r.startswith(home)]

    def at_a_path_start(start: int) -> bool:
        before = text[max(0, start - 300):start]
        if not before or before[-1] not in '/.-' and not (before[-1].isalnum() or before[-1] == '_'):
            return True
        return any(before.endswith(r) for r in roots) or (before.endswith('./') and not before.endswith('../'))

    found = set()
    for path in tracked:
        name = os.path.basename(path)
        if name not in text:
            continue
        if any(at_a_path_start(m.start()) for m in re.finditer(re.escape(path) + END, text)):
            found.add(path)
        elif len(name) >= 8 and shared[name] == 1 and re.search(
                r'(?<![\w.-])' + re.escape(name) + END, text):
            found.add(path)
    return found
