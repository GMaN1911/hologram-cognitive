# hologram-cognitive

Pressure-based context routing with attention basins and lighthouse resurrection for LLMs.

**Portable AI working memory that travels between Claude.ai, Claude Code, ChatGPT, and any LLM platform.**

## What's New in v0.3.0

- **Attention Basins**: Files that stay HOT build "basin depth" and decay slower
- **Turn-State Inheritance**: Pressure carries forward between turns at 60% rate
- **Tension Tracking**: Cognitive load from unresolved questions accumulates
- **Auto-Crystallization**: Session notes generated automatically when attention clusters resolve
- **Project-First Routing**: Hook finds project `.claude/` before falling back to global

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

### Session-based (multi-turn with v0.3.0 features)
```python
import hologram

session = hologram.Session('.claude')

# Each conversation turn - now tracks tension and clusters
result = session.turn("Let's design a drone swarm")
print(f"Tension: {result.tension}")
print(f"Cluster size: {result.cluster_size}")

# Check if crystallization was triggered
if result.resolved:
    print(f"Topic resolved: {result.resolution_type}")

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

# Check memory status (now includes basins and tension)
hologram status .claude

# View turn state (attention cluster, tension, basins)
hologram state .claude

# Manually crystallize current session
hologram crystallize .claude

# List recent session notes
hologram sessions .claude

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

### Attention Basins (v0.3.0)
Files that remain HOT across multiple turns develop "basin depth":
```
Turn 1: pipeline.md HOT → basin_depth = 1.0
Turn 2: pipeline.md HOT → basin_depth = 1.3
Turn 3: pipeline.md HOT → basin_depth = 1.6
Turn 4: pipeline.md HOT → basin_depth = 1.9
Turn 5: pipeline.md HOT → basin_depth = 2.2 (max ~2.5)
```

Deeper basins = slower decay. Files you consistently use become "sticky" and resist falling to COLD.

### Turn-State Inheritance (v0.3.0)
Pressure carries forward between turns:
```python
# Turn N: file has pressure 0.6
# Turn N+1: file inherits 0.6 × 0.6 = 0.36 (above threshold)
# Turn N+2: file inherits 0.36 × 0.6 = 0.22 (fading)
```

Only files with pressure > 0.3 inherit. This creates smooth attention transitions instead of jarring context switches.

### Tension Tracking (v0.3.0)
Unresolved cognitive load accumulates:
```python
result = session.turn("How does the pipeline work?")
# tension = 0.15 (question detected)

result = session.turn("What about error handling?")
# tension = 0.30 (more questions accumulate)

result = session.turn("Got it, thanks!")
# tension = 0.0 (resolved, decayed)
```

Tension sources are tracked and can trigger crystallization.

### Auto-Crystallization (v0.3.0)
When attention clusters resolve, session notes are automatically generated:

**Trigger conditions:**
1. Resolution detected (completion phrases, topic change)
2. Cluster sustained for 3+ turns
3. Peak pressure exceeded 0.6

**Output:** `.claude/sessions/YYYYMMDD_HHMMSS_topic-slug.md`

### Tiered Injection
- **HOT** (pressure > 0.8): Full content injected
- **WARM** (0.2 < pressure ≤ 0.8): Summary injected
- **COLD** (pressure ≤ 0.2): Available for resurrection

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
│   ├── turn_state.json        # v0.3.0: Attention cluster state
│   ├── t3-overview.md         # Your knowledge files
│   ├── projects/
│   │   └── drone-swarm.md
│   └── sessions/              # v0.3.0: Auto-crystallized notes
│       └── 20260118_143022_pipeline-architecture.md
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
- `.turn(message)` → `TurnResult` with injection and v0.3.0 state
- `.note(title, body, links=[])` → Write memory note
- `.crystallize()` → Manually trigger crystallization
- `.sessions()` → List recent session notes
- `.save()` → Persist state to disk
- `.status()` → Current memory statistics
- `.files_by_pressure(min=0.0)` → List files sorted by pressure

**Properties:**
- `.turn_state` → Current TurnState (cluster, tension, inheritance)
- `.last_crystallization` → Most recent crystallized session note

### `TurnResult` (v0.3.0 enhanced)
- `.injection` - Formatted context string
- `.hot` - List of critical files
- `.warm` - List of high-priority files
- `.cold` - List of inactive files
- `.activated` - Files activated this turn
- `.turn_number` - Current turn count
- `.tension` - Current cognitive tension (0.0-1.0)
- `.cluster_size` - Files in attention cluster
- `.resolved` - Whether resolution was detected
- `.resolution_type` - Type of resolution (completion, topic_change, None)

### `TurnState` (v0.3.0)
```python
@dataclass
class TurnState:
    turn: int
    attention_cluster: Set[str]      # Files co-activated across turns
    cluster_formation_turn: int      # When cluster formed
    cluster_sustained_turns: int     # How long cluster held
    pressure_inheritance: Dict[str, float]  # Inherited pressures
    unresolved_tension: float        # Accumulated cognitive load
    tension_sources: List[str]       # What's causing tension
    last_resolution_turn: int        # When last resolved
    pending_crystallization: bool    # Ready to crystallize?
```

## Configuration

### Pressure Tuning
```python
from hologram.pressure import PressureConfig

config = PressureConfig(
    # Activation
    activation_boost=0.6,         # Files reach HOT on first mention
    edge_flow_rate=0.15,          # Pressure propagation along DAG edges

    # Decay
    decay_rate=0.85,              # Decay multiplier per turn

    # Basin dynamics (v0.3.0)
    max_basin_depth_turns=5,      # Turns to reach max basin
    basin_depth_multiplier=1.5,   # Max basin depth factor
    basin_cooldown_rate=2,        # Basin decay when not HOT

    # Lighthouse resurrection
    use_toroidal_decay=True,      # Enable lighthouse
    resurrection_threshold=0.05,  # When files are effectively dead
    resurrection_pressure=0.55,   # Resurrect to WARM tier
    resurrection_cooldown=100,    # Turns between lighthouse sweeps
)
```

### Turn-State Config (v0.3.0)
```python
from hologram.turn_state import TurnStateConfig

config = TurnStateConfig(
    enable_inheritance=True,      # Enable pressure inheritance
    inheritance_rate=0.6,         # 60% pressure carries forward
    inheritance_threshold=0.3,    # Min pressure to inherit
    tension_accumulation=0.15,    # Tension per unresolved signal
    tension_decay=0.3,            # Tension decay on resolution
    cluster_stability_turns=3,    # Turns before cluster is "stable"
    min_cluster_size=2,           # Min files for valid cluster
)
```

### Crystallization Config (v0.3.0)
```python
from hologram.crystallize import CrystallizeConfig

config = CrystallizeConfig(
    min_cluster_size=2,           # Min files to crystallize
    min_sustained_turns=3,        # Min turns cluster held
    min_peak_pressure=0.6,        # Min pressure reached
    sessions_subdir='sessions',   # Output directory
    enable_auto_linking=True,     # Convert names to [[wiki-links]]
)
```

## Claude Code Hook

For Claude Code integration, add to `~/.config/claude-code/hooks.json`:

```json
{
  "hooks": [
    {
      "matcher": "UserPromptSubmit",
      "hooks": [
        {
          "type": "command",
          "command": "python3 ~/.claude/hologram_hook.py"
        }
      ]
    }
  ]
}
```

The hook automatically routes queries and injects relevant context. v0.3.0 hook uses project-first routing (finds project `.claude/` before falling back to global `~/.claude`).

## Performance

### Batch Loading
v0.3.0 uses batch DAG building for O(n²) complexity instead of O(n³):
```
First load (183 files): ~5s
Subsequent loads (cached): ~0.3s
```

### DAG Caching
DAG relationships are cached with signature-based invalidation. Cache is automatically rebuilt when files change.

## Author

**Garret Sutherland**
MirrorEthic LLC
gsutherland@mirrorethic.com

## License

MIT
