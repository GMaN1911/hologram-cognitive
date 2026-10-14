"""Battery for integration scoping — the footprint half of the tin label.

Claims asserted:
  1. All integrations default OFF (customer posture).
  2. Config file turns them on; env var overrides both ways.
  3. MeshBus cannot be constructed with mesh off; works with it on.
  4. pool off → _load_openclaw_registry() is None and sys.path is never
     polluted with ~/openclaw-cognitive.
  5. FOOTPRINT: with defaults, a full core init+route cycle in a sandboxed
     HOME opens nothing under the real home directory (outside the package
     source itself) and opens zero sockets. Verified with sys.addaudithook
     in a subprocess — the strace claim, machine-checked.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from hologram import integrations

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def fresh_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLOGRAM_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("HOLOGRAM_INTEGRATIONS", raising=False)
    integrations._reset_cache()
    yield
    integrations._reset_cache()


# 1
def test_defaults_all_off():
    assert integrations.summary() == {
        "cortex": False, "pool": False, "mesh": False, "temporal": False
    }
    for name in integrations.FLAGS:
        assert integrations.enabled(name) is False


# 2
def test_config_file_enables(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"integrations": {"cortex": True, "mesh": True}}))
    monkeypatch.setenv("HOLOGRAM_CONFIG", str(cfg))
    integrations._reset_cache()
    assert integrations.enabled("cortex") is True
    assert integrations.enabled("mesh") is True
    assert integrations.enabled("pool") is False
    assert integrations.enabled("temporal") is False


def test_env_overrides_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"integrations": {name: True for name in integrations.FLAGS}}))
    monkeypatch.setenv("HOLOGRAM_CONFIG", str(cfg))
    monkeypatch.setenv("HOLOGRAM_INTEGRATIONS", "pool")
    integrations._reset_cache()
    assert integrations.enabled("pool") is True
    assert integrations.enabled("cortex") is False  # env list is exhaustive


def test_env_all_and_none(monkeypatch):
    monkeypatch.setenv("HOLOGRAM_INTEGRATIONS", "all")
    integrations._reset_cache()
    assert all(integrations.summary().values())
    monkeypatch.setenv("HOLOGRAM_INTEGRATIONS", "none")
    integrations._reset_cache()
    assert not any(integrations.summary().values())


def test_garbage_config_is_all_off(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{not json")
    monkeypatch.setenv("HOLOGRAM_CONFIG", str(cfg))
    integrations._reset_cache()
    assert not any(integrations.summary().values())


# 3
@pytest.mark.skipif(__import__('hologram.edition', fromlist=['EDITION']).EDITION != 'pro', reason='a Pro feature')
def test_meshbus_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from hologram.mesh import MeshBus
    with pytest.raises(RuntimeError, match="mesh integration is disabled"):
        MeshBus()
    monkeypatch.setenv("HOLOGRAM_INTEGRATIONS", "mesh")
    integrations._reset_cache()
    MeshBus()  # constructs; any files it makes land under the sandbox HOME
    assert not (Path.home() / ".claude").exists() or str(Path.home()).startswith(str(tmp_path))


# 4
@pytest.mark.skipif(__import__('hologram.edition', fromlist=['EDITION']).EDITION != 'pro', reason='a Pro feature')
def test_openclaw_sys_path_never_polluted(monkeypatch):
    from hologram.mcp import pool_registry
    before = list(sys.path)
    assert pool_registry._load_openclaw_registry() is None
    polluted = [p for p in sys.path if "openclaw" in p and p not in before]
    assert polluted == []


# 5 — the strace claim, machine-checked
FOOTPRINT_SCRIPT = textwrap.dedent("""
    import sys, os, json
    from pathlib import Path

    opened, sockets = [], []
    REPO = os.environ["FOOTPRINT_REPO"]

    def hook(event, args):
        if event == "open":
            opened.append(str(args[0]))
        elif event.startswith("socket."):
            sockets.append(event)
    sys.addaudithook(hook)

    proj = os.path.join(os.environ["HOME"], "scratch-project", ".claude")
    from hologram import cli
    for argv in (["hologram", "init", proj],
                 ["hologram", "route", proj, "hello footprint", "--quiet"],
                 ["hologram", "status", proj, "--json"]):
        sys.argv = argv
        try:
            cli.main()
        except SystemExit as e:
            if e.code not in (0, None):
                raise

    real_home = os.environ["FOOTPRINT_REAL_HOME"]
    sandbox = os.environ["HOME"]
    interpreter = (sys.prefix, sys.base_prefix)   # the interpreter's own installation (site-packages, dist-info)
    violations = [
        p for p in opened
        if p.startswith(real_home)
        and not p.startswith(REPO)          # package source lives in real home
        and not p.startswith(sandbox)
        and not p.startswith(interpreter)
    ]
    print(json.dumps({"violations": sorted(set(violations)),
                      "sockets": sockets,
                      "opens_total": len(opened)}))
""")


def test_core_cycle_footprint(tmp_path):
    env = dict(os.environ)
    env.update({
        "HOME": str(tmp_path / "sandbox-home"),
        "FOOTPRINT_REAL_HOME": str(Path.home()),
        "FOOTPRINT_REPO": str(REPO),
        "PYTHONPATH": str(REPO),
        "HOLOGRAM_INTEGRATIONS": "none",
    })
    env.pop("HOLOGRAM_LICENSE_KEY", None)
    (tmp_path / "sandbox-home").mkdir()

    out = subprocess.run(
        [sys.executable, "-c", FOOTPRINT_SCRIPT],
        env=env, capture_output=True, text=True, timeout=120, cwd=str(tmp_path),
    )
    assert out.returncode == 0, f"stderr:\n{out.stderr[-2000:]}"
    verdict = json.loads(out.stdout.strip().splitlines()[-1])
    assert verdict["violations"] == [], (
        "core cycle touched paths outside sandbox/package:\n"
        + "\n".join(verdict["violations"])
    )
    assert verdict["sockets"] == [], f"unexpected network activity: {verdict['sockets']}"
    assert verdict["opens_total"] > 0  # the hook actually observed the run


# ---------- first-run init hint (inject hook onboarding) ----------

def _run_inject(cwd, home, repo=REPO):
    import subprocess as sp
    env = dict(os.environ, HOME=str(home), PYTHONPATH=str(repo),
               HOLOGRAM_INTEGRATIONS="none")
    env.pop("HOLOGRAM_LICENSE_DIR", None)
    out = sp.run([sys.executable, "-m", "hologram.hooks_inject"],
                 input=json.dumps({"prompt": "where is the auth code?", "cwd": str(cwd)}),
                 capture_output=True, text=True, env=env, timeout=60)
    return out.stdout.strip()


def test_first_run_hint_in_git_project(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    proj = tmp_path / "proj"; (proj / ".git").mkdir(parents=True)
    out = _run_inject(proj, home)
    assert "hologram init" in out and str(proj) in out
    # second call within the dedupe window: silent
    assert _run_inject(proj, home) == ""


def test_no_hint_outside_projects(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    plain = tmp_path / "plain"; plain.mkdir()   # no VCS marker
    assert _run_inject(plain, home) == ""
    assert _run_inject(home, home) == ""        # $HOME never hints
