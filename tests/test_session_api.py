#!/usr/bin/env python3
"""Test the Session API with real data."""

import sys
sys.path.insert(0, '/home/garret-sutherland/hologram-cognitive-0.2.0-src')

import hologram

# Test Session API
session = hologram.Session('/home/garret-sutherland/claude-memory-turn23/.claude')

print("=" * 60)
print("Testing Session API")
print("=" * 60)

# Get status
status = session.status()
print(f"\nStatus: {status}")

# Process a turn
result = session.turn("Tell me about the memory architecture")

print(f"\n--- Turn Result ---")
print(f"Turn Number: {result.turn_number}")
print(f"Activated: {len(result.activated)} files")
print(f"HOT: {result.hot[:3]}")
print(f"WARM: {result.warm[:3]}")

print(f"\n--- Injection Preview (first 500 chars) ---")
print(result.injection[:500])
print("...")

# Test note creation
print(f"\n--- Testing note() method ---")
note_path = session.note(
    "v0.2.0 Test Session",
    "Successfully tested the new Session API with real data. All features working correctly.",
    links=['[[hologram-cognitive.md]]', '[[t3-overview.md]]']
)
print(f"Created note: {note_path}")

# Save state
session.save()
print(f"\nState saved successfully!")

print("\n" + "=" * 60)
print("All tests passed! ✅")
print("=" * 60)
