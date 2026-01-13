# PyPI Publication Guide for Hologram Cognitive v0.1.0

**Status:** Ready for publication
**Version:** 0.1.0
**Repository:** https://github.com/GMaN1911/hologram-cognitive
**PyPI Package Name:** hologram-cognitive

---

## Prerequisites

### 1. Install Build Tools

```bash
pip install --upgrade build twine
```

**What these do:**
- `build`: Creates distribution packages (sdist and wheel)
- `twine`: Uploads packages to PyPI securely

### 2. PyPI Account Setup

**Create accounts (if you don't have them):**

1. **Test PyPI** (for testing): https://test.pypi.org/account/register/
2. **Production PyPI**: https://pypi.org/account/register/

**Generate API Tokens (recommended over password):**

1. Go to https://pypi.org/manage/account/token/
2. Create token with scope: "Entire account" or specific to "hologram-cognitive"
3. Save token securely (you'll need it for upload)

**Configure token in `~/.pypirc`:**

```ini
[pypi]
username = __token__
password = pypi-AgENT... (your token here)

[testpypi]
username = __token__
password = pypi-AgENT... (your test token here)
```

**Set permissions:**
```bash
chmod 600 ~/.pypirc
```

---

## Publication Steps

### Step 1: Pre-Flight Checklist

Verify all files are ready:

```bash
cd /home/garret-sutherland/hologram-cognitive-v0.1.0/hologram-cognitive

# Check version
grep version pyproject.toml
# Should show: version = "0.1.0"

# Verify README exists
ls -la README.md

# Verify LICENSE exists
ls -la LICENSE

# Check package structure
ls -la hologram/
# Should show: __init__.py, coordinates.py, dag.py, pressure.py, router.py, system.py
```

**Critical Files Status:**
- ✅ `pyproject.toml` - Package metadata configured
- ✅ `README.md` - Comprehensive documentation (566 lines)
- ✅ `LICENSE` - MIT License
- ✅ `hologram/__init__.py` - Package initialization
- ✅ `hologram/*.py` - Core modules
- ✅ `FIXES_AND_EXPERIMENTS.md` - Technical deep-dive
- ✅ `tests/` - Test suite

### Step 2: Clean Previous Builds

```bash
# Remove any old build artifacts
rm -rf dist/ build/ *.egg-info hologram.egg-info

# This ensures clean builds
```

### Step 3: Build Distribution Packages

```bash
python -m build
```

**What this creates:**
```
dist/
├── hologram_cognitive-0.1.0-py3-none-any.whl  # Wheel (binary distribution)
└── hologram-cognitive-0.1.0.tar.gz            # Source distribution
```

**Expected output:**
```
* Creating venv isolated environment...
* Installing packages in isolated environment... (setuptools>=61.0, wheel)
* Getting build dependencies for sdist...
* Building sdist...
* Building wheel from sdist
* Successfully built hologram-cognitive-0.1.0.tar.gz and hologram_cognitive-0.1.0-py3-none-any.whl
```

### Step 4: Verify Distribution

```bash
# Check what was built
ls -lh dist/

# Verify package contents
tar -tzf dist/hologram-cognitive-0.1.0.tar.gz | head -20

# Check wheel contents
unzip -l dist/hologram_cognitive-0.1.0-py3-none-any.whl
```

**Should include:**
- All `hologram/*.py` files
- `README.md`
- `LICENSE`
- `pyproject.toml`
- Package metadata

### Step 5: Test Upload to Test PyPI (Recommended)

```bash
# Upload to Test PyPI first
twine upload --repository testpypi dist/*
```

**Expected prompts:**
```
Uploading distributions to https://test.pypi.org/legacy/
Enter your username: __token__
Enter your password: (your test PyPI token)
```

**Expected output:**
```
Uploading hologram_cognitive-0.1.0-py3-none-any.whl
100%|████████████████████| 12.3k/12.3k [00:01<00:00, 8.42kB/s]
Uploading hologram-cognitive-0.1.0.tar.gz
100%|████████████████████| 15.2k/15.2k [00:00<00:00, 18.9kB/s]

View at:
https://test.pypi.org/project/hologram-cognitive/0.1.0/
```

### Step 6: Test Installation from Test PyPI

```bash
# Create test environment
python -m venv test_env
source test_env/bin/activate

# Install from Test PyPI
pip install --index-url https://test.pypi.org/simple/ hologram-cognitive

# Test import
python -c "from hologram import CognitiveSystem; print('✅ Import successful')"

# Deactivate and clean up
deactivate
rm -rf test_env
```

### Step 7: Production Upload to PyPI

**⚠️ This is permanent - you cannot delete or modify packages on PyPI after upload!**

```bash
# Upload to production PyPI
twine upload dist/*
```

**Expected prompts:**
```
Uploading distributions to https://upload.pypi.org/legacy/
Enter your username: __token__
Enter your password: (your production PyPI token)
```

**Expected output:**
```
Uploading hologram_cognitive-0.1.0-py3-none-any.whl
100%|████████████████████| 12.3k/12.3k [00:01<00:00, 8.42kB/s]
Uploading hologram-cognitive-0.1.0.tar.gz
100%|████████████████████| 15.2k/15.2k [00:00<00:00, 18.9kB/s]

View at:
https://pypi.org/project/hologram-cognitive/0.1.0/
```

### Step 8: Verify Production Installation

```bash
# Create clean test environment
python -m venv verify_env
source verify_env/bin/activate

# Install from PyPI
pip install hologram-cognitive

# Verify version
python -c "from hologram import __version__; print(f'✅ Version: {__version__}')"

# Quick smoke test
python -c "
from hologram import CognitiveSystem, PressureConfig
system = CognitiveSystem()
print('✅ CognitiveSystem instantiated')
print(f'✅ Lighthouse enabled: {system.pressure_config.use_toroidal_decay}')
"

# Clean up
deactivate
rm -rf verify_env
```

---

## Post-Publication Checklist

### Update README with Installation Instructions

Add to README.md (if not already there):

```markdown
## Installation

```bash
pip install hologram-cognitive
```

Or from source:

```bash
git clone https://github.com/GMaN1911/hologram-cognitive.git
cd hologram-cognitive
pip install -e .
```
\```
```

### Tag Release on GitHub

```bash
cd /home/garret-sutherland/hologram-cognitive-v0.1.0/hologram-cognitive

# Create annotated tag
git tag -a v0.1.0 -m "Release v0.1.0 - Lighthouse Toroidal Decay

Features:
- Pressure-conserving attention dynamics
- Auto DAG discovery (6 strategies)
- Lighthouse toroidal decay (ENABLED by default)
- Ghost edge prevention
- State drift correction
- Comprehensive documentation

The Lighthouse: Non-disruptive re-anchoring for long-context sessions.
Resurrects forgotten files to WARM tier without displacing active work."

# Push tag
git push origin v0.1.0
```

### Create GitHub Release

1. Go to https://github.com/GMaN1911/hologram-cognitive/releases
2. Click "Draft a new release"
3. Select tag: v0.1.0
4. Title: "Hologram Cognitive v0.1.0 - The Lighthouse"
5. Description:

```markdown
# Hologram Cognitive v0.1.0 - The Lighthouse 🔦

**Pressure-based context routing with lighthouse re-anchoring for Claude Code**

## Installation

```bash
pip install hologram-cognitive
```

## Key Features

🌊 **Pressure Dynamics**
- Conservation law: Fixed 10.0 pressure budget
- Lateral inhibition: Boosting signal drains noise
- Multi-hop BFS propagation

🔦 **The Lighthouse (Toroidal Decay)**
- Gentle re-anchoring for long-context sessions
- Resurrects forgotten files to WARM tier (non-disruptive)
- Sweep cycle: Every ~100 turns
- Compensates for human memory degradation

📊 **Auto DAG Discovery**
- 6 discovery strategies (path, filename, imports, etc.)
- Ghost edge prevention (excludes generic terms)
- Dynamic edge weights

## What's New

- ✨ Lighthouse toroidal decay enabled by default
- 🐛 Fixed state drift bug (conservation property degradation)
- 🐛 Fixed ghost edge bug (generic term pollution)
- 📚 Comprehensive README and documentation
- 🧪 A/B testing framework (decay_comparison.py)

## Documentation

- [README](https://github.com/GMaN1911/hologram-cognitive/blob/main/README.md)
- [Technical Deep-Dive](https://github.com/GMaN1911/hologram-cognitive/blob/main/FIXES_AND_EXPERIMENTS.md)

## Philosophy

**Conservation Over Addition** - Don't just add context, manage attention budget
**Discovery Over Configuration** - Auto DAG replaces manual co-activation
**Agency Over Automation** - Lighthouse illuminates, doesn't force
```

6. Attach files (optional):
   - `dist/hologram-cognitive-0.1.0.tar.gz`
   - `dist/hologram_cognitive-0.1.0-py3-none-any.whl`

7. Check "Set as the latest release"
8. Publish release

### Update Documentation

**In HOLOGRAM_INTEGRATION.md:**

Add installation section:

```markdown
## Installation

Hologram Cognitive is now available on PyPI:

```bash
pip install hologram-cognitive
```

This installs the package globally, making it available to all Claude Code sessions.
\```
```

### Share Announcement

**Example announcement text:**

```
🔦 Hologram Cognitive v0.1.0 is now on PyPI!

pip install hologram-cognitive

Pressure-based context routing with lighthouse re-anchoring for Claude Code.

Key features:
- Conservation dynamics (boosting signal drains noise)
- The Lighthouse (gentle re-anchoring for long contexts)
- Auto DAG discovery (zero configuration)
- Ghost edge prevention

The lighthouse resurrects forgotten files to WARM tier without
displacing your active work. Think: beam that sweeps periodically,
illuminating what's there without moving your ship.

GitHub: https://github.com/GMaN1911/hologram-cognitive
PyPI: https://pypi.org/project/hologram-cognitive/
```

---

## Troubleshooting

### Error: "Package already exists"

If v0.1.0 is already on PyPI and you need to update:
1. Increment version in `pyproject.toml` (e.g., 0.1.1)
2. Rebuild: `python -m build`
3. Upload new version

**Note:** You CANNOT replace an existing version on PyPI.

### Error: "Invalid or missing authentication"

Check `~/.pypirc` configuration:
```bash
cat ~/.pypirc
# Should show [pypi] and [testpypi] sections with __token__ username
```

### Error: "twine: command not found"

Install twine:
```bash
pip install --upgrade twine
```

### Error: Package doesn't include expected files

Check `pyproject.toml` [tool.setuptools.packages.find]:
```toml
[tool.setuptools.packages.find]
include = ["hologram*"]
```

If you need to include additional files, create `MANIFEST.in`:
```
include README.md
include LICENSE
include FIXES_AND_EXPERIMENTS.md
recursive-include tests *.py
```

### Error: "README rendering failed on PyPI"

PyPI uses strict Markdown rendering. Check:
- No relative links (use absolute GitHub URLs)
- No HTML tags (use Markdown equivalents)
- No custom emoji that PyPI doesn't support

Test locally:
```bash
pip install readme-renderer
python -m readme_renderer README.md -o /tmp/output.html
```

---

## Version Management

**Current:** v0.1.0

**For future releases:**

1. Update version in `pyproject.toml`
2. Update `hologram/__init__.py` if it contains `__version__`
3. Document changes in release notes
4. Follow same publication steps
5. Create new git tag

**Semantic Versioning:**
- MAJOR (1.0.0): Breaking API changes
- MINOR (0.2.0): New features, backward compatible
- PATCH (0.1.1): Bug fixes, backward compatible

---

## Quick Reference Commands

```bash
# Full publication workflow
cd /home/garret-sutherland/hologram-cognitive-v0.1.0/hologram-cognitive

# Clean
rm -rf dist/ build/ *.egg-info

# Build
python -m build

# Test upload
twine upload --repository testpypi dist/*

# Test install
pip install --index-url https://test.pypi.org/simple/ hologram-cognitive

# Production upload
twine upload dist/*

# Verify
pip install hologram-cognitive
python -c "from hologram import CognitiveSystem; print('✅')"

# Tag release
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

---

**Ready for publication!** Follow steps 1-8 above to publish to PyPI.
