"""Query-aware file demotion and query-term selection shared by activation, injection and MCP routing."""

import re
from fnmatch import fnmatchcase

# Words that say nothing about which file a query is about. Without this filter any sentence
# activates every prose file through "the" / "and" / "for".
# The route policy, defined once (hologram.inv.one-policy-one-place): what a project scan skips,
# and which paths are evaluation fixtures or test data, indexed but demoted at activation and
# ranking unless the query names them. The router, the MCP project scanner and every harness
# read these; nothing else carries a copy.
DEFAULT_IGNORES = tuple([
        '.git/**', '.hologram/**', '__pycache__/**', '*.pyc',
        'node_modules/**', 'venv/**', '.venv/**', 'env/**',
        '*.egg-info/**', 'dist/**', 'build/**',
        '.pytest_cache/**', '.mypy_cache/**', '.ruff_cache/**',
        '.claude/**', '.claude-dev/**', '.codex/**', '.grok/**', '.cache/**',   # the harnesses' own state (Hologram writes .grok/rules)
        '.ipynb_checkpoints/**', '.tox/**',
        '*.lock', 'package-lock.json', 'yarn.lock',
        '*.min.js', '*.min.css', '*.map',
        '*.png', '*.jpg', '*.jpeg', '*.gif', '*.ico', '*.svg',
        '*.woff', '*.woff2', '*.ttf', '*.eot',
        '*.zip', '*.tar', '*.gz', '*.bz2',
        '*.pdf', '*.doc', '*.docx',
        '*.so', '*.dylib', '*.dll', '*.exe',
        '*.npz', '*.pt', '*.bin', '*.ckpt', '*.safetensors',
    ])
DEMOTE_PATTERNS = tuple([
        'eval_fixtures/**', '**/eval_fixtures/**',
        'fixtures/**', '**/fixtures/**', '__fixtures__/**', '**/__fixtures__/**',
        'testdata/**', '**/testdata/**',
    ])
DEMOTE_FACTOR = 0.1
DEMOTE_RELEASE_TOKENS = tuple([
        'fixture', 'fixtures', '__fixtures__', 'eval_fixtures', 'testdata', 'test data',
    ])

QUERY_STOPWORDS = frozenset([
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'to', 'of',
    'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through',
    'during', 'before', 'after', 'above', 'below', 'between', 'out', 'off',
    'over', 'under', 'again', 'further', 'then', 'once', 'here', 'there',
    'when', 'where', 'why', 'how', 'all', 'any', 'each', 'few', 'more',
    'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own',
    'same', 'so', 'than', 'too', 'very', 'just', 'and', 'but', 'if', 'or',
    'because', 'until', 'while', 'this', 'that', 'these', 'those', 'it',
    'its', 'they', 'them', 'their', 'what', 'which', 'who', 'whom', 'you',
    'your', 'she', 'her', 'him', 'his', 'our', 'about', 'also', 'now',
    'get', 'got', 'let', 'lets', 'see', 'use', 'yes', 'yeah', 'like',
    'want', 'know', 'think', 'make', 'look', 'still', 'well', 'into',
])

_EDGE_PUNCTUATION = '.,;:!?()[]{}<>"\'`*'

# What a harness delivers in the prompt slot that nobody typed: a background task finishing, a
# subagent handing back, another session writing in (Claude Code's wrappers). Routing them as
# prompts activated files on task ids and report prose and decayed everything once per message:
# 38% of 1,334 routed prompts across five projects (2026-10-05), and a fan-out of twenty agents
# is twenty decay steps in the middle of one task.
HARNESS_MESSAGE = re.compile(r'\s*<(task-notification|agent-message|cross-session-message)[\s>]')


def is_harness_message(prompt: str) -> bool:
    """True when the "prompt" is a harness message. It still gets the working set as it
    stands; it does not activate, decay or count as a turn."""
    return bool(HARNESS_MESSAGE.match(prompt or ''))


def query_terms(query: str) -> list:
    """The query's words that can select a file: lowercased, edge punctuation stripped,
    3+ chars, no stop-words, each once in first-seen order."""
    terms = []
    for raw in (query or '').lower().split():
        word = raw.strip(_EDGE_PUNCTUATION)
        if len(word) > 2 and word not in QUERY_STOPWORDS and word not in terms:
            terms.append(word)
    return terms


def demotion_released(config, query: str = "") -> bool:
    """True when the query names a demoted area, which lifts demotion for the turn."""
    for token in getattr(config, "demote_release_tokens", ()) or ():
        if re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", query or "", re.I):
            return True
    return False


def is_demoted_path(config, path: str) -> bool:
    patterns = getattr(config, "demote_patterns", None)
    if not patterns:
        return False
    rel = str(path).replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return any(fnmatchcase(rel, pattern) for pattern in patterns)


def demotion_factor(config, path: str, query: str = "") -> float:
    if not getattr(config, "demote_patterns", None):
        return 1.0
    if demotion_released(config, query):
        return 1.0
    return config.demote_factor if is_demoted_path(config, path) else 1.0
