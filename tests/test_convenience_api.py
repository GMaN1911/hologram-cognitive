#!/usr/bin/env python3
"""Test the convenience route() function."""

import sys
sys.path.insert(0, '/home/garret-sutherland/hologram-cognitive-0.2.0-src')

import hologram
import json

print("=" * 60)
print("Testing Convenience API: hologram.route()")
print("=" * 60)

# One-liner usage
result = hologram.route(
    '/home/garret-sutherland/claude-memory-turn23/.claude',
    'What is the lighthouse resurrection mechanism?'
)

print(f"\nResult keys: {list(result.keys())}")
print(f"Turn: {result['turn']}")
print(f"Activated: {len(result['activated'])} files")
print(f"HOT: {result['hot'][:3]}")
print(f"WARM: {result['warm'][:3]}")

print(f"\n--- Injection Preview (first 400 chars) ---")
print(result['injection'][:400])
print("...")

print("\n" + "=" * 60)
print("Convenience API works! ✅")
print("=" * 60)
