# Integration with claude-cognitive Ecosystem

This guide explains how to use **hologram-cognitive** as the routing backend for **claude-cognitive** hooks.

## Overview

**claude-cognitive** provides the hook infrastructure for Claude Code:
- UserPromptSubmit hooks for context injection
- Pool coordinator for multi-instance coordination
- Usage tracking and analytics

**hologram-cognitive** provides the memory/routing engine:
- Pressure-based file activation
- DAG-aware co-activation
- Lighthouse resurrection
- State persistence

Together, they create a powerful working memory system for Claude Code.

## Architecture

```
User message in Claude Code
    ↓
claude-cognitive hook (UserPromptSubmit)
    ↓
hologram.claude_cognitive.HologramBackend
    ↓
hologram.Session.turn() [pressure routing]
    ↓
Formatted injection context
    ↓
Claude Code receives context
```

## Installation

### 1. Install Both Packages

```bash
# Install hologram-cognitive
pip install hologram-cognitive

# Install claude-cognitive scripts
cd ~
git clone https://github.com/GMaN1911/claude-cognitive.git .claude-cognitive
cp -r .claude-cognitive/scripts ~/.claude/scripts/
```

### 2. Choose Integration Method

You have two options:

#### Option A: Replace context-router-v2.py (Recommended)

Replace the existing routing logic entirely with hologram:

**~/.claude/hooks/user-prompt-submit.py:**
```python
#!/usr/bin/env python3
"""
UserPromptSubmit hook using hologram-cognitive backend.
Replaces context-router-v2.py completely.
"""
import sys
import json

# Import hologram backend
from hologram.claude_cognitive import HologramBackend

# Read stdin (claude-cognitive format)
try:
    data = json.load(sys.stdin)
    user_prompt = data.get('prompt', '')
except:
    user_prompt = sys.stdin.read().strip()

# Route through hologram
backend = HologramBackend(claude_dir='.claude', auto_save=True)
result = backend.route_message(user_prompt, return_format='claude-cognitive')

# Output injection
print(result['injection'])

# Optional: Log stats
print(f"# Turn {result['turn']}: {result['stats']['hot_count']} hot, "
      f"{result['stats']['warm_count']} warm, {result['stats']['cold_count']} cold",
      file=sys.stderr)
```

#### Option B: Use hologram alongside context-router-v2.py

Keep both systems and let them complement each other:

**~/.claude/hooks/user-prompt-submit.py:**
```python
#!/usr/bin/env python3
"""
Hybrid approach: Use both context-router-v2.py and hologram-cognitive.
"""
import sys
import json
import subprocess

# Read user prompt
data = json.load(sys.stdin)
user_prompt = data.get('prompt', '')

# 1. Run context-router-v2.py (existing logic)
result_router = subprocess.run(
    ['python3', os.path.expanduser('~/.claude/scripts/context-router-v2.py')],
    input=json.dumps(data),
    capture_output=True,
    text=True
)
router_injection = result_router.stdout

# 2. Run hologram-cognitive (add pressure-based memory)
from hologram.claude_cognitive import HologramBackend
backend = HologramBackend(claude_dir='.claude')
result_hologram = backend.route_message(user_prompt, return_format='hologram')

# 3. Combine both injections
combined = f"""{router_injection}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MEMORY CONTEXT (hologram-cognitive)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{result_hologram['injection']}
"""

print(combined)
```

## Migration from context-router-v2.py

If you have existing context-router-v2.py state, migrate it:

```bash
# Migrate attention scores to hologram pressure
python -m hologram.claude_cognitive migrate \
  --old-state ~/.claude/scripts/.context_router_state.json \
  --claude-dir .claude

# Output:
# {
#   "success": true,
#   "files_migrated": 42,
#   "old_format": "context-router-v2",
#   "new_format": "hologram-cognitive-v0.2.0",
#   "note": "Attention scores mapped 1:1 to pressure values"
# }
```

The migration maps attention scores 1:1 to pressure values since they use the same 0.0-1.0 scale and similar decay semantics.

## Configuration

### Hologram Pressure Settings

Configure pressure dynamics in your code:

```python
from hologram import Session
from hologram.pressure import PressureConfig

session = Session('.claude')

# Optional: Customize pressure configuration
from hologram.system import CognitiveSystem
system = CognitiveSystem(
    pressure_config=PressureConfig(
        activation_boost=0.4,      # HOT activation strength
        edge_flow_rate=0.15,       # Pressure flow along DAG edges
        decay_rate=0.85,           # Decay multiplier per turn
        use_toroidal_decay=True,   # Enable lighthouse resurrection
        resurrection_pressure=0.55 # Resurrect to WARM tier
    )
)
```

### claude-cognitive Settings

Keep your existing claude-cognitive settings for:
- Pool coordinator
- Usage tracking
- Instance coordination

These work alongside hologram without modification.

## Usage Examples

### Basic Usage

```bash
# Check hologram status
python -m hologram.claude_cognitive status --claude-dir .claude

# Test routing
echo "Tell me about the architecture" | \
  python -m hologram.claude_cognitive route --claude-dir .claude

# Output injection
python -m hologram.claude_cognitive route \
  --claude-dir .claude \
  --message "What's the T3 system?"
```

### Programmatic Usage

```python
from hologram.claude_cognitive import HologramBackend

# Create backend
backend = HologramBackend(claude_dir='.claude')

# Route message
result = backend.route_message("Tell me about the architecture")

# Access structured result
print(f"Turn: {result['turn']}")
print(f"HOT files: {result['stats']['hot_count']}")
print(f"Injection: {result['injection'][:200]}...")

# Get status
status = backend.get_status()
print(f"Total files: {status['files']}")
print(f"Current turn: {status['turn']}")
```

## Feature Comparison

| Feature | context-router-v2.py | hologram-cognitive |
|---------|---------------------|-------------------|
| Attention/Pressure dynamics | ✅ | ✅ |
| HOT/WARM/COLD tiers | ✅ | ✅ |
| File decay | ✅ | ✅ |
| Co-activation | ✅ | ✅ (via DAG) |
| State persistence | ✅ | ✅ |
| Wiki-link DAG | ❌ | ✅ |
| Lighthouse resurrection | ❌ | ✅ |
| Toroidal decay | ❌ | ✅ |
| Session API | ❌ | ✅ |
| CLI tool | ❌ | ✅ |
| Export/Import | ❌ | ✅ |
| Cross-platform | ❌ | ✅ |
| Note creation | ❌ | ✅ |

## Pool Coordinator Integration

hologram-cognitive works with claude-cognitive's pool coordinator:

**Example pool block with hologram stats:**
```pool
INSTANCE: A
ACTION: completed
TOPIC: refactored auth module
SUMMARY: Auth token refresh bug fixed, all tests passing
AFFECTS: authentication, api_client
BLOCKS: None

MEMORY: 3 hot files (auth.md, api.md, tokens.md), turn 47
```

You can query hologram state from pool scripts:

```python
from hologram import Session

session = Session('.claude')
status = session.status()

# Include in pool block
pool_block = f"""
INSTANCE: {os.getenv('CLAUDE_INSTANCE', 'unknown')}
...
MEMORY: {len(status['hot'])} hot files ({', '.join(status['hot'][:3])}), turn {status['turn']}
"""
```

## Usage Tracking

hologram-cognitive has built-in turn tracking. Integrate with claude-cognitive's usage tracker:

```python
# In your hook script
from hologram.claude_cognitive import HologramBackend

# Track hologram usage
backend = HologramBackend('.claude')
result = backend.route_message(user_prompt)

# Log to usage tracker
usage_data = {
    'turn': result['turn'],
    'hot_count': result['stats']['hot_count'],
    'warm_count': result['stats']['warm_count'],
    'injection_chars': result['stats']['injection_chars'],
    'backend': 'hologram-cognitive-v0.2.0'
}

# Pass to claude-cognitive's usage_tracker.py if desired
```

## Troubleshooting

### hologram not found

```bash
# Ensure hologram-cognitive is installed
pip install hologram-cognitive

# Or install from source
cd /path/to/hologram-cognitive-0.2.0-src
pip install -e .
```

### Import errors in hooks

```python
# Add to sys.path if needed
import sys
sys.path.insert(0, '/path/to/hologram-cognitive-0.2.0-src')
from hologram.claude_cognitive import HologramBackend
```

### State file conflicts

hologram and context-router use different state files:
- context-router: `~/.claude/scripts/.context_router_state.json`
- hologram: `.claude/hologram_state.json`

They don't conflict, but migrate if switching completely.

### Performance

hologram adds ~100-150ms overhead per message (routing + pressure updates).

For large codebases (100+ files), this is negligible compared to context-router's file scanning.

## Best Practices

1. **Start with hologram-only** (Option A) for simplicity
2. **Use DAG features** - Add `[[wiki-links]]` to connect files
3. **Create notes** - Use `hologram note` to save important decisions
4. **Export regularly** - Backup memory state with `hologram export`
5. **Monitor pressure** - Run `hologram status` occasionally to see what's hot
6. **Leverage lighthouse** - Let resurrection bring back forgotten context

## Complete Example Hook

**~/.claude/hooks/user-prompt-submit.py** (complete):

```python
#!/usr/bin/env python3
"""
Complete UserPromptSubmit hook using hologram-cognitive.

Features:
- Hologram backend for pressure routing
- JSON stdin/stdout (claude-cognitive format)
- Error handling with fallback
- Debug output to stderr
"""
import sys
import json
import traceback
from pathlib import Path

try:
    from hologram.claude_cognitive import HologramBackend

    # Read user prompt (claude-cognitive JSON format)
    try:
        data = json.load(sys.stdin)
        user_prompt = data.get('prompt', '')
    except:
        user_prompt = sys.stdin.read().strip()

    # Find .claude directory (project-local or cwd)
    claude_dir = Path.cwd() / '.claude'
    if not claude_dir.exists():
        # Fallback to parent directories
        for parent in Path.cwd().parents:
            test_dir = parent / '.claude'
            if test_dir.exists():
                claude_dir = test_dir
                break

    # Route through hologram
    backend = HologramBackend(claude_dir=str(claude_dir), auto_save=True)
    result = backend.route_message(user_prompt, return_format='claude-cognitive')

    # Output injection
    print(result['injection'])

    # Debug info to stderr
    print(f"[hologram] Turn {result['turn']}: {result['stats']['hot_count']} hot, "
          f"{result['stats']['warm_count']} warm, {result['stats']['cold_count']} cold "
          f"({result['stats']['injection_chars']:,} chars)",
          file=sys.stderr)

except Exception as e:
    # Fallback: Output error but don't break Claude Code
    print(f"# (Memory system unavailable: {e})", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    # Output minimal context so Claude can still function
    print("# Memory context unavailable this turn")
```

Make executable:
```bash
chmod +x ~/.claude/hooks/user-prompt-submit.py
```

## See Also

- [Claude Code Integration Guide](CLAUDE_CODE_INTEGRATION.md)
- [Session API Reference](README.md)
- [claude-cognitive documentation](https://github.com/GMaN1911/claude-cognitive)
