"""Hologram memory provider for Hermes Agent — the thin shim.

Every decision lives in the installed `hologram` package; this file only relays. It keeps one warm
`hologram hook hermes serve` worker per Hermes process (JSON lines over stdin/stdout), so the
expensive loads (the memory index, the embedder) are paid once per session instead of once per
prompt; when the worker cannot run it falls back to one-shot calls.

  prefetch            → the [HOLOGRAM] layer and the graph's line for this turn
  system_prompt_block → the graph's brief (fetched once per session)
  sync_turn           → the turn's messages, so the files it touched are reinforced
  recall_status       → the status line Hermes shows the person after each prefetch

Works with the free `hologram-cognitive` (the working set) and with Hologram Pro (the graph,
guards, board and memory too); the installed `hologram` says which. Anything about Pro is shown
to the person (the status line, once per session) and never put into the model's context.

The hologram command is found in order: `memory.hologram.command` in ~/.hermes/config.yaml
(a string, shell-split), the HOLOGRAM_CMD environment variable, `hologram` on PATH.
State stays in each project's own .hologram/ — nothing is written under $HERMES_HOME, and the
hook path makes no network calls.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import threading

from agent.memory_provider import MemoryProvider, spawn_context_thread

try:
    from agent.memory_provider import RecallStatus
except ImportError:  # older Hermes: no recall indicator
    RecallStatus = None

logger = logging.getLogger(__name__)

PRO_URL = 'hologram-pro.dev'
_FIRST_TIMEOUT_S = 20      # the first call loads the embedder
_TIMEOUT_S = 8
_ONE_SHOT_TIMEOUT_S = 12
_MAX_WORKER_FAILURES = 3


def _configured_command() -> list[str]:
    try:
        from hermes_cli.config import load_config_readonly
        block = load_config_readonly().get('memory', {}).get('hologram', {})
        if isinstance(block, dict) and isinstance(block.get('command'), str) and block['command']:
            return shlex.split(block['command'])
    except Exception:
        pass
    env = os.environ.get('HOLOGRAM_CMD')
    if env:
        return shlex.split(env)
    found = shutil.which('hologram')
    return [found] if found else []


class _Worker:
    """One `hologram hook hermes serve` process, one request at a time. A timeout kills it (a late
    answer would desynchronize the stream); a worker that keeps failing is given up on."""

    _TIMED_OUT = object()

    def __init__(self, cmd: list[str]) -> None:
        self._cmd = cmd
        self._proc = None
        self._lock = threading.Lock()
        self._failures = 0
        self._answered = False

    def usable(self) -> bool:
        return os.name != 'nt' and bool(self._cmd) and self._failures < _MAX_WORKER_FAILURES

    def call(self, event: str, data: dict):
        """The answer's text; None when the worker could not run (fall back); _TIMED_OUT on timeout."""
        import select
        with self._lock:
            try:
                if self._proc is None or self._proc.poll() is not None:
                    self._proc = subprocess.Popen(
                        self._cmd + ['hook', 'hermes', 'serve'], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
                    self._answered = False
                self._proc.stdin.write(json.dumps({'event': event, 'data': data}, default=str) + '\n')
                self._proc.stdin.flush()
                timeout = _TIMEOUT_S if self._answered else _FIRST_TIMEOUT_S
                ready, _, _ = select.select([self._proc.stdout], [], [], timeout)
                if not ready:
                    self._fail()
                    return self._TIMED_OUT
                line = self._proc.stdout.readline()
                if not line:
                    raise EOFError('worker exited')
                answer = json.loads(line)
                self._failures, self._answered = 0, True
                return answer.get('text', '') if answer.get('ok') else ''
            except Exception as exc:
                logger.debug('hologram worker %s failed: %s', event, exc)
                self._fail()
                return None

    def _fail(self) -> None:
        self._failures += 1
        self.close()

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.stdin.close()
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


class HologramMemoryProvider(MemoryProvider):
    def __init__(self) -> None:
        self._cmd: list[str] = []
        self._worker: _Worker | None = None
        self._session_id = ''
        self._cwd = ''
        self._primary = True
        self._edition = ''
        self._brief: str | None = None
        self._last_files = 0
        self._pointed = False

    @property
    def name(self) -> str:
        return 'hologram'

    def is_available(self) -> bool:
        return bool(_configured_command())

    def unavailable_reason(self) -> str:
        return ("no hologram command found: install hologram-cognitive (free) or Hologram Pro, or set "
                "memory.hologram.command in ~/.hermes/config.yaml, or HOLOGRAM_CMD")

    def initialize(self, session_id: str, **kwargs) -> None:
        self._cmd = _configured_command()
        self._worker = _Worker(self._cmd)
        self._session_id = session_id
        self._cwd = str(kwargs.get('cwd') or os.getcwd())
        # Hermes's rule for providers: only the primary agent writes (subagents, cron, flush runs read).
        self._primary = kwargs.get('agent_context') in (None, '', 'primary')
        caps = self._call('capabilities', {})
        try:
            self._edition = json.loads(caps).get('edition', '') if caps else ''
        except ValueError:
            self._edition = ''

    def _call(self, event: str, payload: dict) -> str:
        if not self._cmd:
            return ''
        data = {'session_id': self._session_id, 'cwd': self._cwd, **payload}
        if self._worker is not None and self._worker.usable():
            answer = self._worker.call(event, data)
            if answer is _Worker._TIMED_OUT:
                return ''
            if answer is not None:
                return answer
        return self._one_shot(event, data)

    def _one_shot(self, event: str, data: dict) -> str:
        try:
            done = subprocess.run(self._cmd + ['hook', 'hermes', event], input=json.dumps(data, default=str),
                                  capture_output=True, text=True, timeout=_ONE_SHOT_TIMEOUT_S)
            return done.stdout.strip() if done.returncode == 0 else ''
        except Exception as exc:
            logger.debug('hologram %s failed: %s', event, exc)
            return ''

    def system_prompt_block(self) -> str:
        if self._brief is None:
            self._brief = self._call('brief', {})
        return self._brief

    def prefetch(self, query: str, *, session_id: str = '') -> str:
        text = self._call('prefetch', {'prompt': query})
        self._last_files = len(re.findall(r'(?m)^- \S', text.split('MEMORIES', 1)[0])) if text else 0
        return text

    def recall_status(self):
        if RecallStatus is None or not self._last_files:
            return None
        label = f'Hologram · {self._last_files} files'
        if self._edition == 'core':
            label = f'Hologram core · {self._last_files} files'
            if not self._pointed:
                self._pointed = True
                label += f' (graph, guards, board, memory: {PRO_URL})'
        return RecallStatus(provider_label=label, count=0)

    def sync_turn(self, user_content: str, assistant_content: str, *,
                  session_id: str = '', messages=None) -> None:
        if not self._primary:
            return
        payload = {'user': user_content, 'assistant': assistant_content, 'messages': messages or []}
        spawn_context_thread(lambda: self._call('sync', payload), name='hologram-sync').start()

    def get_tool_schemas(self) -> list[dict]:
        return []

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        return ''

    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.close()

    def get_config_schema(self) -> list[dict]:
        return [{'key': 'command', 'description': "the hologram CLI (e.g. 'hologram' or a venv's "
                                                  'python -m hologram.cli)', 'required': False}]

    def save_config(self, values: dict, hermes_home: str) -> None:
        command = (values or {}).get('command')
        if not command:
            return
        try:
            from hermes_cli.config import save_config
            save_config({'memory': {'hologram': {'command': command}}}, merge_existing=True)
        except Exception as exc:
            logger.debug('hologram save_config failed: %s', exc)


def register(ctx) -> None:
    ctx.register_memory_provider(HologramMemoryProvider())
