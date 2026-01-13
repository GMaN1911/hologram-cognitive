"""
Comparison Test: Linear vs Toroidal Decay Dynamics

Evaluates the behavioral differences between:
1. Linear Decay: Files decay to 0.0 and stay dead (current default)
2. Toroidal Decay: Files resurrect after long dormancy (experimental)

This tests the core question: Does curiosity-driven resurrection improve
context relevance or just create noise?
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from hologram import CognitiveSystem, EdgeDiscoveryConfig, PressureConfig
from hologram.system import process_turn
from hologram.pressure import get_pressure_stats


def create_test_system(use_toroidal: bool = False) -> CognitiveSystem:
    """Create a test system with sample files."""

    # Create pressure config
    pressure_config = PressureConfig(
        use_toroidal_decay=use_toroidal,
        resurrection_threshold=0.01,
        resurrection_pressure=0.8,
        resurrection_cooldown=100,
        decay_rate=0.85,
        enable_conservation=True,
        total_pressure_budget=10.0,
    )

    # Create system with custom pressure config
    system = CognitiveSystem(
        dag_config=EdgeDiscoveryConfig(),
        pressure_config=pressure_config,
    )

    # Add sample documentation files
    system.add_file('modules/auth.md', """
# Authentication Module
Uses session tokens and integrates with user management.
See also: modules/user.md, modules/session.md
""")

    system.add_file('modules/user.md', """
# User Management
Handles user accounts, profiles, and permissions.
Related: modules/auth.md
""")

    system.add_file('modules/session.md', """
# Session Management
Tracks active sessions and handles timeouts.
Requires: modules/auth.md
""")

    system.add_file('modules/database.md', """
# Database Layer
Core persistence layer used by all modules.
""")

    system.add_file('guides/quickstart.md', """
# Quickstart Guide
Get started with authentication: see modules/auth.md
""")

    system.add_file('archived/old-auth.md', """
# Deprecated Authentication
Old auth system, replaced by modules/auth.md
""")

    return system


def simulate_interaction_pattern(system: CognitiveSystem, turns: int = 500):
    """
    Simulate realistic interaction pattern:
    - Early turns: Focus on auth (modules/auth.md, modules/user.md)
    - Middle turns: Shift to database (modules/database.md)
    - Late turns: Return to auth (will old files resurrect in toroidal mode?)
    """

    turn_records = []

    for turn in range(turns):
        # Pattern 1: Turns 0-100 - Learning authentication
        if 0 <= turn < 100:
            if turn % 3 == 0:
                query = "How does authentication work?"  # Activates auth.md
            elif turn % 3 == 1:
                query = "What about user management?"  # Activates user.md
            else:
                query = "Session handling?"  # Activates session.md

        # Pattern 2: Turns 100-300 - Working on database
        elif 100 <= turn < 300:
            query = "Database schema and persistence"  # Activates database.md

        # Pattern 3: Turns 300-400 - Other unrelated work
        elif 300 <= turn < 400:
            query = "Quickstart guide and documentation"  # Activates quickstart.md

        # Pattern 4: Turns 400-500 - Return to authentication
        else:
            query = "Authentication security audit"  # Should reactivate auth.md
            # Question: Will old auth files resurrect in toroidal mode?

        record = process_turn(system, query)
        turn_records.append(record)

    return turn_records


def analyze_results(system: CognitiveSystem, records: list, mode_name: str):
    """Analyze and print results."""

    print(f"\n{'='*60}")
    print(f"Results: {mode_name}")
    print(f"{'='*60}\n")

    # Final pressure distribution
    stats = get_pressure_stats(system.files)
    print(f"Final Pressure Stats:")
    print(f"  Total pressure: {stats['total_pressure']:.2f}")
    print(f"  Avg pressure:   {stats['avg_pressure']:.3f}")
    print(f"  Max pressure:   {stats['max_pressure']:.3f}")
    print(f"  Min pressure:   {stats['min_pressure']:.6f}")
    print(f"  HOT files:      {stats['hot_count']}")
    print(f"  WARM files:     {stats['warm_count']}")
    print(f"  COLD files:     {stats['cold_count']}")

    # File-by-file breakdown
    print(f"\nFinal File States:")
    for path, file in sorted(system.files.items(), key=lambda x: x[1].raw_pressure, reverse=True):
        print(f"  {file.tier:4s} {file.raw_pressure:6.4f}  {path}")
        print(f"       Last activated: turn {file.last_activated}")
        if file.last_resurrected > 0:
            print(f"       Last resurrected: turn {file.last_resurrected}")

    # Resurrection events (toroidal mode only)
    resurrection_count = sum(1 for f in system.files.values() if f.last_resurrected > 0)
    if resurrection_count > 0:
        print(f"\n  Total resurrection events: {resurrection_count}")
        print(f"  Resurrected files:")
        for path, file in system.files.items():
            if file.last_resurrected > 0:
                print(f"    - {path} (turn {file.last_resurrected})")

    # Context relevance at key moments
    print(f"\nContext Relevance Analysis:")

    # Turn 0 (initial)
    print(f"  Turn 0 (initial auth query):")
    print(f"    HOT: {records[0].hot[:3]}")

    # Turn 100 (database work begins)
    print(f"  Turn 100 (switching to database):")
    print(f"    HOT: {records[100].hot[:3]}")

    # Turn 300 (unrelated work)
    print(f"  Turn 300 (unrelated work):")
    print(f"    HOT: {records[300].hot[:3]}")

    # Turn 450 (returning to auth after 350 turns away)
    print(f"  Turn 450 (returning to auth after 350 turns):")
    print(f"    HOT: {records[450].hot[:3]}")
    print(f"    Question: Did auth files resurface in toroidal mode?")


def main():
    """Run comparison test."""

    print("Decay Dynamics Comparison Test")
    print("="*60)
    print("\nSimulating 500 turns of realistic interaction...")
    print("Pattern:")
    print("  Turns 0-100:   Auth-focused work")
    print("  Turns 100-300: Database work (auth files decay)")
    print("  Turns 300-400: Unrelated work")
    print("  Turns 400-500: Return to auth (will old files resurface?)")

    # Test 1: Linear Decay (current default)
    print("\n" + "="*60)
    print("Test 1: LINEAR DECAY MODE (current default)")
    print("="*60)
    system_linear = create_test_system(use_toroidal=False)
    records_linear = simulate_interaction_pattern(system_linear, turns=500)
    analyze_results(system_linear, records_linear, "Linear Decay (No Resurrection)")

    # Test 2: Toroidal Decay (experimental)
    print("\n" + "="*60)
    print("Test 2: TOROIDAL DECAY MODE (experimental)")
    print("="*60)
    system_toroidal = create_test_system(use_toroidal=True)
    records_toroidal = simulate_interaction_pattern(system_toroidal, turns=500)
    analyze_results(system_toroidal, records_toroidal, "Toroidal Decay (With Resurrection)")

    # Comparison Summary
    print("\n" + "="*60)
    print("COMPARISON SUMMARY")
    print("="*60)

    linear_stats = get_pressure_stats(system_linear.files)
    toroidal_stats = get_pressure_stats(system_toroidal.files)

    print(f"\nPressure Conservation:")
    print(f"  Linear:   {linear_stats['total_pressure']:.2f} / 10.0")
    print(f"  Toroidal: {toroidal_stats['total_pressure']:.2f} / 10.0")

    print(f"\nContext Distribution:")
    print(f"  Linear:   HOT={linear_stats['hot_count']}, WARM={linear_stats['warm_count']}, COLD={linear_stats['cold_count']}")
    print(f"  Toroidal: HOT={toroidal_stats['hot_count']}, WARM={toroidal_stats['warm_count']}, COLD={toroidal_stats['cold_count']}")

    resurrection_count = sum(1 for f in system_toroidal.files.values() if f.last_resurrected > 0)
    print(f"\nResurrection Events (Toroidal only): {resurrection_count}")

    print(f"\nKey Question: At turn 450 (returning to auth after 350 turns away)...")
    linear_hot_450 = set(records_linear[450].hot)
    toroidal_hot_450 = set(records_toroidal[450].hot)

    print(f"  Linear HOT files:   {linear_hot_450}")
    print(f"  Toroidal HOT files: {toroidal_hot_450}")

    # Check if toroidal mode brought back auth files
    auth_files = {'modules/auth.md', 'modules/user.md', 'modules/session.md'}
    linear_has_auth = bool(linear_hot_450 & auth_files)
    toroidal_has_auth = bool(toroidal_hot_450 & auth_files)

    print(f"\n  Linear recovered auth files:   {linear_has_auth}")
    print(f"  Toroidal recovered auth files: {toroidal_has_auth}")

    if toroidal_has_auth and not linear_has_auth:
        print(f"\n  ✓ TOROIDAL WIN: Resurrection brought back relevant old context")
    elif linear_has_auth and not toroidal_has_auth:
        print(f"\n  ✓ LINEAR WIN: Normal activation was sufficient")
    else:
        print(f"\n  ≈ TIE: Both modes achieved similar results")

    print("\n" + "="*60)
    print("Test complete. Review results above.")
    print("="*60)


if __name__ == "__main__":
    main()
