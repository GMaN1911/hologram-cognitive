# Example Claude Code Hooks

Ready-to-use hook scripts for integrating hologram-cognitive with Claude Code.

## Quick Install

### Option 1: Copy to Your Project

```bash
cd your-project

# Create hooks directory
mkdir -p .claude/hooks/

# Copy hooks
cp /path/to/hologram-cognitive/examples/hooks/*.py .claude/hooks/

# Make executable
chmod +x .claude/hooks/*.py
```

### Option 2: Global Installation

```bash
# Copy to global Claude directory
cp /path/to/hologram-cognitive/examples/hooks/*.py ~/.claude/hooks/

# Make executable
chmod +x ~/.claude/hooks/*.py
```

## Hook Files

### user-prompt-submit.py

**Called:** Before each user message
**Purpose:** Inject memory context based on message content
**Output:** Relevant files (HOT/WARM/COLD tiers) for prompt injection

**Features:**
- Automatic .claude directory discovery
- Pressure-based routing
- Auto-save after each turn
- Graceful fallback on errors

### session-start.py

**Called:** When Claude Code session starts
**Purpose:** Display memory status
**Output:** Summary of available memory (files, turns, hot/warm files)

**Features:**
- Shows memory statistics
- Lists top hot/warm files
- Provides usage instructions

## Testing Hooks

Test hooks manually before using with Claude Code:

```bash
# Test session-start
cd your-project
.claude/hooks/session-start.py

# Test user-prompt-submit
echo "Tell me about the architecture" | .claude/hooks/user-prompt-submit.py

# Test with JSON input (claude-cognitive format)
echo '{"prompt": "What is T3?"}' | .claude/hooks/user-prompt-submit.py
```

## Configuration

### Claude Code Settings

Add to your Claude Code configuration (typically `~/.claude/settings.json`):

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

### Environment Variables

Optional environment variables:

```bash
# Override .claude directory location
export HOLOGRAM_CLAUDE_DIR=/path/to/.claude

# Adjust max injection size
export HOLOGRAM_MAX_CHARS=20000

# Enable debug output
export HOLOGRAM_DEBUG=1
```

## Customization

### Adjust Injection Size

Edit `user-prompt-submit.py`:

```python
backend = HologramBackend(
    claude_dir=str(claude_dir),
    auto_save=True,
    max_injection_chars=15000  # Reduce from default 25000
)
```

### Filter by File Type

Add filtering to only inject certain file types:

```python
result = backend.route_message(user_prompt, return_format='claude-cognitive')

# Filter HOT files to only markdown
hot_md = [f for f in result['tiers']['hot'] if f['path'].endswith('.md')]

# Rebuild injection with filtered files
# (custom logic here)
```

### Add Pool Coordinator Integration

Combine with claude-cognitive's pool coordinator:

```python
# After routing
result = backend.route_message(user_prompt)

# Generate pool block
if os.getenv('CLAUDE_INSTANCE'):
    pool_info = f"""
MEMORY: {result['stats']['hot_count']} hot, turn {result['turn']}
"""
    # Append to pool file
```

## Troubleshooting

### Hook Not Running

1. Check hook is executable: `ls -l .claude/hooks/`
2. Test manually: `.claude/hooks/user-prompt-submit.py`
3. Check Claude Code logs for errors

### Import Errors

```bash
# Ensure hologram-cognitive is installed
pip install hologram-cognitive

# Verify installation
python -c "import hologram; print(hologram.__version__)"
```

### No .claude Directory Found

Hooks search up from current directory. Ensure:
1. `.claude/` exists in your project root
2. Or run `hologram init .claude` to create it

### Debug Output

Enable debug mode:

```bash
export HOLOGRAM_DEBUG=1
.claude/hooks/user-prompt-submit.py
```

Debug output goes to stderr (visible in Claude Code console).

## See Also

- [Claude Code Integration Guide](../../CLAUDE_CODE_INTEGRATION.md)
- [claude-cognitive Integration](../../CLAUDE_COGNITIVE_INTEGRATION.md)
- [Session API Reference](../../README.md)
