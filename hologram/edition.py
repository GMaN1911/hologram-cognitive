"""Which edition this installation is.

Hologram Pro and the free hologram-cognitive (MIT) are built from one tree: the core is exported
with the Pro modules left out (`scripts/export_core.py`) and this line rewritten to 'core'. Shared
code reaches every Pro feature through `pro(name)`, which returns the module or None, so the same
function runs in both editions and the core simply has less to say.

Pro: the causal research graph and its guards (crg), the blackboard (board), Cortex memory, the
MCP servers, the linear reranker, the Codex, Grok and Antigravity adapters, the Claude Code mod,
licensing and upgrades. Core: the routing engine, the Claude Code hooks and the Hermes provider.
"""
from __future__ import annotations

import importlib
from types import ModuleType
from typing import Optional

EDITION = 'core'
PRO_URL = 'https://hologram-pro.dev'
PRO_FEATURES = 'the project graph and its guards, the blackboard, project memory, and the Codex, Grok and Antigravity adapters'


def distribution() -> str:
    """The installed distribution this edition ships as."""
    return 'hologram-cognitive-pro' if EDITION == 'pro' else 'hologram-cognitive'


def version() -> str:
    """The installed version, from the distribution's metadata ('unknown' in a source checkout)."""
    try:
        from importlib.metadata import version as _version
        return _version(distribution())
    except Exception:
        return 'unknown'


def pro(name: str) -> Optional[ModuleType]:
    """The Pro module `hologram.<name>`, or None in the core edition (or when it is absent)."""
    if EDITION != 'pro':
        return None
    try:
        return importlib.import_module(f'hologram.{name}')
    except ImportError:
        return None


def pro_only(feature: str) -> str:
    """The one line the core prints where a Pro feature would be (to the person, never the model)."""
    return f'{feature} is part of Hologram Pro: {PRO_URL}'
