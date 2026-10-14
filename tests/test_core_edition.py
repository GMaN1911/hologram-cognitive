"""The core edition (hologram-cognitive) is the same code with the Pro modules absent: a prompt
gets the working set and nothing that needs Pro, guards never refuse, the other harnesses' hooks
answer without blocking, and the pointer to Pro reaches the person, never the model. Each test
runs here with EDITION flipped to 'core', and natively in the exported core."""

import io
import json
import os
import sys
import time
from contextlib import redirect_stderr, redirect_stdout

import pytest

from hologram import edition, hook
from hologram.harness import hermes


@pytest.fixture
def core(monkeypatch):
    monkeypatch.setattr(edition, 'EDITION', 'core')


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('CRG_MESH_DIR', str(tmp_path / 'mesh-registry'))
    monkeypatch.setenv('HOLOGRAM_CORTEX_RECALL_CLI', '/nonexistent')
    monkeypatch.setenv('HOLOGRAM_MEMORY_LIMIT', '0')
    for key in ('CLAUDE_PROJECT_DIR', 'HOLOGRAM_CRG_EMIT', 'HOLOGRAM_CRG_ROOT', 'HOLOGRAM_RERANK'):
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / 'home' / 'proj'
    (root / '.hologram').mkdir(parents=True)
    (root / 'docs').mkdir()
    (root / 'crg' / 'nodes').mkdir(parents=True)
    now = time.time()
    for age, (name, text) in enumerate({'routing.md': '# Routing\nhow pressure routing decides what a prompt gets\n',
                                        'deploy.md': '# Deploy\ntunnels and service contracts\n'}.items()):
        (root / 'docs' / name).write_text(text)
        os.utime(root / 'docs' / name, (now - age * 3600, now - age * 3600))
    (root / 'crg' / 'nodes' / 'p.inv.never-empty.toml').write_text(
        'id = "p.inv.never-empty"\ncreated = "2026-10-06"\ntype = "invariant"\nstatus = "CURRENT"\n'
        'claim = "Never empty."\nadjudicated_by = "garret"\n')
    (root / 'crg' / 'CURRENT.md').write_text('# generated\n')
    (root / 'crg' / 'GUARDS.json').write_text(json.dumps([
        {'node': 'p.inv.graph-is-the-source', 'name': 'graph-is-the-source', 'claim': 'CURRENT.md is generated.',
         'kind': 'path', 'tools': ['Edit', 'Write', 'NotebookEdit'], 'is': 'crg/CURRENT.md',
         'on_violation': 'deny', 'fix': 'Edit the nodes, then regenerate.'}]))
    return root


def _data(root, **extra):
    return {'session_id': 'core-1', 'cwd': str(root), **extra}


def test_pro_modules_are_absent_in_the_core(core):
    assert edition.pro('crg') is None and edition.pro('board') is None
    assert 'hologram-pro.dev' in edition.pro_only('The blackboard')


def test_a_prompt_gets_the_working_set_and_nothing_that_needs_pro(core, project):
    text = hook.prompt_context(_data(project, prompt='how does pressure routing work'))
    assert text.startswith('[HOLOGRAM]') and '- docs/routing.md' in text
    assert '[CRG]' not in text and '[BOARD]' not in text and 'MEMORIES' not in text
    assert 'hologram-pro.dev' not in text          # the pointer never reaches the model


def test_session_start_and_guards_are_silent_in_the_core(core, project):
    assert hook.session_context(_data(project)) == ''
    edit = _data(project, tool_name='Edit', tool_input={'file_path': str(project / 'crg' / 'CURRENT.md')})
    assert hook.pretool_refusal(edit) is None


def test_the_other_harnesses_answer_without_blocking(core):
    for event in (hook.CODEX, hook.GROK):
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            assert hook.run(event, {}) == 0
        assert 'hologram-pro.dev' in err.getvalue() and out.getvalue() == ''
    out = io.StringIO()
    with redirect_stderr(io.StringIO()), redirect_stdout(out):
        assert hook.run(hook.ANTIGRAVITY, {}, subevent='PreToolUse') == 0
    assert json.loads(out.getvalue()) == {'decision': 'allow'}   # in agy, printing nothing denies


def test_hermes_says_core_and_offers_no_brief(core, project):
    caps = hermes.capabilities()
    assert caps['edition'] == 'core' and 'brief' not in caps['features']
    assert hermes.handle('brief', _data(project)) is None
    assert hermes.handle('prefetch', _data(project, prompt='how does pressure routing work')).startswith('[HOLOGRAM]')


@pytest.mark.parametrize('argv', [['board', 'read'], ['crg', 'check'], ['license', 'status'], ['upgrade'],
                                  ['install', 'grok']])
def test_pro_commands_point_to_pro(core, monkeypatch, argv):
    from hologram import cli
    monkeypatch.setattr(sys, 'argv', ['hologram', *argv])
    out = io.StringIO()
    with redirect_stdout(out), pytest.raises(SystemExit) as done:
        cli.main()
    assert done.value.code == 0 and 'hologram-pro.dev' in out.getvalue()


def test_claude_code_gets_only_the_hooks_the_core_answers(core):
    from hologram.harness import claude_code
    assert set(claude_code.hooks('hologram hook')) == {'UserPromptSubmit', 'Stop'}
    settings, changes = claude_code.install({}, command='hologram hook')
    assert set(settings['hooks']) == {'UserPromptSubmit', 'Stop'} and changes
