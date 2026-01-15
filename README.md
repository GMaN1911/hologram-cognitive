# hologram-cognitive

Pressure-based context routing with lighthouse resurrection for LLMs.

**Portable AI working memory that travels between Claude.ai, Claude Code, ChatGPT, and any LLM platform.**

## Installation

```bash
pip install hologram-cognitive
```

## Quick Start

### One-liner routing
```python
import hologram

ctx = hologram.route('.claude', "What's the T3 architecture?")
print(ctx['injection'])  # Ready for your prompt
```

### Session-based (multi-turn)
```python
import hologram

session = hologram.Session('.claude')

# Each conversation turn
result = session.turn("Let's design a drone swarm")
# result.injection contains relevant context from memory

# Write important things to memory
session.note(
    "Drone Architecture Decision",
    "Using ESP-NOW for pressure propagation between units",
    links=['[[t3-overview.md]]', '[[projects/drone-swarm.md]]']
)

session.save()
```

### CLI
```bash
# Route a message
hologram route .claude "What about the T3 architecture?"

# Check memory status  
hologram status .claude

# Write a note
hologram note .claude "Meeting Notes" "Discussed X, Y, Z" -l t3-overview.md

# Initialize new project
hologram init ./my-project/.claude

# Export for transfer
hologram export .claude memory-backup.tar.gz
```

## How It Works

### Pressure-Based Routing
Unlike RAG (similarity-based retrieval), hologram-cognitive uses **pressure dynamics**:
- Files have pressure (0.0 - 1.0)
- Relevant files activate and gain pressure
- Pressure propagates along DAG edges (from `[[wiki-links]]`)
- Inactive files decay over time
- **Lighthouse resurrection**: Cold files periodically resurface (spaced repetition)

### Tiered Injection
- 🔥 **CRITICAL** (≥0.8): Full content injected
- ⭐ **HIGH** (≥0.5): Headers + summary
- 📋 **MEDIUM** (≥0.2): Listed only  
- ❄️ **COLD** (<0.2): Waiting for resurrection

### DAG Structure
Link files with `[[wiki-links]]` in your markdown:
```markdown
# My Project

This builds on [[t3-overview.md]] and relates to [[other-project.md]].
```

Links are auto-discovered. Structure emerges from content.

## File Structure

```
your-project/
├── .claude/
│   ├── MEMORY.md              # Instructions for LLMs (optional)
│   ├── hologram_state.json    # Pressure state (auto-generated)
│   ├── hologram_history.jsonl # Turn history (auto-generated)
│   ├── t3-overview.md         # Your knowledge files
│   ├── projects/
│   │   └── drone-swarm.md
│   └── sessions/
│       └── 2025-01-15-notes.md
└── CLAUDE.md                  # Claude Code instructions (optional)
```

## Cross-Platform Portability

The `.claude/` folder works everywhere:
- **Claude.ai**: Upload folder, instant context
- **Claude Code**: Drop in project root
- **ChatGPT**: Upload to sandbox
- **Local/API**: Direct Python integration

Export → Transfer → Import. Memory travels with you.

## API Reference

### `hologram.route(claude_dir, message)`
One-shot routing. Returns dict with `injection`, `hot`, `warm`, `cold`, `activated`.

### `hologram.Session(claude_dir)`
Session manager for multi-turn conversations.

**Methods:**
- `.turn(message)` → `TurnResult` with injection and metadata
- `.note(title, body, links=[])` → Write memory note
- `.save()` → Persist state to disk
- `.status()` → Current memory statistics
- `.files_by_pressure(min=0.0)` → List files sorted by pressure

### `TurnResult`
- `.injection` - Formatted context string
- `.hot` - List of critical files
- `.warm` - List of high-priority files  
- `.cold` - List of inactive files
- `.activated` - Files activated this turn
- `.turn_number` - Current turn count

## Configuration

### MEMORY.md
Place a `MEMORY.md` in your `.claude/` folder with instructions for LLMs:
```markdown
# Memory System Active

Run `session.turn(message)` before each response.
Write notes for significant topics.
Save state after each turn.
```

### Pressure Tuning
```python
from hologram.pressure import PressureConfig

config = PressureConfig(
    activation_boost=0.6,         # Default: files reach HOT on first mention
    edge_flow_rate=0.15,          # Pressure propagation along DAG edges
    decay_rate=0.85,              # Decay multiplier per turn
    use_toroidal_decay=True,      # Enable lighthouse resurrection
    resurrection_threshold=0.05,  # When files are effectively dead
    resurrection_pressure=0.55,   # Resurrect to WARM tier
)
```

## Author

**Garret Sutherland**  
MirrorEthic LLC  
gsutherland@mirrorethic.com

## License

MIT
