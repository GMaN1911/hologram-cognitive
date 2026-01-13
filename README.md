# hologram-cognitive v0.1.0

**Auto-discovered DAG-based context routing for AI systems**

[![Version](https://img.shields.io/badge/version-0.1.0-blue)](https://github.com/GMaN1911/hologram-cognitive/releases)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9+-blue)](https://www.python.org/)

See full documentation: https://github.com/GMaN1911/hologram-cognitive

## What is this?

Auto-discovers relationships between documentation files using 6 strategies, then uses physics-based prioritization to inject relevant context.

**Key Innovation:** 20x more relationships than manual config, 100% accuracy, zero configuration.

## Quick Start

\`\`\`bash
# Clone
cd ~/
git clone https://github.com/GMaN1911/hologram-cognitive.git

# Use in Python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "hologram-cognitive/hologram"))

from hologram import HologramRouter

router = HologramRouter.from_directory('.claude/')
record = router.process_query("work on auth")
print(router.get_injection_text())
\`\`\`

## Integration

See [claude-cognitive v2.0](https://github.com/GMaN1911/claude-cognitive/tree/v2.0) for complete integration example.

**Created by:** Garret Sutherland ([@GMaN1911](https://github.com/GMaN1911))
