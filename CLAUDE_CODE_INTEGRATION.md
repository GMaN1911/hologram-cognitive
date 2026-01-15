# Claude Code Integration Guide

hologram-cognitive v0.2.0 integrates seamlessly with Claude Code through hooks that automatically inject memory context during conversations.

## Quick Setup

### 1. Create Hook Scripts

In your project's `.claude/hooks/` directory, create these hook files:

**`.claude/hooks/user-prompt-submit.py`** (Required - runs before each message):
```python
#!/usr/bin/env python3
"""Hook to inject memory context before each user message."""
import sys
import hologram.hooks

# Process user message through memory system
result = hologram.hooks.user_prompt_submit_hook()

# Output injection for Claude Code
if result.get('enabled') and result.get('injection'):
    print(result['injection'])
```

**`.claude/hooks/session-start.py`** (Optional - runs when session starts):
```python
#!/usr/bin/env python3
"""Hook to display memory status at session start."""
import hologram.hooks

# Load memory state and show status
result = hologram.hooks.session_start_hook()

# Output status for Claude Code
if result.get('enabled') and result.get('injection'):
    print(result['injection'])
```

### 2. Make Scripts Executable

```bash
chmod +x .claude/hooks/user-prompt-submit.py
chmod +x .claude/hooks/session-start.py
```

### 3. Configure Hook Execution

Add to your `.claude/config.json` (or Claude Code settings):

```json
{
  "hooks": {
    "session-start": {
      "command": ".claude/hooks/session-start.py",
      "inject": true
    },
    "user-prompt-submit": {
      "command": ".claude/hooks/user-prompt-submit.py",
      "inject": true,
      "pass_message": true
    }
  }
}
```

## How It Works

### Automatic Context Flow

```
User types message
    ↓
Claude Code calls user-prompt-submit hook
    ↓
Hook routes message through hologram.Session.turn()
    ↓
Pressure system activates relevant files
    ↓
Hook returns formatted injection context
    ↓
Claude Code injects context into prompt
    ↓
Claude processes message with memory context
```

### Memory Injection Format

The hook injects context in this format:

```
╔══ ATTENTION STATE [Turn 42] ══╗

║ 🔥 Hot: 3 │ 🌡️ Warm: 5 │ ❄️ Cold: 12 ║

║ Total chars: 8,421 / 25,000 ║

╚══════════════════════════════════════╝

=== ACTIVE MEMORY ===

## project-overview.md
[Full content of hot files...]

=== RELATED CONTEXT ===

## technical-details.md
[Headers from warm files...]

=== AVAILABLE (inactive) ===
readme.md, changelog.md, archive.md, ...
```

## Advanced Usage

### Programmatic Hook Usage

```python
import hologram.hooks

# Manual hook invocation
result = hologram.hooks.user_prompt_submit_hook(
    user_message="Tell me about the lighthouse feature",
    claude_dir="/path/to/.claude",
    max_injection_chars=20000
)

print(result['injection'])
print(f"Turn: {result['turn']}")
print(f"Hot files: {result['hot']}")
```

### Custom Hook Scripts

You can customize the hook behavior:

```python
#!/usr/bin/env python3
"""Custom hook with filtering."""
import hologram.hooks

# Get memory context
result = hologram.hooks.user_prompt_submit_hook()

if result.get('enabled'):
    # Custom filtering logic
    injection = result['injection']

    # Only inject if hot files exist
    if len(result.get('hot', [])) > 0:
        print(injection)
    else:
        print("# (No hot memory context)")
```

### Testing Hooks

Test hooks from command line:

```bash
# Test session start hook
python -m hologram.hooks session-start --claude-dir .claude

# Test user prompt submit hook
python -m hologram.hooks user-prompt-submit "your message" --claude-dir .claude

# Pipe message from stdin
echo "your message" | python -m hologram.hooks user-prompt-submit --claude-dir .claude

# Get JSON output
python -m hologram.hooks session-start --json
```

## Integration with Claude Code Features

### Working Directory Detection

Hooks automatically find `.claude` directory by searching up from current working directory:

```
/project/
├── .claude/           ← Found automatically
│   ├── hooks/
│   └── files...
├── src/
│   └── subdir/        ← Hooks work from here too
```

### Memory Note Creation

Create notes during conversations:

```python
# In your code or via hologram CLI
import hologram

session = hologram.Session('.claude')
session.note(
    "Important Decision",
    "We decided to use approach X because of reasons Y and Z",
    links=['[[architecture.md]]', '[[decisions.md]]']
)
session.save()
```

Notes immediately become part of the routing system.

### Export/Import for Portability

Move memory between environments:

```bash
# Export from Claude Code
hologram export .claude memory-backup.tar.gz

# Import to Claude.ai (upload folder)
# Import to ChatGPT (upload to sandbox)
# Import to another machine
hologram import memory-backup.tar.gz .claude
```

## Troubleshooting

### Hook Not Running

Check:
1. Scripts are executable: `chmod +x .claude/hooks/*.py`
2. Python can import hologram: `python -c "import hologram; print(hologram.__version__)"`
3. `.claude` directory exists and has valid structure
4. Claude Code hook configuration is correct

### No Memory Context Appearing

Debug:
```bash
# Test hook manually
cd your-project
python .claude/hooks/user-prompt-submit.py <<< "test message"

# Check session status
hologram status .claude

# Verify files are being tracked
hologram files .claude
```

### Injection Too Large

Adjust max characters:
```python
# In your hook script
result = hologram.hooks.user_prompt_submit_hook(
    max_injection_chars=15000  # Reduce from default 25000
)
```

Or create custom filtering logic to only inject most relevant files.

## Examples

See the `examples/` directory for complete working examples:
- Basic integration
- Custom filtering
- Automatic note creation
- Cross-platform workflows

## Performance

Typical hook overhead:
- Session start: ~50ms (loads state)
- User prompt submit: ~100-150ms (routes message, updates pressure)
- Memory overhead: ~15-20MB per session

This is negligible for interactive use in Claude Code.

## Best Practices

1. **Start with minimal hooks** - Just `user-prompt-submit` is often enough
2. **Use .gitignore** - Add `.claude/hologram_state.json` and `.claude/hologram_history.jsonl` to ignore list (or don't, if you want to commit state)
3. **Regular exports** - Periodically backup with `hologram export`
4. **Monitor pressure** - Run `hologram status .claude` occasionally to see what's hot
5. **Create notes** - Use `hologram note` or `session.note()` to explicitly save important decisions

## See Also

- [Session API Reference](README.md#session-api)
- [CLI Commands](README.md#cli)
- [Pressure Configuration](README.md#configuration)
- [Cross-Platform Usage](README.md#cross-platform-portability)
