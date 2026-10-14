"""Explicit editor-integration install/uninstall.

Contract (FOOTPRINT.md "Installed hooks" section): integration is only ever
written by an explicit `hologram install ...` step — never implicitly on
import or first run — every planned change is printed before it happens, and
`hologram uninstall` reverses all of it using a manifest recorded at install
time (``~/.hologram/install_manifest.json``).

Integration depth varies by tool — this is a capability fact, not favoritism:

  claude-code   MCP server + hooks on every event (the working set and the graph on each
                prompt, the graph at session start, guards before a tool, reinforcement at
                the end of the turn) + the Hologram mod (status line, /holo, /guard).
  codex         MCP server + the same hooks through `hologram hook codex`
                (~/.codex/hooks.json; Codex asks you to re-trust the file in /hooks).
  grok          hooks only (~/.grok/hooks/hologram.json; Grok has no MCP registration CLI).
  gemini        MCP server only (Gemini CLI has no hook mechanism).
  cursor        printed MCP config instructions (no CLI to drive).

When the hologram-cortex package is installed (`hologram-cognitive-pro[memory]`), its MCP
server is registered beside Hologram's for the tools that take one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

MCP_SERVER_NAME = "hologram"
MCP_COMMAND = "hologram-mcp"
MEMORY_SERVER_NAME = "hologram-cortex"
MEMORY_COMMAND = "hologram-cortex"
MEMORY_ARGS = ["serve"]


def _exe(name: str) -> str:
    """This installation's console script by absolute path (hologram.harness.executable), so
    a registration works whatever PATH the editor's shell has."""
    from hologram.harness import executable
    return executable(name)


def _memory_server_available() -> bool:
    """The hologram-cortex package rides in this wheel; its MCP server is registered when its
    console script is there."""
    try:
        import hologram_cortex  # noqa: F401
    except ImportError:
        return False
    return os.path.isabs(_exe(MEMORY_COMMAND)) or bool(shutil.which(MEMORY_COMMAND))


def _codex_hooks_path() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "hooks.json"


def _grok_hooks_dir() -> Path:
    return Path.home() / ".grok" / "hooks"


def _antigravity_hooks_file() -> Path:
    return Path.home() / ".gemini" / "config" / "hooks.json"


def _antigravity_settings_path() -> Path:
    return Path.home() / ".gemini" / "antigravity-cli" / "settings.json"


# Antigravity's permission engine does not read MCP tool annotations (probed on agy 1.3.5,
# 2026-10-14): without an allow-rule, headless mode soft-denies every MCP call and interactive
# mode prompts. These two rules give parity with Claude Code and Codex, where the board and
# memory tools run unattended. Every tool on both servers is local and reversible; neither
# server has a tool that spends money or leaves the machine.
ANTIGRAVITY_ALLOW_RULES = ("mcp(hologram/*)", "mcp(hologram-cortex/*)")


def _antigravity_rules(settings_path: Path, add: bool) -> str:
    """Add or remove Hologram's allow-rules in agy's settings.json, leaving the rest alone."""
    try:
        settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    except ValueError:
        return f"could not parse {settings_path}; add {', '.join(ANTIGRAVITY_ALLOW_RULES)} yourself"
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    if add:
        changed = [r for r in ANTIGRAVITY_ALLOW_RULES if r not in allow]
        allow.extend(changed)
    else:
        changed = [r for r in ANTIGRAVITY_ALLOW_RULES if r in allow]
        for rule in changed:
            allow.remove(rule)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    verb = "added" if add else "removed"
    return f"{verb} {len(changed)} allow-rule(s) in {settings_path}" if changed else "allow-rules already as wanted"


def _claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _manifest_path() -> Path:
    override = os.environ.get("HOLOGRAM_LICENSE_DIR")  # shares the config dir
    base = Path(override) if override else Path.home() / ".hologram"
    return base / "install_manifest.json"


def _read_manifest() -> dict:
    try:
        return json.loads(_manifest_path().read_text())
    except (OSError, ValueError):
        return {}


def _write_manifest(data: dict) -> None:
    p = _manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(p)


def _confirm(prompt: str, assume_yes: bool, input_fn: Callable[[str], str]) -> bool:
    if assume_yes:
        return True
    try:
        return input_fn(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _mcp_extra_missing() -> bool:
    try:
        import mcp  # noqa: F401
        return False
    except ImportError:
        return True


def _run_mcp_add(tool_bin: str, args: List[str], echo) -> int:
    result = subprocess.run([tool_bin] + args, capture_output=True, text=True)
    if result.returncode != 0:
        echo(f"{Path(tool_bin).name} {' '.join(args[:2])} failed ({result.returncode}):")
        echo((result.stderr or result.stdout).strip())
    return result.returncode


# ---------------------------------------------------------------- claude-code

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def _install_claude_hooks(assume_yes: bool, input_fn, echo) -> int:
    """Register the hooks for every event and the Hologram mod in Claude Code settings
    (hologram.harness.claude_code decides the entries; older entries of ours are replaced)."""
    from hologram.harness import claude_code
    settings_path = _claude_settings_path()
    try:
        settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    except (OSError, ValueError) as e:
        echo(f"Cannot read {settings_path}: {e} — skipping hooks (MCP server still works).")
        return 1

    new_settings, changes = claude_code.install(settings)
    if new_settings == settings:
        echo("Hooks already registered — nothing to do.")
        return 0

    backup = settings_path.with_name(
        f"settings.json.hologram-backup-{time.strftime('%Y%m%d-%H%M%S')}")
    echo("This will edit your Claude Code settings:")
    echo(f"    file:   {settings_path}")
    echo(f"    backup: {backup.name} (written first)")
    for change in changes:
        echo(f"    {change}")
    echo("    effect: every prompt gets its working set of files and the project graph's")
    echo("            line; a session start gets the graph's brief; guarded edits are refused;")
    echo("            the files a turn used reinforce routing after every response; the mod")
    echo("            adds the status line, /holo and /guard.")
    if not _confirm("Proceed?", assume_yes, input_fn):
        echo("Skipped hooks. The MCP server registration stands on its own.")
        return 1

    if settings_path.exists():
        shutil.copy2(settings_path, backup)
    _write_json(settings_path, new_settings)

    manifest = _read_manifest()
    manifest["claude_code_hooks"] = {
        "settings_path": str(settings_path),
        "events": sorted(claude_code.HOOKS),
        "commands": sorted({h["command"] for groups in claude_code.HOOKS.values()
                            for g in groups for h in g["hooks"]}),
        "mod": str(claude_code.mod_dir() or ""),
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    _write_manifest(manifest)
    echo("Hooks registered (restart Claude Code sessions to pick them up).")
    return 0


def _remove_claude_hooks(entry: dict, echo) -> int:
    from hologram.harness import claude_code
    settings_path = Path(entry.get("settings_path") or _claude_settings_path())
    try:
        settings = json.loads(settings_path.read_text())
    except (OSError, ValueError):
        echo(f"{settings_path} unreadable — hooks may already be gone.")
        return 0
    new_settings, changes = claude_code.remove(settings)
    if changes:
        _write_json(settings_path, new_settings)
        echo("Removed hologram hooks and the mod from Claude Code settings.")
    return 0


# -------------------------------------------------------------- codex, grok

def _install_codex_hooks(assume_yes: bool, input_fn, echo) -> int:
    """Hologram's entries in ~/.codex/hooks.json (hologram.harness.codex)."""
    from hologram.harness import codex
    path = _codex_hooks_path()
    try:
        config = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError) as e:
        echo(f"Cannot read {path}: {e} — skipping hooks (MCP server still works).")
        return 1
    new_config, changes = codex.install(config)
    if new_config == config:
        echo("Codex hooks already registered — nothing to do.")
        return 0
    echo("This will edit your Codex hooks:")
    echo(f"    file: {path}")
    for change in changes:
        echo(f"    {change}")
    echo("    Codex trusts hooks.json by hash: open /hooks in Codex afterwards and re-trust it.")
    if not _confirm("Proceed?", assume_yes, input_fn):
        echo("Skipped hooks. The MCP server registration stands on its own.")
        return 1
    if path.exists():
        shutil.copy2(path, path.with_name(f"hooks.json.hologram-backup-{time.strftime('%Y%m%d-%H%M%S')}"))
    _write_json(path, new_config)
    manifest = _read_manifest()
    manifest["codex_hooks"] = {"path": str(path), "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    _write_manifest(manifest)
    echo("Codex hooks registered. Re-trust the file in Codex's /hooks.")
    return 0


def _remove_codex_hooks(entry: dict, echo) -> int:
    from hologram.harness import codex
    path = Path(entry.get("path") or _codex_hooks_path())
    try:
        config = json.loads(path.read_text())
    except (OSError, ValueError):
        echo(f"{path} unreadable — Codex hooks may already be gone.")
        return 0
    new_config, changes = codex.remove(config)
    if changes:
        _write_json(path, new_config)
        echo("Removed hologram hooks from Codex (re-trust the file in /hooks).")
    return 0


def install_grok(
    assume_yes: bool = False,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
) -> int:
    """Hologram's own hook file in ~/.grok/hooks (hologram.harness.grok). Grok has no MCP
    registration CLI, so this is the whole integration."""
    from hologram.harness import grok
    hooks_dir = _grok_hooks_dir()
    target = hooks_dir / grok.HOOK_FILE
    echo("This will make exactly one change:")
    echo(f"    write {target} (Hologram's own file; nothing else in the directory is touched)")
    echo("    effect: the project graph goes to .grok/rules/hologram.md at session start, the")
    echo("            working set rides the first tool result of each prompt, guarded edits are")
    echo("            refused, and the end of a turn reinforces what it used.")
    if not _confirm("Proceed?", assume_yes, input_fn):
        echo("Aborted. No changes were made.")
        return 1
    path, change = grok.install(hooks_dir)
    manifest = _read_manifest()
    manifest["grok"] = {"path": str(path), "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    _write_manifest(manifest)
    echo(f"Installed: {change}.")
    echo("Undo at any time with: hologram uninstall")
    return 0


def install_claude_code(
    scope: str = "user",
    with_hooks: bool = True,
    assume_yes: bool = False,
    claude_bin: Optional[str] = None,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
) -> int:
    """Register the hologram MCP server (and optionally hooks) with Claude Code."""
    if _mcp_extra_missing():
        echo("The MCP server needs the optional [mcp] extra:")
        echo("    pip install 'hologram-cognitive-pro[mcp]'")
        echo("Install it, then re-run `hologram install claude-code`.")
        return 1

    claude = claude_bin or shutil.which("claude")
    if not claude:
        echo("Claude Code CLI (`claude`) not found on PATH.")
        echo("Manual registration — run this once Claude Code is installed:")
        echo(f"    claude mcp add -s {scope} {MCP_SERVER_NAME} -- {MCP_COMMAND}")
        echo("No changes were made.")
        return 1

    mcp_cmd, mem_cmd = _exe(MCP_COMMAND), _exe(MEMORY_COMMAND)
    cmd = [claude, "mcp", "add", "-s", scope, MCP_SERVER_NAME, "--", mcp_cmd]
    echo("This will make exactly one change:" if not _memory_server_available() else "This will make two changes:")
    echo(f"    run: {' '.join(cmd)}")
    echo(f"    (registers the `{MCP_SERVER_NAME}` MCP server, {scope} scope,")
    echo(f"     launching `{mcp_cmd}` from this environment)")
    if _memory_server_available():
        echo(f"    run: {claude} mcp add -s {scope} {MEMORY_SERVER_NAME} -- {mem_cmd} {' '.join(MEMORY_ARGS)}")
        echo("    (the memory tools: memory_add, memory_query, memory_brief ...)")
    if not _confirm("Proceed?", assume_yes, input_fn):
        echo("Aborted. No changes were made.")
        return 1

    code = _run_mcp_add(claude, cmd[1:], echo)
    if code != 0:
        return code

    manifest = _read_manifest()
    manifest["claude_code"] = {
        "server_name": MCP_SERVER_NAME,
        "scope": scope,
        "command": mcp_cmd,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if _memory_server_available():
        rc = _run_mcp_add(claude, ["mcp", "add", "-s", scope, MEMORY_SERVER_NAME, "--", mem_cmd, *MEMORY_ARGS], echo)
        if rc == 0:
            manifest["claude_code"]["memory_server_name"] = MEMORY_SERVER_NAME
            echo(f"`{MEMORY_SERVER_NAME}` (the memory tools) is registered beside it.")
    _write_manifest(manifest)
    echo(f"Installed. `{MCP_SERVER_NAME}` is registered with Claude Code ({scope} scope).")

    if with_hooks:
        echo("")
        _install_claude_hooks(assume_yes, input_fn, echo)

    echo("Undo at any time with: hologram uninstall")
    return 0


# ------------------------------------------------------------- other editors

def install_antigravity(
    assume_yes: bool = False,
    tool_bin: Optional[str] = None,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
) -> int:
    """Hologram's named entry in Antigravity's global hooks.json (hologram.harness.antigravity),
    both MCP servers through `agy mcp add`, and the two allow-rules that let their tools run
    unattended. Antigravity merges named hooks across files, so every other entry is kept."""
    from hologram.harness import antigravity
    binary = tool_bin or shutil.which("agy")
    if binary and "/snap/" in str(Path(binary).resolve()):
        echo("Your `agy` is the snap build, which cannot run host programs: snap confinement")
        echo("denies every hook command with `Permission denied` (probed on agy 1.2.11), and its")
        echo("config lives in a confined home this installer does not manage.")
        echo("Install the native build instead, then re-run:")
        echo("    curl -fsSL https://antigravity.google/cli/install.sh | bash")
        echo("No changes were made.")
        return 1
    target = _antigravity_hooks_file()
    with_mcp = bool(binary) and not _mcp_extra_missing()
    with_memory = with_mcp and _memory_server_available()
    echo("This will make the following changes:")
    echo(f"    merge a `{antigravity.HOOK_NAME}` entry into {target} (other entries are kept)")
    echo("    effect: the working set and the project graph's line arrive as an ephemeral")
    echo("            message on the first model call of each turn, guarded calls are refused,")
    echo("            and the end of a turn reinforces what it used.")
    if with_mcp:
        echo(f"    run: agy mcp add {MCP_SERVER_NAME} -- {_exe(MCP_COMMAND)}")
        if with_memory:
            echo(f"    run: agy mcp add {MEMORY_SERVER_NAME} -- {_exe(MEMORY_COMMAND)} serve")
        echo(f"    add {', '.join(ANTIGRAVITY_ALLOW_RULES)} under permissions.allow in")
        echo(f"        {_antigravity_settings_path()}")
        echo("        (Antigravity does not read MCP annotations; without these rules every")
        echo("         board and memory call prompts, and headless mode denies them.)")
    elif binary:
        echo("    (MCP servers skipped: install the [mcp] extra to register the board and")
        echo("     memory tools — pip install 'hologram-cognitive-pro[mcp]')")
    else:
        echo("    (`agy` not found on PATH: hooks only; re-run after installing Antigravity")
        echo("     to register the MCP servers)")
    if not _confirm("Proceed?", assume_yes, input_fn):
        echo("Aborted. No changes were made.")
        return 1
    path, change = antigravity.install(target)
    manifest = _read_manifest()
    manifest["antigravity"] = {"path": str(path), "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    echo(f"Installed: {change}.")
    if with_mcp:
        servers = []
        if _run_mcp_add(binary, ["mcp", "add", MCP_SERVER_NAME, "--", _exe(MCP_COMMAND)], echo) == 0:
            servers.append(MCP_SERVER_NAME)
        if with_memory and _run_mcp_add(
                binary, ["mcp", "add", MEMORY_SERVER_NAME, "--", _exe(MEMORY_COMMAND), "serve"], echo) == 0:
            servers.append(MEMORY_SERVER_NAME)
        if servers:
            manifest["antigravity"]["servers"] = servers
            manifest["antigravity"]["agy"] = binary
        echo(_antigravity_rules(_antigravity_settings_path(), add=True))
        manifest["antigravity"]["rules"] = list(ANTIGRAVITY_ALLOW_RULES)
    _write_manifest(manifest)
    echo("Undo at any time with: hologram uninstall")
    return 0


def _hermes_plugins_dir() -> Path:
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes") / "plugins"


def _hermes_config(binary: str, args: List[str]) -> Tuple[int, str]:
    """Hermes's own config CLI, so its YAML is never edited behind its back."""
    try:
        done = subprocess.run([binary, "config", *args], capture_output=True, text=True, timeout=60)
        return done.returncode, (done.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def install_hermes(
    assume_yes: bool = False,
    tool_bin: Optional[str] = None,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
) -> int:
    """Hologram as Hermes Agent's memory provider (hologram.harness.hermes): the provider shim in
    Hermes's user plugins directory, selected with `hermes config set`. Hermes has one active
    memory provider; the one it had is recorded and restored by `hologram uninstall`."""
    from hologram.harness import hermes
    binary = tool_bin or shutil.which("hermes")
    if not binary:
        echo("`hermes` not found on PATH. Install Hermes Agent first, then re-run.")
        echo("No changes were made.")
        return 1
    plugins = _hermes_plugins_dir()
    command = _exe("hologram")
    _, previous = _hermes_config(binary, ["get", "memory.provider"])
    previous = previous.splitlines()[-1].strip() if previous else ""
    echo("This will make the following changes:")
    echo(f"    write {plugins / 'hologram'}/ (Hologram's provider shim; nothing else there is touched)")
    echo("    run: hermes config set memory.provider hologram"
         + (f"   (replaces `{previous}`; restored on uninstall)" if previous and previous != "hologram" else ""))
    echo(f"    run: hermes config set memory.hologram.command {command}")
    echo("    effect: the working set and the project graph's line ride each prompt, the graph's")
    echo("            brief joins the system prompt, and each turn reinforces what it used.")
    if not _confirm("Proceed?", assume_yes, input_fn):
        echo("Aborted. No changes were made.")
        return 1
    path, change = hermes.install(plugins)
    rc1, _ = _hermes_config(binary, ["set", "memory.provider", "hologram"])
    rc2, _ = _hermes_config(binary, ["set", "memory.hologram.command", command])
    manifest = _read_manifest()
    manifest["hermes"] = {"path": str(path), "hermes": binary,
                          "previous_provider": previous if previous != "hologram" else "",
                          "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    _write_manifest(manifest)
    echo(f"Installed: {change}.")
    if rc1 or rc2:
        echo("`hermes config set` did not succeed; select it yourself:")
        echo("    hermes config set memory.provider hologram")
        echo(f"    hermes config set memory.hologram.command {command}")
        return 1
    echo("Undo at any time with: hologram uninstall")
    return 0


def install_simple_mcp(
    tool: str,
    assume_yes: bool = False,
    tool_bin: Optional[str] = None,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
    with_hooks: bool = True,
) -> int:
    """MCP registration for tools with an `<tool> mcp add` CLI (gemini, codex); Codex also
    gets the hooks."""
    if _mcp_extra_missing():
        echo("The MCP server needs the optional [mcp] extra:")
        echo("    pip install 'hologram-cognitive-pro[mcp]'")
        return 1

    binary = tool_bin or shutil.which(tool)
    mcp_cmd, mem_cmd = _exe(MCP_COMMAND), _exe(MEMORY_COMMAND)
    add_args = {"gemini": ["mcp", "add", MCP_SERVER_NAME, mcp_cmd],
                "codex": ["mcp", "add", MCP_SERVER_NAME, "--", mcp_cmd]}[tool]
    if not binary:
        echo(f"`{tool}` CLI not found on PATH. Manual registration:")
        echo(f"    {tool} {' '.join(add_args)}")
        echo("No changes were made.")
        return 1

    echo("This will make exactly one change:")
    echo(f"    run: {binary} {' '.join(add_args)}")
    if tool == "gemini":
        echo("    note: Gemini CLI gets MCP tools only — it has no hook mechanism.")
    if not _confirm("Proceed?", assume_yes, input_fn):
        echo("Aborted. No changes were made.")
        return 1

    code = _run_mcp_add(binary, add_args, echo)
    if code != 0:
        return code
    manifest = _read_manifest()
    manifest[tool] = {
        "server_name": MCP_SERVER_NAME,
        "command": mcp_cmd,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if _memory_server_available():
        memory_args = {"gemini": ["mcp", "add", MEMORY_SERVER_NAME, mem_cmd, *MEMORY_ARGS],
                       "codex": ["mcp", "add", MEMORY_SERVER_NAME, "--", mem_cmd, *MEMORY_ARGS]}[tool]
        if _run_mcp_add(binary, memory_args, echo) == 0:
            manifest[tool]["memory_server_name"] = MEMORY_SERVER_NAME
            echo(f"`{MEMORY_SERVER_NAME}` (the memory tools) is registered beside it.")
    _write_manifest(manifest)
    echo(f"Installed. `{MCP_SERVER_NAME}` is registered with {tool}.")
    if tool == "codex" and with_hooks:
        echo("")
        _install_codex_hooks(assume_yes, input_fn, echo)
    echo("Undo at any time with: hologram uninstall")
    return 0


def print_cursor_instructions(echo: Callable[[str], None] = print) -> int:
    """Cursor has no registration CLI — print the exact config to paste."""
    echo("Cursor: add this to ~/.cursor/mcp.json (create it if absent):")
    servers = {MCP_SERVER_NAME: {"command": _exe(MCP_COMMAND)}}
    if _memory_server_available():
        servers[MEMORY_SERVER_NAME] = {"command": _exe(MEMORY_COMMAND), "args": list(MEMORY_ARGS)}
    echo(json.dumps({"mcpServers": servers}, indent=2))
    echo("No files were changed. (MCP tools only — hooks are Claude Code features.)")
    return 0


# ------------------------------------------------------------------ uninstall

def uninstall(
    purge: bool = False,
    assume_yes: bool = False,
    claude_bin: Optional[str] = None,
    tool_bins: Optional[dict] = None,
    input_fn: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
) -> int:
    """Reverse everything `hologram install` did. Returns exit code."""
    manifest = _read_manifest()
    tool_bins = tool_bins or {}
    planned: List[str] = []

    if manifest.get("claude_code"):
        e = manifest["claude_code"]
        planned.append(f"run: claude mcp remove -s {e['scope']} {e['server_name']}")
    if manifest.get("claude_code_hooks"):
        planned.append("remove hologram hook entries and the mod from ~/.claude/settings.json")
    for tool in ("gemini", "codex"):
        if manifest.get(tool):
            planned.append(f"run: {tool} mcp remove {manifest[tool]['server_name']}")
    if manifest.get("codex_hooks"):
        planned.append(f"remove hologram hook entries from {manifest['codex_hooks']['path']}")
    if manifest.get("grok"):
        planned.append(f"delete {manifest['grok']['path']}")
    if manifest.get("antigravity"):
        planned.append(f"remove the hologram entry from {manifest['antigravity']['path']}")
        for name in manifest["antigravity"].get("servers", []):
            planned.append(f"run: agy mcp remove {name}")
        if manifest["antigravity"].get("rules"):
            planned.append(f"remove Hologram's allow-rules from {_antigravity_settings_path()}")
    if manifest.get("hermes"):
        planned.append(f"delete {manifest['hermes']['path']}/")
        prev = manifest['hermes'].get('previous_provider')
        planned.append(f"run: hermes config set memory.provider {prev}" if prev
                       else "run: hermes config unset memory.provider")
        planned.append("run: hermes config unset memory.hologram.command")
    for key in ("claude_code", "gemini", "codex"):
        if (manifest.get(key) or {}).get("memory_server_name"):
            planned.append(f"remove the {MEMORY_SERVER_NAME} MCP server from {key.replace('_', '-')}")
    if purge:
        planned.append("delete ~/.hologram/ entirely — including your LICENSE KEY and config")

    if not planned:
        echo("Nothing to uninstall (no install manifest found).")
        echo("Per-project state lives in each project's .hologram/ or .claude/ —")
        echo("delete those directories yourself if you want them gone.")
        return 0

    echo("This will make the following changes:")
    for step in planned:
        echo(f"    {step}")
    if not _confirm("Proceed?", assume_yes, input_fn):
        echo("Aborted. No changes were made.")
        return 1

    code = 0

    entry = manifest.get("claude_code")
    if entry:
        claude = claude_bin or shutil.which("claude")
        if claude:
            rc = _run_mcp_add(claude, ["mcp", "remove", "-s", entry["scope"], entry["server_name"]], echo)
            if rc == 0:
                echo(f"Removed `{entry['server_name']}` from Claude Code.")
                if entry.get("memory_server_name"):
                    _run_mcp_add(claude, ["mcp", "remove", "-s", entry["scope"], entry["memory_server_name"]], echo)
                manifest.pop("claude_code", None)
            code = code or rc
        else:
            echo("`claude` not found — remove manually:")
            echo(f"    claude mcp remove -s {entry['scope']} {entry['server_name']}")
            code = code or 1

    if manifest.get("claude_code_hooks"):
        rc = _remove_claude_hooks(manifest["claude_code_hooks"], echo)
        if rc == 0:
            manifest.pop("claude_code_hooks", None)
        code = code or rc

    for tool in ("gemini", "codex"):
        entry = manifest.get(tool)
        if not entry:
            continue
        binary = tool_bins.get(tool) or shutil.which(tool)
        if binary:
            rc = _run_mcp_add(binary, ["mcp", "remove", entry["server_name"]], echo)
            if rc == 0:
                echo(f"Removed `{entry['server_name']}` from {tool}.")
                if entry.get("memory_server_name"):
                    _run_mcp_add(binary, ["mcp", "remove", entry["memory_server_name"]], echo)
                manifest.pop(tool, None)
            code = code or rc
        else:
            echo(f"`{tool}` not found — remove manually: {tool} mcp remove {entry['server_name']}")
            code = code or 1

    if manifest.get("codex_hooks"):
        if _remove_codex_hooks(manifest["codex_hooks"], echo) == 0:
            manifest.pop("codex_hooks", None)

    if manifest.get("grok"):
        from hologram.harness import grok
        _, change = grok.remove(Path(manifest["grok"]["path"]).parent)
        echo(f"Grok: {change}.")
        manifest.pop("grok", None)

    if manifest.get("antigravity"):
        from hologram.harness import antigravity
        entry = manifest["antigravity"]
        _, change = antigravity.remove(Path(entry["path"]))
        echo(f"Antigravity: {change}.")
        binary = entry.get("agy") or shutil.which("agy")
        for name in entry.get("servers", []):
            if binary:
                _run_mcp_add(binary, ["mcp", "remove", name], echo)
            else:
                echo(f"`agy` not found — remove manually: agy mcp remove {name}")
        if entry.get("rules"):
            echo(f"Antigravity: {_antigravity_rules(_antigravity_settings_path(), add=False)}.")
        manifest.pop("antigravity", None)

    if manifest.get("hermes"):
        from hologram.harness import hermes
        entry = manifest["hermes"]
        _, change = hermes.remove(Path(entry["path"]).parent)
        echo(f"Hermes: {change}.")
        binary = entry.get("hermes") or shutil.which("hermes")
        if binary:
            prev = entry.get("previous_provider")
            _hermes_config(binary, ["set", "memory.provider", prev] if prev else ["unset", "memory.provider"])
            _hermes_config(binary, ["unset", "memory.hologram.command"])
        else:
            echo("`hermes` not found — reset memory.provider in ~/.hermes/config.yaml yourself")
        manifest.pop("hermes", None)

    _write_manifest(manifest)

    if purge and code == 0:
        base = _manifest_path().parent
        shutil.rmtree(base, ignore_errors=True)
        echo(f"Removed {base}.")

    if code == 0:
        echo("Uninstall complete. Per-project .hologram/ state is untouched (yours).")
    return code
