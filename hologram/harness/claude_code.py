"""Claude Code: the hook entries in settings.json that route every event to `hologram hook`.

Claude Code reads `~/.claude/settings.json` (or a project's `.claude/settings.json`); each event
has a list of matcher groups, each group a list of hooks. The entries below are what Hologram
needs: the graph at a session start and again after a compaction, the working set and the
graph's line on every prompt, a guard check before a file or shell tool runs, and reinforcement
at the end of the turn. `install` and `remove` are pure: they return the changed settings and
say what changed, and the caller writes the file.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

COMMAND = 'hologram hook'
# The Claude Code mod: the status line, the /holo pane, /guard (the only way to waive an `ask`
# guard), and the graph's guards enforced on tool calls before they run. Claude Code loads it
# from the CLAUDE_CODE_PLUGIN_DIRS environment variable, a colon-separated list of mod
# directories, which settings.json `env` can set. In the research checkout it is
# mods/hologram; a wheel carries it at hologram/mods/claude-code.
PLUGIN_DIRS = 'CLAUDE_CODE_PLUGIN_DIRS'
MOD_DIR_NAMES = ('claude-code', 'hologram')
HOOKS: Dict[str, List[dict]] = {
    'SessionStart': [{'matcher': 'startup|resume|compact',
                      'hooks': [{'type': 'command', 'command': f'{COMMAND} session', 'timeout': 15}]}],
    'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': f'{COMMAND} prompt', 'timeout': 15}]}],
    'PreToolUse': [{'matcher': 'Edit|Write|NotebookEdit|Bash',
                    'hooks': [{'type': 'command', 'command': f'{COMMAND} pretool', 'timeout': 30}]}],
    'Stop': [{'hooks': [{'type': 'command', 'command': f'{COMMAND} stop', 'timeout': 30}]}],
}
# Entries this package has ever installed, including the 0.4 console scripts, so an upgrade
# replaces them and an uninstall removes them.
OURS = re.compile(r'^(?:\S*hologram hook \w+|\S*hologram-hook-(?:inject|observe))(?:\s|$)')


def ours(hook: dict) -> bool:
    return hook.get('type', 'command') == 'command' and bool(OURS.match(str(hook.get('command', ''))))


def mod_dir() -> Optional[Path]:
    """Where the mod is on this machine: in the wheel, else in the research checkout."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / 'mods' / 'claude-code', here.parents[2] / 'mods' / 'hologram'):
        if (candidate / 'hooks' / 'hooks.json').is_file():
            return candidate
    return None


def _our_mod(path: str) -> bool:
    parts = Path(path).parts
    return len(parts) >= 2 and parts[-2] == 'mods' and parts[-1] in MOD_DIR_NAMES


def remove(settings: dict) -> Tuple[dict, List[str]]:
    """The settings without any of our entries, and one line per removal."""
    out = dict(settings)
    hooks = {event: [dict(group) for group in groups] for event, groups in (settings.get('hooks') or {}).items()}
    changes = []
    for event, groups in list(hooks.items()):
        kept = []
        for group in groups:
            mine = [h for h in group.get('hooks', []) if ours(h)]
            if mine:
                changes.append(f"remove {event} hook `{mine[0]['command']}`")
            rest = [h for h in group.get('hooks', []) if not ours(h)]
            if rest:
                kept.append({**group, 'hooks': rest})
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if hooks:
        out['hooks'] = hooks
    else:
        out.pop('hooks', None)
    env = dict(settings.get('env') or {})
    dirs = [d for d in str(env.get(PLUGIN_DIRS, '')).split(':') if d]
    kept = [d for d in dirs if not _our_mod(d)]
    if len(kept) != len(dirs):
        changes.append(f'remove the Hologram mod from {PLUGIN_DIRS}')
        if kept:
            env[PLUGIN_DIRS] = ':'.join(kept)
        else:
            env.pop(PLUGIN_DIRS, None)
        if env:
            out['env'] = env
        else:
            out.pop('env', None)
    return out, changes


def hooks(command: str = COMMAND) -> Dict[str, List[dict]]:
    """The entries with the given `hologram hook` command (an absolute path at install time)."""
    from ..edition import EDITION
    # The core has no graph brief and no guards, so it registers only the events it answers:
    # a session-start or pre-tool hook would start a process (one per tool call) to say nothing.
    events = HOOKS if EDITION == 'pro' else {e: g for e, g in HOOKS.items() if e in ('UserPromptSubmit', 'Stop')}
    return {event: [dict(g, hooks=[dict(h, command=h['command'].replace(COMMAND, command, 1)) for h in g['hooks']])
                    for g in groups] for event, groups in events.items()}


def install(settings: dict, mod: Optional[Path] = None, command: Optional[str] = None) -> Tuple[dict, List[str]]:
    """The settings with our entries (older ones of ours replaced) and the mod registered, and
    one line per change. Other people's hooks and mods are left exactly where they are.
    `command` is the `hologram hook` to write: by default this installation's executable, so
    the entry works whatever PATH the harness's shell has."""
    from . import executable
    command = command or f"{executable('hologram')} hook"
    out, changes = remove(settings)
    changes = [c.replace('remove ', 'replace ') for c in changes]
    mod = mod or mod_dir()
    if mod is not None:
        env = dict(out.get('env') or {})
        dirs = [d for d in str(env.get(PLUGIN_DIRS, '')).split(':') if d]
        env[PLUGIN_DIRS] = ':'.join(dirs + [str(mod)])
        out['env'] = env
        if not any(c.startswith('replace the Hologram mod') for c in changes):
            changes.append(f'add the Hologram mod to {PLUGIN_DIRS} ({mod})')
    entries = dict(out.get('hooks') or {})
    for event, groups in hooks(command).items():
        entries[event] = list(entries.get(event, [])) + groups
        for group in groups:
            for hook in group['hooks']:
                if not any(c.startswith(f'replace {event} ') for c in changes):
                    changes.append(f"add {event} hook `{hook['command']}` (timeout {hook['timeout']}s)")
    out['hooks'] = entries
    return out, changes
