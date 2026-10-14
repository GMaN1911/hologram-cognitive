"""The Claude Code entries: added once, replaced on upgrade, removed on uninstall, nobody else's touched."""

import json

import pytest

from hologram.harness import claude_code
from hologram import hook


def test_every_event_the_entry_handles_has_a_hook_and_nothing_else_is_disturbed():
    theirs = {'type': 'command', 'command': 'python3 ~/.claude/hooks/lattice.py'}
    settings = {'env': {'X': '1'}, 'hooks': {'UserPromptSubmit': [{'hooks': [theirs]}],
                                             'Stop': [{'hooks': [{'type': 'command', 'command': 'hologram-hook-observe', 'timeout': 30}]}]}}
    installed, changes = claude_code.install(settings, command='hologram hook')
    from hologram.edition import EDITION
    assert set(claude_code.HOOKS) == set(hook.EVENTS.values()) == {'SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop'}
    # the core registers only the events it answers (no graph brief, no guards)
    ours = set(claude_code.HOOKS) if EDITION == 'pro' else {'UserPromptSubmit', 'Stop'}
    assert set(installed['hooks']) == ours
    assert {c.split(' ')[1] for c in changes if ' hook ' in c} == ours
    assert theirs in installed['hooks']['UserPromptSubmit'][0]['hooks']
    assert installed['env']['X'] == '1' and settings['hooks']['Stop'][0]['hooks'][0]['command'] == 'hologram-hook-observe'
    assert any(c.startswith('replace Stop hook `hologram-hook-observe`') for c in changes)   # the 0.4 entry is gone
    assert [h['command'] for g in installed['hooks']['Stop'] for h in g['hooks']] == ['hologram hook stop']
    commands = [h['command'] for g in installed['hooks']['UserPromptSubmit'] for h in g['hooks']]
    assert commands == ['python3 ~/.claude/hooks/lattice.py', 'hologram hook prompt']
    # every command is an event the entry handles
    for event, groups in claude_code.HOOKS.items():
        for g in groups:
            for h in g['hooks']:
                assert h['command'].split()[-1] in hook.EVENTS and hook.EVENTS[h['command'].split()[-1]] == event

    again, changes = claude_code.install(installed, command='hologram hook')
    assert again == installed and all(c.startswith('replace') for c in changes)

    removed, changes = claude_code.remove(installed)
    assert removed['hooks'] == {'UserPromptSubmit': [{'hooks': [theirs]}]} and sum(' hook ' in c for c in changes) == len(ours)
    assert claude_code.remove({'env': {}})[0] == {'env': {}}
    json.dumps(installed)   # what the caller writes


@pytest.mark.skipif(__import__('hologram.edition', fromlist=['EDITION']).EDITION != 'pro', reason='a Pro feature')
def test_the_mod_is_registered_beside_other_mods_and_removed_alone(tmp_path):
    mod = tmp_path / 'wheel' / 'hologram' / 'mods' / 'claude-code'
    settings = {'env': {'CLAUDE_CODE_PLUGIN_DIRS': '/home/me/openclaw-cognitive/plugins/mesh', 'HOLOGRAM_TYPED': '1'}}
    installed, changes = claude_code.install(settings, mod, command='hologram hook')
    assert installed['env']['CLAUDE_CODE_PLUGIN_DIRS'] == f'/home/me/openclaw-cognitive/plugins/mesh:{mod}'
    assert installed['env']['HOLOGRAM_TYPED'] == '1' and any('add the Hologram mod' in c for c in changes)
    again, changes = claude_code.install(installed, mod, command='hologram hook')   # idempotent: replaced, not doubled
    assert again['env']['CLAUDE_CODE_PLUGIN_DIRS'] == installed['env']['CLAUDE_CODE_PLUGIN_DIRS']
    assert sum('Hologram mod' in c for c in changes) == 1 and changes[-1].startswith('replace the Hologram mod')
    # the research checkout's spelling counts as ours too
    old = {'env': {'CLAUDE_CODE_PLUGIN_DIRS': '/home/me/hologram-mesh/mods/hologram:/home/me/openclaw-cognitive/plugins/mesh'}}
    removed, changes = claude_code.remove(old)
    assert removed == {'env': {'CLAUDE_CODE_PLUGIN_DIRS': '/home/me/openclaw-cognitive/plugins/mesh'}}
    assert claude_code.remove({'env': {'CLAUDE_CODE_PLUGIN_DIRS': str(mod)}})[0] == {}
    # on this checkout the mod is where the research tree keeps it
    found = claude_code.mod_dir()
    assert found is not None and found.name == 'hologram' and (found / 'hooks' / 'register.tsx').is_file()


def test_the_entries_carry_this_installations_executable_by_default(monkeypatch, tmp_path):
    """A harness's shell rarely has a venv's bin on PATH: the entry names the executable."""
    import sys
    from hologram import harness
    exe = tmp_path / 'bin' / 'hologram'
    exe.parent.mkdir()
    exe.write_text('#!/bin/sh\n')
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'bin' / 'python3'))
    assert harness.executable('hologram') == str(exe)
    installed, _ = claude_code.install({}, mod=None)
    assert [h['command'] for h in installed['hooks']['Stop'][0]['hooks']] == [f'{exe} hook stop']
    assert claude_code.remove(installed)[0].get('hooks', {}) == {}       # still recognised as ours
