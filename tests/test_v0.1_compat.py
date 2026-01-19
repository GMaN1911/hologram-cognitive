#!/usr/bin/env python3
"""Test backward compatibility with v0.1.1 low-level API."""

import sys
sys.path.insert(0, '/home/garret-sutherland/hologram-cognitive-0.2.0-src')

from hologram import CognitiveSystem, process_turn, get_context
from hologram.pressure import PressureConfig
from hologram.dag import EdgeDiscoveryConfig

print("=" * 60)
print("Testing v0.1.1 Backward Compatibility")
print("=" * 60)

# Test low-level CognitiveSystem API (v0.1.1 style)
print("\n--- CognitiveSystem (v0.1.1 API) ---")

# Create minimal test files
test_files = {
    "test1.md": "# Test 1\nContent about lighthouse and pressure.",
    "test2.md": "# Test 2\nRelated to [[test1.md]] and memory.",
}

system = CognitiveSystem(pressure_config=PressureConfig())

for name, content in test_files.items():
    system.add_file(name, content)

print(f"Files added: {len(system.files)}")

# Process a turn (v0.1.1 API)
result = process_turn(system, "Tell me about lighthouse")
print(f"Turn processed: activated {len(result.activated)} files")

# Get context (v0.1.1 API)
context = get_context(system)
print(f"Context tiers: {list(context.keys())}")

print(f"\nCurrent turn: {system.current_turn}")
print(f"File pressures:")
for name, cf in system.files.items():
    print(f"  {name}: {cf.raw_pressure:.2f}")

# Test PressureConfig and EdgeDiscoveryConfig are accessible
print("\n--- Configuration Classes (v0.1.1 API) ---")
pressure_cfg = PressureConfig(
    activation_boost=0.15,
    propagation_factor=0.3,
    decay_rate=0.02
)
print(f"PressureConfig: activation_boost={pressure_cfg.activation_boost}")

edge_cfg = EdgeDiscoveryConfig(auto_extract_links=True)
print(f"EdgeDiscoveryConfig: auto_extract_links={edge_cfg.auto_extract_links}")

print("\n" + "=" * 60)
print("v0.1.1 API fully compatible! ✅")
print("=" * 60)
