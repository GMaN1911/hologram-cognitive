# Hologram Cognitive

> **Pressure-based context routing for Claude Code**
> Replaces manual co-activation with physics-driven attention dynamics

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

---

## The Problem

Current RAG systems face the **noise saturation problem**:
- More context = more noise dilution
- Manual `co_activation` is brittle and doesn't scale
- Static routing misses dynamic relationships
- Infinite context windows → infinite signal degradation

**Result:** Claude Code loads irrelevant docs, wastes tokens, loses focus.

---

## The Solution

**Hologram Cognitive** implements **pressure-conserving attention dynamics**:

```
Conservation Law: Adding signal mechanically cools noise
```

When you activate relevant context, pressure **flows away** from irrelevant files due to conservation. The system maintains constant total pressure (10.0), so boosting one file **drains** from others automatically.

### Key Features

**🌊 Pressure Dynamics**
- **Conservation:** Fixed total pressure budget (10.0)
- **Lateral inhibition:** Activating signal suppresses noise
- **Multi-hop propagation:** Pressure flows along DAG edges
- **Exponential decay:** Unused files naturally cool down

**🔦 The Lighthouse (Toroidal Decay)**
- **Gentle re-anchoring:** Forgotten files resurrect to WARM tier
- **Non-disruptive:** Doesn't displace your active focus (HOT files stay HOT)
- **Spaced repetition:** ~Every 100 turns, sweep for dead context
- **Long-context support:** Compensates for human memory degradation

**📊 Content-Addressed Coordinates**
- **Deterministic buckets:** SHA3-based structural positioning
- **No semantic similarity:** Explicit edges via DAG discovery
- **Auto-discovery:** Finds relationships from mentions/imports
- **Ghost edge prevention:** Excludes generic terms (utils, test, config)

**🔄 No Manual Configuration**
- **Auto DAG:** Discovers edges from content
- **Dynamic weights:** Multi-mention = stronger edge
- **Hub governance:** High-degree nodes don't dominate
- **Zero setup:** Just point at .claude/ directory

---

## How It Works

### 1. Content-Addressed Coordinates

Each file gets a **structural coordinate** (system bucket) via SHA3:

```python
bucket = int(sha3_256(path + content).hexdigest()[:8], 16) % 48
```

This is **static** - changes only when content changes. No semantic similarity.

### 2. Pressure Coordinates

Each file also has a **dynamic pressure** (attention state):

```python
raw_pressure: float   # 0.0 → 1.0
pressure_bucket: int  # 0-47 (quantized)
tier: str            # HOT (>40), WARM (20-40), COLD (<20)
```

This is **dynamic** - changes with usage patterns.

### 3. DAG Auto-Discovery

Edges discovered from content:

```python
# modules/auth.md mentions "modules/user.md"
adjacency['modules/auth.md'] = {'modules/user.md', 'modules/session.md'}

# Weighted by relationship strength
edge_weights['modules/auth.md']['modules/user.md'] = 1.8
```

**Discovery strategies:**
- Full path matching
- Filename matching
- Hyphenated keyword matching (`t3-telos` → `t3` + `telos`)
- Import statements (`from X import Y`)
- Markdown links (`[text](path)`)
- **Excludes:** Generic terms (utils, test, config, etc.)

### 4. Pressure Dynamics

**Turn Processing:**

```python
1. Activation: Query activates relevant files (+0.4 pressure)
2. Propagation: HOT files push pressure to neighbors (BFS, 2 hops)
3. Decay: Inactive files cool down (×0.85 per turn)
4. Lighthouse: Dead files resurrect to WARM (every 100 turns)
5. Normalization: Total pressure normalized to 10.0 (every 100 turns)
```

**Conservation in Action:**

```
Before Query: Total = 10.0
- auth.md: 0.3 (COLD)
- database.md: 0.5 (WARM)
- ... 8 other files: 9.2 (distributed)

After "auth" Query: Total = 10.0 (conserved!)
- auth.md: 0.7 (boosted +0.4, now HOT)
- database.md: 0.4 (drained to maintain budget)
- ... 8 other files: 8.9 (gently cooled)
```

**Result:** Signal boosted, noise naturally suppressed.

### 5. The Lighthouse 🔦

**Problem:** In long sessions (>1000 turns), humans forget what files exist.

**Solution:** Toroidal decay - dead files "wrap around" and resurface:

```python
# File decays to near-zero
if raw_pressure < 0.05:
    # Resurrect to WARM (0.55), not HOT (0.8)
    raw_pressure = 0.55  # Visible but non-disruptive
    last_resurrected = current_turn

# Cooldown prevents loops
if current_turn - last_resurrected >= 100:
    # Ready for next resurrection
```

**Metaphor:**
- 🔦 **Beam sweeps periodically** - Every ~100 turns
- 💡 **Illuminates forgotten context** - Makes visible in WARM tier
- 🚢 **Doesn't move your ship** - HOT files stay HOT (minimal drain)
- 🧭 **You choose navigation** - Ignore or explore (agency preserved)

---

## Quick Start

### Installation

```bash
pip install hologram-cognitive
```

Or from source:

```bash
git clone https://github.com/GMaN1911/hologram-cognitive.git
cd hologram-cognitive
pip install -e .
```

### Basic Usage

```python
from hologram import CognitiveSystem

# Create system
system = CognitiveSystem()

# Add your .claude/ docs
import glob
for path in glob.glob('.claude/**/*.md', recursive=True):
    with open(path) as f:
        system.add_file(path, f.read())

# Process a query
from hologram.system import process_turn
record = process_turn(system, "How does authentication work?")

# Get hot context
from hologram.router import get_context
context = get_context(system)

print(f"HOT files ({len(context['HOT'])}):")
for file in context['HOT']:
    print(f"  - {file.path} (pressure: {file.raw_pressure:.2f})")
```

### With Claude Code

**Standalone mode (replace context-router-v2):**

```bash
# In your project
git clone https://github.com/GMaN1911/hologram-cognitive.git
cd hologram-cognitive

# Process query
python -c "
from hologram import CognitiveSystem
import sys

system = CognitiveSystem()
# Load files...
process_turn(system, sys.argv[1])
context = get_context(system)
for f in context['HOT']:
    print(f.path)
" "your query here"
```

**Integrated mode (coming soon):**
Hologram will integrate directly with Claude Code's context system.

---

## Configuration

### Pressure Config

```python
from hologram import PressureConfig

config = PressureConfig(
    # Activation
    activation_boost=0.4,        # Pressure boost per activation

    # Propagation
    edge_flow_rate=0.15,         # How much flows per edge
    flow_decay_per_hop=0.7,      # Decay with distance
    max_propagation_hops=2,       # How far pressure flows

    # Decay
    decay_rate=0.85,             # Multiply by this each turn
    decay_immunity_turns=2,       # Grace period after activation

    # Lighthouse (Toroidal Decay)
    use_toroidal_decay=True,     # Enable resurrection
    resurrection_threshold=0.05,  # When file is "dead"
    resurrection_pressure=0.55,   # Resurrect to WARM
    resurrection_cooldown=100,    # Turns between resurrections

    # Conservation
    enable_conservation=True,     # Enforce pressure budget
    total_pressure_budget=10.0,   # Total pressure in system
)

system = CognitiveSystem(pressure_config=config)
```

### Edge Discovery Config

```python
from hologram import EdgeDiscoveryConfig

config = EdgeDiscoveryConfig(
    # Discovery strategies
    use_path_matching=True,
    use_filename_matching=True,
    use_partial_path=True,
    use_keyword_parts=True,
    use_import_statements=True,
    use_markdown_links=True,

    # Filtering
    min_part_length=4,
    exclude_generic_terms=['utils', 'test', 'config', ...],
    exclude_patterns=[r'__pycache__', r'\.git', ...],
)

system = CognitiveSystem(dag_config=config)
```

---

## Examples

### Example 1: Long-Context Session

```python
system = CognitiveSystem()
# Load 100+ docs

# Early session: Focus on auth
for turn in range(100):
    process_turn(system, "authentication and user management")

# Middle session: Database work (auth files decay)
for turn in range(100, 300):
    process_turn(system, "database schema and queries")

# Late session: Return to auth
# Question: Will lighthouse resurface old auth files?
record = process_turn(system, "auth security audit")
context = get_context(system)

# Result: old-auth-design.md resurrected at turn 202
# Visible in WARM tier, didn't displace current HOT files
```

### Example 2: Conservation in Action

```python
# Initial state
print(f"Total pressure: {sum(f.raw_pressure for f in system.files.values())}")
# Output: 10.0 (budget)

# Activate file
process_turn(system, "modules/auth.md")

# After activation
print(f"Total pressure: {sum(f.raw_pressure for f in system.files.values())}")
# Output: 10.0 (still conserved!)

# Check redistribution
print(f"auth.md: {system.files['modules/auth.md'].raw_pressure:.2f}")  # Boosted
print(f"other files: {[f.raw_pressure for f in system.files.values() if f.path != 'modules/auth.md']}")  # Drained
```

### Example 3: Ghost Edge Prevention

```python
# Without filtering (BAD):
system = CognitiveSystem(
    dag_config=EdgeDiscoveryConfig(exclude_generic_terms=[])
)
# "utils" in content → edge to ANY file with "utils" in path
# Result: 100+ false edges

# With filtering (GOOD):
system = CognitiveSystem(
    dag_config=EdgeDiscoveryConfig(
        exclude_generic_terms=['utils', 'test', 'config']
    )
)
# "utils" ignored → no false edges
# Result: Clean, accurate DAG
```

---

## Architecture

### File Structure

```
hologram-cognitive/
├── hologram/
│   ├── __init__.py          # Public API
│   ├── system.py            # CognitiveSystem, CognitiveFile, process_turn
│   ├── coordinates.py       # Bucket computation, quantization
│   ├── pressure.py          # Pressure dynamics, lighthouse
│   ├── dag.py               # Edge discovery, mutual clusters
│   └── router.py            # Context selection, injection
├── tests/
│   ├── test_hologram.py     # Unit tests
│   ├── decay_comparison.py  # Linear vs toroidal benchmark
│   └── scc_comparison.py    # SCC evaluation
├── examples/
│   └── migration_example.py # Basic usage example
├── README.md                # This file
├── FIXES_AND_EXPERIMENTS.md # Technical deep-dive
└── setup.py                 # Package config
```

### Key Classes

**CognitiveSystem:**
- Main entry point
- Manages files, DAG, pressure state
- Orchestrates turn processing

**CognitiveFile:**
- Dual coordinates: structural (system_bucket) + dynamic (pressure_bucket)
- Tracks activation history, edges, metadata

**PressureConfig:**
- Configures all dynamics parameters
- Lighthouse settings
- Conservation settings

**EdgeDiscoveryConfig:**
- Configures DAG discovery strategies
- Ghost edge prevention

---

## Performance

**Complexity:**
- File addition: O(V + E) - DAG discovery
- Turn processing: O(V + E) - Pressure propagation (BFS)
- Context retrieval: O(V log V) - Sorting by priority

**Typical Performance (1000 files):**
- Add file: ~10-20ms
- Process turn: ~50-100ms
- Get context: ~5-10ms
- Lighthouse check: ~1-2ms (when triggered)

**Memory:**
- Per file: ~1-2KB (file object + edges)
- 1000 files: ~1-2MB

**Scaling:**
- Tested up to 1000 files
- Conservation prevents unbounded growth
- Edge discovery is one-time cost

---

## Comparison

### vs. Traditional RAG

| Feature | Traditional RAG | Hologram |
|---------|----------------|----------|
| Context selection | Semantic similarity | Pressure dynamics |
| Signal/noise | Dilutes with size | Conserved ratio |
| Configuration | Manual co-activation | Auto DAG discovery |
| Long-context | Forgets everything | Lighthouse resurrection |
| Physics | Static | Dynamic (conservation) |

### vs. Context-Router-v2

| Feature | Context-Router-v2 | Hologram |
|---------|-------------------|----------|
| Routing | 3-tier priority | Pressure physics |
| Relationships | Manual `co_activation` | Auto DAG discovery |
| Decay | None | Exponential decay |
| Re-anchoring | None | Lighthouse (toroidal) |
| Conservation | None | Yes (lateral inhibition) |

---

## Testing

```bash
# Run tests
pytest

# Run lighthouse comparison
python tests/decay_comparison.py

# Run SCC evaluation
python tests/scc_comparison.py
```

**Test Coverage:**
- ✅ Content-addressed buckets (deterministic)
- ✅ Pressure quantization (48 buckets)
- ✅ Edge discovery (6 strategies)
- ✅ Pressure conservation (budget maintained)
- ✅ Multi-hop propagation (BFS correctness)
- ✅ Lighthouse resurrection (toroidal decay)
- ✅ Ghost edge prevention (generic term filtering)
- ✅ State drift correction (periodic normalization)

---

## Roadmap

**v0.1.0 (Current):**
- ✅ Core pressure dynamics
- ✅ Auto DAG discovery
- ✅ Lighthouse (toroidal decay)
- ✅ Conservation enforcement
- ✅ Ghost edge prevention

**v0.2.0 (Next):**
- 🔄 Claude Code integration (native plugin)
- 🔄 Adaptive tier thresholds (percentile-based)
- 🔄 Hub governance (degree-based weighting)
- 🔄 Visualization tools (pressure heatmaps)
- 🔄 Performance profiling (bottleneck analysis)

**v0.3.0 (Future):**
- 📋 Multi-user support (shared context)
- 📋 Temporal coherence (long-term memory)
- 📋 Cluster-based routing (SCC utilization)
- 📋 Real-time tuning (adaptive parameters)

---

## Contributing

**Found a bug?** Open an issue!

**Have an idea?** Start a discussion!

**Want to contribute?**
1. Fork the repo
2. Create a feature branch
3. Add tests for new features
4. Ensure all tests pass
5. Submit a pull request

---

## Philosophy

Hologram Cognitive is built on three principles:

**1. Conservation Over Addition**
- Don't just add context - manage attention budget
- Boosting signal naturally suppresses noise
- Physics prevents unbounded growth

**2. Discovery Over Configuration**
- Auto DAG replaces manual `co_activation`
- Relationships emerge from content
- Zero-configuration by default

**3. Agency Over Automation**
- Lighthouse illuminates, doesn't force
- WARM resurrection (visible but non-disruptive)
- User chooses navigation

---

## License

MIT License - See LICENSE file for details

---

## Citation

If you use Hologram Cognitive in research, please cite:

```bibtex
@software{hologram_cognitive,
  author = {MirrorEthic LLC},
  title = {Hologram Cognitive: Pressure-Based Context Routing},
  year = {2026},
  url = {https://github.com/GMaN1911/hologram-cognitive}
}
```

---

## Acknowledgments

- **Inspiration:** MirrorBot CVMP's consciousness modeling architecture
- **Physics:** Lateral inhibition in biological neural networks
- **Design:** Spaced repetition and working memory research

---

**Built with ❤️ by MirrorEthic LLC**

*"Conservation means adding signal mechanically cools noise"*
