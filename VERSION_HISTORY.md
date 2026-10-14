# Hologram Cognitive - Version History

## v0.4.0 (2026-10-14) - Current Release

The routing engine of Hologram Pro 0.5, released free under MIT. Built from the same source as
Hologram Pro, with the Pro features left out.

- **Routes your project's own files**, with state in `your-project/.hologram/` (0.3 routed a
  `.claude/` notes directory; that directory is left as it was and is no longer routed).
- **Activation**: at most 8 files per prompt; stop-words and words found in most files ignored;
  whole-word matches; rarer words weigh more.
- **A fixed pressure budget of 10**, taken equally from every file, so the leaders keep their lead.
  Replaces 0.3's per-file dynamic budget, which kept every file lukewarm as projects grew.
- **A working set that is never empty**: the top 6 by pressure, the next 10 by name, and up to 3
  recently modified docs when too few files hold pressure. Replaces absolute hot/warm thresholds.
- **Learning from use**: the files a turn actually read or edited are reinforced; each file's boost
  and decay adapt to how often it is used when activated.
- **Fixtures and test data** are indexed but demoted unless the prompt names them.
- **Harnesses**: `hologram install claude-code` (a prompt hook and an end-of-turn hook) and
  `hologram install hermes` (Hologram as Hermes Agent's memory provider, with a warm worker so a
  prompt after the first costs tens of milliseconds); `hologram uninstall` reverses both.
- Off by default (still available as `PressureConfig` options for experiments): lighthouse
  resurrection and the dynamic budget, both measured to flatten the working set.
- The 0.3 notes commands (`route`, `note`, `pin`, `files`, `state`, `crystallize`, `sessions`,
  `export`, `import`) still take a notes directory, as in 0.3; the hooks do not use them.
- Python 3.11 or newer.

Hologram Pro (https://hologram-pro.dev) adds the project's causal graph and guards, project
memory, the blackboard between sessions, a reranker, and Codex, Grok and Antigravity support.

## v0.1.1 (2026-01-12)

**PyPI:** https://pypi.org/project/hologram-cognitive/0.1.1/
**Git Tag:** v0.1.1 (commit 6748fc5)
**Status:** ✅ Published and verified

### Purpose
This release corrects a version mismatch between git tags and PyPI packages.

### Background
- The git tag `v0.1.0` was created early (pointing to MIT License commit f068c99)
- The PyPI package `v0.1.0` was built from a later commit (with all lighthouse features)
- This created a mismatch: git v0.1.0 ≠ PyPI v0.1.0

### Solution
- Incremented version to 0.1.1 in both `pyproject.toml` and `hologram/__init__.py`
- Rebuilt and republished to PyPI as v0.1.1
- Created git tag v0.1.1 at current HEAD
- **Result:** git v0.1.1 = PyPI v0.1.1 ✅

### Changes (from v0.1.0 codebase)
- Version number updated: 0.1.0 → 0.1.1
- No functional changes (identical to PyPI v0.1.0 functionality)
- Added publication documentation (PYPI_PUBLICATION.md, READY_FOR_PYPI.md, PUBLISHED.md)

### Installation
```bash
pip install hologram-cognitive  # Gets v0.1.1 automatically
```

---

## v0.1.0 (2026-01-12) - Initial PyPI Release

**PyPI:** https://pypi.org/project/hologram-cognitive/0.1.0/ (SUPERSEDED by v0.1.1)
**Git Tag:** v0.1.0 (commit f068c99 - MIT License only, DOES NOT match PyPI)
**Status:** ⚠️ Version mismatch - use v0.1.1 instead

### Features (Lighthouse Release)
This was the first public release containing:

**🔦 The Lighthouse (Toroidal Decay)**
- Gentle re-anchoring for long-context sessions (>1000 turns)
- Resurrects forgotten files to WARM tier (0.55 pressure)
- Non-disruptive design (doesn't displace HOT files)
- Enabled by default with 100-turn sweep cycle

**🌊 Pressure Dynamics**
- Fixed 10.0 pressure budget (conservation law)
- Lateral inhibition (boosting signal drains noise)
- Multi-hop BFS propagation with exponential decay
- Periodic normalization (every 100 turns)

**📊 Auto DAG Discovery**
- 6 discovery strategies:
  1. Full path matching
  2. Filename matching
  3. Partial path components
  4. Hyphenated keyword parts
  5. Import statement parsing
  6. Markdown link detection
- Ghost edge prevention (excludes generic terms)
- Dynamic edge weights (multi-mention = stronger)

**🐛 Critical Bug Fixes**
1. **State drift** - Missing redistribute_pressure() call
2. **Ghost edges** - Generic terms creating false edges
3. **Non-deterministic hash** - Python's hash() is salted (fixed with SHA3)
4. **O(n²) BFS** - Scanning all files for incoming edges (pre-computed)

**📚 Documentation**
- Comprehensive README (566 lines)
- Technical deep-dive (FIXES_AND_EXPERIMENTS.md, 471 lines)
- Test suite with A/B comparison framework

### Why v0.1.0 is Superseded
The git tag v0.1.0 points to an early commit that only contains the MIT License. The PyPI package v0.1.0 contains all the features above, but this creates confusion. **Use v0.1.1 instead** for proper version alignment.

---

## Pre-Release History

### commit ea36568 (2026-01-12)
**Message:** `fix: state drift + ghost edges + experimental toroidal decay`

**Changes:**
- Fixed missing redistribute_pressure() call (state drift bug)
- Added exclude_generic_terms to EdgeDiscoveryConfig (ghost edge bug)
- Implemented experimental toroidal decay (use_toroidal_decay parameter)
- Created decay_comparison.py for A/B testing

**Status:** Experimental toroidal decay feature

### commit 43d02be (2026-01-12)
**Message:** `feat: lighthouse toroidal decay - non-disruptive resurrection`

**Changes:**
- Enabled toroidal decay by default (use_toroidal_decay = True)
- Changed resurrection target from HOT (0.8) to WARM (0.55)
- Updated all documentation with lighthouse metaphor
- Created comprehensive README (566 lines)
- Established production-ready defaults

**Status:** Lighthouse feature promoted to production

**Key Insight:** Resurrecting to WARM instead of HOT prevents displacement of active work due to conservation physics. This made toroidal decay viable for production.

### commit c4830f3 (2026-01-12)
**Message:** `docs: comprehensive README with lighthouse explanation`

**Changes:**
- 566-line README covering all features
- Lighthouse metaphor throughout
- Installation, configuration, examples
- Philosophy section (Conservation > Addition, Discovery > Configuration, Agency > Automation)

**Status:** Documentation complete

### commit 85fbc28 (2026-01-12)
**Message:** `fix: Critical bugs - determinism, performance, accuracy`

**Changes:**
- Replaced Python's hash() with SHA3-256 (deterministic)
- Fixed O(n²) BFS by pre-computing incoming edges
- Removed fake SCC implementation (mutual clusters were sufficient)
- Added hop propagation logic

**Status:** Core bugs fixed

### commit f068c99 (Early 2026-01)
**Message:** `chore: Add MIT License`

**Changes:**
- MIT License file added
- Copyright: Garret Sutherland / MirrorEthic LLC

**Status:** Initial git tag v0.1.0 points here (mismatch with PyPI)

---

## Version Philosophy

**Semantic Versioning:**
- MAJOR.MINOR.PATCH (0.1.1)
- MAJOR = 0: Pre-1.0, API may change
- MINOR: New features, backward compatible
- PATCH: Bug fixes, backward compatible

**Lighthouse Naming:**
- v0.1.0 was the "Lighthouse Release" (initial PyPI)
- v0.1.1 is the "Version Alignment Release" (git = PyPI)

**Future Versions:**
- v0.1.2+: Patch releases (bug fixes only)
- v0.2.0: Next minor release (new features)
- v1.0.0: Stable API commitment

---

## Migration Guide

### From PyPI v0.1.0 to v0.1.1
```bash
pip install --upgrade hologram-cognitive
```

**Changes:** None functional - only version number updated
**Compatibility:** 100% compatible, safe upgrade

### From Git v0.1.0 Tag (Early Commit)
If you cloned from the v0.1.0 git tag:

```bash
git fetch origin
git checkout v0.1.1  # Use the correct tag
pip install -e .     # Reinstall
```

**Changes:** All lighthouse features now included
**Compatibility:** Major functionality added

---

## Downloads

### v0.1.1 (Latest)
- **Wheel:** https://files.pythonhosted.org/packages/.../hologram_cognitive-0.1.1-py3-none-any.whl
- **Source:** https://files.pythonhosted.org/packages/.../hologram_cognitive-0.1.1.tar.gz
- **Install:** `pip install hologram-cognitive`

### v0.1.0 (Superseded)
- **Wheel:** https://files.pythonhosted.org/packages/.../hologram_cognitive-0.1.0-py3-none-any.whl
- **Source:** https://files.pythonhosted.org/packages/.../hologram_cognitive-0.1.0.tar.gz
- **Install:** `pip install hologram-cognitive==0.1.0` (not recommended)

---

## Statistics

### Code Size
- **Core modules:** 6 Python files (~12KB each)
- **Total package:** ~27KB (wheel), ~52KB (source)
- **Documentation:** ~1500 lines across 4 files

### Dependencies
- **Runtime:** None (pure Python, stdlib only)
- **Development:** pytest, pytest-cov

### Python Support
- 3.9, 3.10, 3.11, 3.12
- Type hints throughout

---

## Acknowledgments

**Inspiration:** MirrorBot CVMP's consciousness modeling architecture

**Key Contributors:**
- Garret Sutherland (MirrorEthic LLC) - Original design and implementation
- Claude (Anthropic) - Architectural review, bug identification, documentation

**Special Thanks:**
- The Claude Code community for inspiring the lighthouse feature
- The pressure dynamics research that led to conservation-based design

---

## References

- **PyPI Project:** https://pypi.org/project/hologram-cognitive/
- **GitHub Repository:** https://github.com/GMaN1911/hologram-cognitive
- **Documentation:** See README.md and FIXES_AND_EXPERIMENTS.md
- **License:** MIT

---

*"Conservation means adding signal mechanically cools noise."*
