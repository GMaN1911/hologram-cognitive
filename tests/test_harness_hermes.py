"""Hermes through its memory-provider seat: the layer from `prefetch`, the brief from `brief`,
reinforcement from `sync` with the receipts read out of Hermes's own messages. The adapter is
shape-driven (path arguments and `command` arguments), never pinned to Hermes's tool names."""

import json
import os
import time
from pathlib import Path

import pytest

from hologram.harness import hermes


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
                                        'deploy.md': '# Deploy\ntunnels and service contracts\n',
                                        'notes.md': '# Notes\nmiscellaneous\n'}.items()):
        (root / 'docs' / name).write_text(text)
        os.utime(root / 'docs' / name, (now - age * 3600, now - age * 3600))
    (root / 'crg' / 'nodes' / 'p.inv.never-empty.toml').write_text(
        'id = "p.inv.never-empty"\ncreated = "2026-10-06"\ntype = "invariant"\nstatus = "CURRENT"\n'
        'claim = "Never empty."\nadjudicated_by = "garret"\n')
    (root / 'crg' / 'CURRENT.md').write_text('# generated\n')
    return root


def _data(root, **extra):
    return {'session_id': 'hermes-abc', 'cwd': str(root), **extra}


def test_prefetch_returns_the_layer_and_the_graphs_line(project):
    text = hermes.handle('prefetch', _data(project, prompt='how does pressure routing work'))
    assert text.startswith('[HOLOGRAM]') and '- docs/routing.md' in text
    from hologram.edition import EDITION
    assert ('\n\n[CRG] ' in text) == (EDITION == 'pro')   # the graph's line is Pro


@pytest.mark.skipif(__import__('hologram.edition', fromlist=['EDITION']).EDITION != 'pro', reason='a Pro feature')
def test_brief_is_the_sessions_graph_brief(project):
    text = hermes.handle('brief', _data(project))
    assert text and 'CRG' in text


def test_receipts_are_read_from_the_messages_by_shape():
    used, edited, commands = hermes.messages_turn([
        {'role': 'user', 'content': 'go'},
        {'role': 'assistant', 'tool_calls': [
            {'function': {'name': 'read_file', 'arguments': json.dumps({'path': '/p/docs/a.md'})}},
            {'function': {'name': 'terminal', 'arguments': json.dumps({'command': 'pytest -q'})}},
            {'function': {'name': 'write_file', 'arguments': json.dumps({'path': '/p/docs/c.md', 'content': 'x'})}},
            {'function': {'name': 'str_replace_file', 'arguments': {'file_path': '/p/docs/d.md'}}},
            {'function': {'name': 'search_files', 'arguments': json.dumps({'query': 'x'})}},
            {'function': {'name': 'broken', 'arguments': 'not json'}},
        ]},
        {'role': 'tool', 'content': 'done'},
        'not a dict',
    ])
    assert used == {'/p/docs/a.md'}
    assert edited == {'/p/docs/c.md', '/p/docs/d.md'}
    assert commands == ['pytest -q']


def test_sync_reinforces_what_the_messages_touched(project):
    state = lambda: json.loads((project / '.hologram' / 'hologram_state.json').read_text())['current_turn']
    hermes.handle('prefetch', _data(project, prompt='read the deploy doc'))
    before = state()
    messages = [{'role': 'assistant', 'tool_calls': [
        {'function': {'name': 'read_file', 'arguments': json.dumps({'path': str(project / 'docs' / 'deploy.md')})}}]}]
    assert hermes.handle('sync', _data(project, user='read the deploy doc', assistant='done',
                                       messages=messages)) is None
    assert state() == before + 1
    text = hermes.handle('prefetch', _data(project, prompt='read the deploy doc'))
    files = [l[2:].split(' [')[0] for l in text.splitlines() if l.startswith('- ')]
    from hologram.edition import EDITION
    if EDITION == 'pro':
        assert files[0] == 'docs/deploy.md'      # the reranker carries the session's touched docs
    else:
        assert 'docs/deploy.md' in files         # pressure alone: reinforced, ties broken by the engine


def test_outside_a_project_nothing_is_said_and_nothing_breaks(tmp_path):
    assert hermes.handle('prefetch', {'session_id': 's', 'cwd': '/nonexistent-xyz', 'prompt': 'x'}) is None
    assert hermes.main({'cwd': '/nonexistent-xyz', 'prompt': 'x'}, 'prefetch') == 0
    assert hermes.main({}, 'not-an-event') == 0


def test_install_writes_the_shim_and_remove_takes_it_back(tmp_path):
    plugins = tmp_path / 'plugins'
    dst, what = hermes.install(plugins)
    assert what.startswith('wrote')
    assert (dst / '__init__.py').read_text().startswith('"""Hologram memory provider for Hermes')
    assert 'name: hologram' in (dst / 'plugin.yaml').read_text()
    _, what = hermes.remove(plugins)
    assert what.startswith('removed') and not dst.exists()
    _, what = hermes.remove(plugins)
    assert what.startswith('nothing')


def test_the_worker_answers_one_line_per_request_and_survives_bad_ones(project):
    import io
    requests = '\n'.join([
        json.dumps({'event': 'capabilities'}),
        json.dumps({'event': 'prefetch', 'data': _data(project, prompt='how does pressure routing work')}),
        'not json',
        json.dumps({'event': 'nope', 'data': {}}),
        json.dumps({'event': 'prefetch', 'data': _data(project, prompt='read the deploy doc')}),
    ]) + '\n'
    out = io.StringIO()
    assert hermes.serve(io.StringIO(requests), out) == 0
    answers = [json.loads(l) for l in out.getvalue().splitlines()]
    assert len(answers) == 5
    assert json.loads(answers[0]['text'])['edition'] in ('pro', 'core')
    assert answers[1]['ok'] and answers[1]['text'].startswith('[HOLOGRAM]')
    assert not answers[2]['ok'] and not answers[3]['ok']
    assert answers[4]['ok'] and '- docs/' in answers[4]['text']


def _load_shim(monkeypatch):
    """The shim against a stand-in for Hermes's agent.memory_provider (the real one lives in
    Hermes's own environment)."""
    import importlib.util
    import sys
    import threading
    import types
    from dataclasses import dataclass

    fake = types.ModuleType('agent.memory_provider')

    class MemoryProvider:
        pass

    @dataclass
    class RecallStatus:
        provider_label: str
        count: int
        glyph: str = '*'

    fake.MemoryProvider = MemoryProvider
    fake.RecallStatus = RecallStatus
    fake.spawn_context_thread = lambda target, name='', daemon=True: threading.Thread(target=target, name=name, daemon=daemon)
    monkeypatch.setitem(sys.modules, 'agent', types.ModuleType('agent'))
    monkeypatch.setitem(sys.modules, 'agent.memory_provider', fake)
    path = Path(hermes.__file__).resolve().parent.parent / 'data' / 'hermes_plugin' / '__init__.py'
    spec = importlib.util.spec_from_file_location('hologram_hermes_shim', path)
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)
    return shim


def test_the_shim_routes_through_the_warm_worker_and_falls_back_to_one_shot(project, monkeypatch):
    import shlex
    import sys
    repo = Path(hermes.__file__).resolve().parent.parent.parent
    monkeypatch.setenv('PYTHONPATH', str(repo))
    monkeypatch.setenv('HOLOGRAM_CMD', f'{shlex.quote(sys.executable)} -m hologram.cli')
    shim = _load_shim(monkeypatch)
    provider = shim.HologramMemoryProvider()
    assert provider.is_available()
    provider.initialize('hermes-shim', cwd=str(project))
    try:
        assert provider._edition in ('pro', 'core')
        text = provider.prefetch('how does pressure routing work')
        assert text.startswith('[HOLOGRAM]') and provider._worker._answered
        status = provider.recall_status()
        assert status.provider_label.startswith('Hologram') and 'files' in status.provider_label
        assert 'hologram-pro.dev' not in text            # the pointer never enters the model's context
        provider._worker._failures = shim._MAX_WORKER_FAILURES   # the worker given up on: one-shot
        assert provider.prefetch('how does pressure routing work').startswith('[HOLOGRAM]')
    finally:
        provider.shutdown()


def test_subagents_read_but_never_write(project, monkeypatch):
    shim = _load_shim(monkeypatch)
    provider = shim.HologramMemoryProvider()
    provider._cmd = ['/nonexistent-hologram']
    provider._primary = False
    started = []
    monkeypatch.setattr(shim, 'spawn_context_thread', lambda *a, **k: started.append(1))
    provider.sync_turn('u', 'a', messages=[])
    assert started == []
