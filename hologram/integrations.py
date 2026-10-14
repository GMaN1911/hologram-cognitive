"""Integration flags for personal-mesh features.

hologram-pro grew up inside MirrorEthic's cognitive mesh, where it reads and
writes shared state under ``~/.claude/`` (cortex memory, instance pool, mesh
bus, temporal). None of that exists on a customer machine, so every one of
those integrations is **off by default** — the customer posture. Machines
that are part of a mesh opt in via config.

Config file: ``~/.hologram/config.json``::

    {"integrations": {"cortex": true, "pool": true, "mesh": true, "temporal": true}}

Env override (wins over the file; for tests/CI and one-off runs)::

    HOLOGRAM_INTEGRATIONS=cortex,mesh     # exactly these on, others off
    HOLOGRAM_INTEGRATIONS=all             # everything on
    HOLOGRAM_INTEGRATIONS=none            # everything off

Contract: ``enabled()`` never raises and does no I/O after the first call.
When a flag is off, the corresponding code path must not stat, open, lock, or
sys.path-inject anything — security reviewers run strace, and FOOTPRINT.md
promises a clean trace.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

FLAGS = ("cortex", "pool", "mesh", "temporal")

_cache: Optional[Dict[str, bool]] = None


def _config_path() -> Path:
    override = os.environ.get("HOLOGRAM_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".hologram" / "config.json"


def _load() -> Dict[str, bool]:
    flags = {name: False for name in FLAGS}

    env = os.environ.get("HOLOGRAM_INTEGRATIONS")
    if env is not None:
        env = env.strip().lower()
        if env == "all":
            return {name: True for name in FLAGS}
        if env in ("", "none"):
            return flags
        wanted = {part.strip() for part in env.split(",")}
        return {name: (name in wanted) for name in FLAGS}

    try:
        raw = json.loads(_config_path().read_text())
        configured = raw.get("integrations", {})
        for name in FLAGS:
            flags[name] = bool(configured.get(name, False))
    except (OSError, ValueError):
        pass
    return flags


def enabled(name: str) -> bool:
    """True if the named integration is switched on. Never raises."""
    global _cache
    try:
        if _cache is None:
            _cache = _load()
        return _cache.get(name, False)
    except Exception:
        return False


def summary() -> Dict[str, bool]:
    """Current flag state (for status tools and diagnostics)."""
    global _cache
    if _cache is None:
        _cache = _load()
    return dict(_cache)


def _reset_cache() -> None:
    """Testing hook: force a reload on next enabled() call."""
    global _cache
    _cache = None
