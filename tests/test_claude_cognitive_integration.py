#!/usr/bin/env python3
"""Test claude-cognitive integration."""

import sys
sys.path.insert(0, '/home/garret-sutherland/hologram-cognitive-0.2.0-src')

import json
from hologram.claude_cognitive import HologramBackend

print("=" * 60)
print("Testing claude-cognitive Integration")
print("=" * 60)

# Create backend
backend = HologramBackend(
    claude_dir='/home/garret-sutherland/claude-memory-turn23/.claude',
    auto_save=True,
    max_injection_chars=25000
)

# Test routing
message = "Tell me about the T3 architecture and hologram system"
result = backend.route_message(message, return_format='claude-cognitive')

print(f"\n--- Result Structure ---")
print(f"Keys: {list(result.keys())}")
print(f"\n--- Stats ---")
print(json.dumps(result['stats'], indent=2))

print(f"\n--- Tiers (Summary) ---")
print(f"HOT files: {len(result['tiers']['hot'])}")
for f in result['tiers']['hot'][:3]:
    print(f"  - {f['path']} (pressure: {f['pressure']:.2f})")

print(f"\nWARM files: {len(result['tiers']['warm'])}")
for f in result['tiers']['warm'][:3]:
    print(f"  - {f['path']} (pressure: {f['pressure']:.2f}, headers: {len(f['headers'])})")

print(f"\nCOLD files: {len(result['tiers']['cold'])}")
print(f"  (first 3: {', '.join([f['path'] for f in result['tiers']['cold'][:3]])})")

print(f"\n--- Injection Preview (first 500 chars) ---")
print(result['injection'][:500])
print("...")

print(f"\n--- Status ---")
status = backend.get_status()
print(json.dumps(status, indent=2))

print("\n" + "=" * 60)
print("claude-cognitive integration working! ✅")
print("=" * 60)
