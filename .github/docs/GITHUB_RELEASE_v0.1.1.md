# GitHub Release v0.1.1 - Copy/Paste Template

**Instructions:** Copy everything between the dashed lines and paste into GitHub release form.

---

## Release Title
```
Hologram Cognitive v0.1.1 - Version Alignment
```

## Tag
```
v0.1.1
```

## Release Description

```markdown
# v0.1.1 - Version Alignment Release

This release corrects a version mismatch between git tags and PyPI packages.

## 🔧 What Changed

- **Version number updated:** 0.1.0 → 0.1.1
- **No functional changes** (identical to PyPI v0.1.0 functionality)
- **Repository cleanup:** Process docs moved to `.github/docs/`

## 📦 Why This Release?

The git tag `v0.1.0` pointed to an early commit (MIT License), while the PyPI package `v0.1.0` contained all lighthouse features. This created confusion when comparing versions.

**v0.1.1 solves this:** Now the git tag and PyPI package are perfectly aligned.

## 🚀 Installation

```bash
pip install hologram-cognitive
```

This installs v0.1.1, which now matches the git tag exactly.

## ✨ Full Features (same as v0.1.0 on PyPI)

### 🔦 The Lighthouse (Toroidal Decay)
- Gentle re-anchoring for long-context sessions (>1000 turns)
- Resurrects forgotten files to WARM tier (0.55 pressure)
- Non-disruptive design (doesn't displace HOT files)
- Enabled by default with 100-turn sweep cycle

**Metaphor:** A lighthouse beam that sweeps periodically, illuminating forgotten context without moving your ship.

### 🌊 Pressure Dynamics
- Fixed 10.0 pressure budget (conservation law)
- Lateral inhibition: Boosting signal drains noise
- Multi-hop BFS propagation with exponential decay
- Periodic normalization (every 100 turns)

### 📊 Auto DAG Discovery
- 6 discovery strategies (path, filename, imports, markdown links, etc.)
- Ghost edge prevention (excludes generic terms like 'utils', 'test', 'config')
- Dynamic edge weights (multi-mention = stronger relationship)
- Zero configuration required

### 🐛 Bug Fixes (from pre-release)
- State drift correction (missing redistribute_pressure)
- Ghost edge elimination (generic term exclusion)
- Deterministic hashing (SHA3 instead of Python hash())
- Performance improvements (pre-computed DAG edges)

## 📚 Documentation

- [README](https://github.com/GMaN1911/hologram-cognitive/blob/main/README.md) - Installation, usage, features
- [Technical Deep-Dive](https://github.com/GMaN1911/hologram-cognitive/blob/main/FIXES_AND_EXPERIMENTS.md) - Bug fixes and design decisions
- [Version History](https://github.com/GMaN1911/hologram-cognitive/blob/main/VERSION_HISTORY.md) - Complete release timeline
- [PyPI Package](https://pypi.org/project/hologram-cognitive/) - Published package

## 🔗 Links

- **PyPI:** https://pypi.org/project/hologram-cognitive/0.1.1/
- **GitHub:** https://github.com/GMaN1911/hologram-cognitive
- **Issues:** https://github.com/GMaN1911/hologram-cognitive/issues

## 🎯 Philosophy

**Conservation Over Addition** - Don't just add context, manage attention budget
**Discovery Over Configuration** - Auto DAG replaces manual co-activation
**Agency Over Automation** - Lighthouse illuminates, doesn't force

---

*"Conservation means adding signal mechanically cools noise."*

**Built with ❤️ by MirrorEthic LLC**
```

---

## Release Assets (Optional)

You can attach these files if you want:

**From `dist/` directory:**
- `hologram_cognitive-0.1.1-py3-none-any.whl` (27 KB) - Wheel distribution
- `hologram_cognitive-0.1.1.tar.gz` (52 KB) - Source distribution

**Note:** GitHub automatically creates source archives (zip and tar.gz), so attaching these is optional but can be helpful for users who want the exact PyPI artifacts.

---

## Checklist Before Publishing

- [ ] Tag selected: v0.1.1
- [ ] Title: "Hologram Cognitive v0.1.1 - Version Alignment"
- [ ] Description pasted from above
- [ ] "Set as the latest release" checked
- [ ] Release type: Latest release (not pre-release)

---

## After Publishing

Once published, the release will be at:
```
https://github.com/GMaN1911/hologram-cognitive/releases/tag/v0.1.1
```

You can then:
1. Share the release link
2. Update `~/.claude/HOLOGRAM_INTEGRATION.md` with PyPI installation info
3. Monitor PyPI download stats: https://pypistats.org/packages/hologram-cognitive

---

## Quick Copy Sections

If you need to copy specific sections:

**Title only:**
```
Hologram Cognitive v0.1.1 - Version Alignment
```

**Short description (for announcements):**
```
🔦 Hologram Cognitive v0.1.1 is now available!

This release aligns git tags with PyPI packages for consistency.

pip install hologram-cognitive

Features the Lighthouse (toroidal decay) for long-context re-anchoring,
pressure-conserving attention dynamics, and auto DAG discovery.

PyPI: https://pypi.org/project/hologram-cognitive/0.1.1/
GitHub: https://github.com/GMaN1911/hologram-cognitive
```
