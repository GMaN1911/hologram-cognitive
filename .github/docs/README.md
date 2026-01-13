# Maintainer Documentation

This directory contains process documentation for maintaining and releasing hologram-cognitive.

**For Users:** See the [main README](../../README.md) for installation and usage.

**For Contributors:** These docs explain how the package was published and how to do future releases.

---

## Contents

### Publication Process
- **PYPI_PUBLICATION.md** - Complete guide to publishing to PyPI
  - Step-by-step upload instructions
  - Troubleshooting common issues
  - Version management
  - Security best practices

- **READY_FOR_PYPI.md** - Pre-publication checklist
  - Quick command reference
  - Verification steps
  - Post-publication tasks

- **PUBLISHED.md** - Publication success record
  - What was published (v0.1.0)
  - Verification results
  - Next steps after publication
  - Security reminder (token revocation)

### Release Documentation
- **GITHUB_RELEASE_v0.1.0.md** - Template for GitHub releases
  - Release description format
  - Feature highlights
  - Installation instructions

---

## For Future Releases

### Quick Reference

**1. Update version:**
```bash
# Edit pyproject.toml and hologram/__init__.py
vim pyproject.toml hologram/__init__.py
```

**2. Build:**
```bash
rm -rf dist/ build/ *.egg-info
python -m build
```

**3. Upload to PyPI:**
```bash
twine upload dist/*
```

**4. Create git tag:**
```bash
git tag -a v0.x.x -m "Release notes"
git push origin v0.x.x
```

**5. Create GitHub release:**
- Go to https://github.com/GMaN1911/hologram-cognitive/releases/new
- Use GITHUB_RELEASE_v0.1.0.md as template

---

## Documentation Philosophy

**Root directory** - User-facing documentation:
- README.md - Main documentation
- FIXES_AND_EXPERIMENTS.md - Technical deep-dive
- VERSION_HISTORY.md - Release history
- LICENSE - MIT License

**.github/docs/** - Maintainer documentation:
- Process guides (this directory)
- Not included in PyPI packages
- Available to contributors via GitHub

This separation keeps the project root clean while preserving valuable process documentation for maintainers.

---

## Related Documentation

- [Main README](../../README.md) - Installation, usage, features
- [Technical Deep-Dive](../../FIXES_AND_EXPERIMENTS.md) - Bug fixes and design decisions
- [Version History](../../VERSION_HISTORY.md) - Complete release timeline
- [PyPI Package](https://pypi.org/project/hologram-cognitive/) - Published package

---

**Last Updated:** 2026-01-12 (v0.1.1 release)
