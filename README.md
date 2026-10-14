# hologram-cognitive

**Every prompt arrives with the few files that matter for what your session is doing right now.**

Hologram watches what your coding agent actually reads and edits, keeps a pressure score per file,
and puts the project's current working set in front of the model on every prompt — so a fresh
session stops re-deriving your project from scratch and a long one stays on the right files.

This is the free, MIT-licensed routing engine. It runs locally, makes no network calls, and keeps
its state in your project.

## Install

Python 3.11 or newer.

```bash
pipx install hologram-cognitive
cd your-project
hologram init .
```

Then connect your agent:

```bash
hologram install claude-code   # Claude Code: a prompt hook and an end-of-turn hook
hologram install hermes        # Hermes Agent: Hologram as its memory provider
```

Each command prints every change before making it and asks first. `hologram uninstall` reverses
all of them.

## What a prompt gets

```
[HOLOGRAM] (cap=7000B, schema=t3-ctx/v1, project=your-project)
  tier_counts: hot=1 warm=0 cold=1 (working set 2: 1 by pressure, 1 by recency)
- docs/deploy.md [legacy/unknown]
  preview: # Deploy tunnels and service contracts
- docs/routing.md [legacy/unknown]
  preview: # Routing how pressure routing decides
  bytes_used: 336/7000 | typed=0 legacy=2 mem=0
```

(Real output from a two-doc project; `[legacy/unknown]` means the file has no typed frontmatter.)

About 1 KB per file — a preview and the excerpts around what the prompt mentions — under a
7,000-byte cap.

## How it chooses

- **Activation.** Words in the prompt activate at most 8 files. Stop-words and words found in most
  files are ignored, matches are whole-word, and rarer words count for more.
- **Pressure.** Activated files gain pressure; everything else decays. Total pressure is capped at
  10 whatever the project's size, taken equally from every file, so the files that matter keep
  their lead and the tail drops out.
- **The working set.** Every prompt gets the top 6 files by pressure, the next 10 by name, and up
  to 3 recently modified docs when too few files hold pressure. It is never empty.
- **Learning.** At the end of each turn the files the session actually read or edited are
  reinforced, and each file's boost and decay adapt to how often it is used when it is activated.
- **Fixtures and test data** are indexed but demoted, unless the prompt names them.

## What it touches

- `your-project/.hologram/` — the routing state and its history. Delete it to start over.
- Claude Code: the hook entries in `~/.claude/settings.json` (a backup is written first).
- Hermes Agent: `~/.hermes/plugins/hologram/` and `memory.provider` / `memory.hologram.command` in
  Hermes's config, set through `hermes config` (the provider you had is restored on uninstall).

No network calls, no telemetry.

## Free and Pro

| | hologram-cognitive (free, MIT) | Hologram Pro |
|---|---|---|
| The working set on every prompt, learned from use | ✓ | ✓ |
| Claude Code hooks, Hermes Agent provider | ✓ | ✓ |
| The project's causal graph: what is current, what failed and why, delivered at session start and on every prompt | | ✓ |
| Guards: an adjudicated rule refuses an edit or command before it runs | | ✓ |
| Project memory (decisions and failed approaches, recalled with the working set) | | ✓ |
| The blackboard: sessions on one machine — any vendor — leave each other notes | | ✓ |
| A reranker over prompt-time signals | | ✓ |
| Codex, Grok and Antigravity; MCP servers for Cursor, Gemini and chat clients | | ✓ |

Hologram Pro: **https://hologram-pro.dev**. Upgrading replaces this package (Pro includes
everything here); your projects' routing state carries over.

## Upgrading from 0.3

0.4 routes your project's own files rather than a `.claude/` notes directory, and keeps its state in
`.hologram/`. Your old `.claude/` directory is left exactly as it was and is no longer routed —
move any notes you want routed into the project (for example `docs/`). `hologram init .` once in
each project. 0.4 needs Python 3.11 or newer.

## License

MIT — see [LICENSE](LICENSE).
