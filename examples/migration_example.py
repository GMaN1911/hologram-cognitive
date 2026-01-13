#!/usr/bin/env python3
"""
Migration Example: keywords.json → Hologram

Shows how Hologram auto-discovers the same relationships
you manually configured in co_activation.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from hologram import HologramRouter, CognitiveSystem, build_dag
from hologram.dag import summarize_dag

# Your existing keywords.json co_activation (subset)
MANUAL_CO_ACTIVATION = {
    "systems/orin.md": [
        "integrations/pipe-to-orin.md",
        "modules/t3-telos.md",
        "modules/ppe-anticipatory-coherence.md"
    ],
    "modules/t3-telos.md": [
        "modules/cvmp-transformer.md",
        "modules/anticipatory-coherence.md",
        "modules/pipeline.md",
    ],
    "modules/pipeline.md": [
        "modules/intelligence.md",
        "modules/es-ac.md",
        "modules/t3-telos.md"
    ],
}

# Simulated file content (in real usage, read from .claude/)
FILES = {
    "systems/orin.md": """
        # Orin Sensory Cortex
        Layer 0 perception on Jetson Orin.
        Uses pipe-to-orin for data flow.
        Connected to t3-telos for trajectory.
        PPE (ppe-anticipatory-coherence) runs here.
    """,
    "modules/t3-telos.md": """
        # T³ Telos
        Toroidal Tesseract Transformer.
        Uses cvmp-transformer for consciousness.
        Integrates with anticipatory-coherence.
        Pipeline layer 4 integration.
    """,
    "modules/pipeline.md": """
        # Pipeline System
        8-layer refined_pipeline.
        Uses intelligence for reasoning.
        ES-AC for emotional learning.
        T3-telos for trajectory.
    """,
    "integrations/pipe-to-orin.md": "Pipe to Orin integration.",
    "modules/ppe-anticipatory-coherence.md": "PPE runtime.",
    "modules/cvmp-transformer.md": "CVMP transformer model.",
    "modules/anticipatory-coherence.md": "Anticipatory coherence framework.",
    "modules/intelligence.md": "Intelligence module.",
    "modules/es-ac.md": "ES-AC emotional learning.",
}


def compare_discovery():
    """Compare manual config vs auto-discovery."""
    
    # Build DAG from content
    discovered = build_dag(FILES)
    
    print("=" * 60)
    print("MIGRATION COMPARISON: Manual vs Discovered")
    print("=" * 60)
    
    total_manual = 0
    total_discovered_matching = 0
    total_extra = 0
    
    for source, manual_targets in MANUAL_CO_ACTIVATION.items():
        discovered_targets = discovered.get(source, set())
        
        matched = set(manual_targets) & discovered_targets
        missed = set(manual_targets) - discovered_targets
        extra = discovered_targets - set(manual_targets)
        
        total_manual += len(manual_targets)
        total_discovered_matching += len(matched)
        total_extra += len(extra)
        
        print(f"\n📄 {source}")
        print(f"   Manual config: {len(manual_targets)} edges")
        print(f"   Discovered:    {len(discovered_targets)} edges")
        
        if matched:
            print(f"   ✅ Matched: {list(matched)}")
        if missed:
            print(f"   ❌ Missed:  {list(missed)}")
        if extra:
            print(f"   ➕ Extra:   {list(extra)}")
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    recall = total_discovered_matching / total_manual * 100 if total_manual else 0
    print(f"""
    Manual edges configured:     {total_manual}
    Auto-discovered (matching):  {total_discovered_matching}
    Extra edges found:           {total_extra}
    
    Recall: {recall:.0f}%
    
    {'✅ DAG discovery can replace keywords.json!' if recall >= 80 else '⚠️ Some edges need richer content.'}
    """)


def show_usage():
    """Show how to use Hologram in practice."""
    
    print("\n" + "=" * 60)
    print("USAGE EXAMPLE")
    print("=" * 60)
    
    # Create system
    system = CognitiveSystem()
    for path, content in FILES.items():
        system.add_file(path, content)
    
    # Simulate queries
    from hologram import process_turn, get_context
    
    queries = [
        "work on orin sensory",
        "t3-telos trajectory",
        "pipeline integration",
    ]
    
    for query in queries:
        record = process_turn(system, query)
        context = get_context(system)
        
        print(f"\n🔍 Query: \"{query}\"")
        print(f"   Activated: {record.activated[:3]}...")
        print(f"   🔥 HOT: {len(context['HOT'])}")
        print(f"   🌡️  WARM: {len(context['WARM'])}")
        print(f"   ❄️  COLD: {len(context['COLD'])}")


if __name__ == "__main__":
    compare_discovery()
    show_usage()
    
    print("\n" + "=" * 60)
    print("NEXT STEPS")
    print("=" * 60)
    print("""
    1. Copy hologram/ to your claude-cognitive installation
    2. Update hooks to use: python -m hologram.router
    3. Delete keywords.json (no longer needed!)
    4. Enjoy zero-config context routing
    """)
