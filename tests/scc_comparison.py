#!/usr/bin/env python3
"""
SCC Comparison: Current Mutual Clusters vs. True SCC

Demonstrates the difference between the current implementation
and a true strongly connected component algorithm.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hologram.dag import find_mutual_clusters
from typing import Dict, Set, List


def tarjan_scc(adjacency: Dict[str, Set[str]]) -> List[Set[str]]:
    """
    Find true strongly connected components using Tarjan's algorithm.

    A strongly connected component is a maximal set of nodes where
    every node can reach every other node in the set.
    """
    index_counter = [0]
    stack = []
    lowlinks = {}
    index = {}
    on_stack = set()
    sccs = []

    def strongconnect(node):
        index[node] = index_counter[0]
        lowlinks[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack.add(node)

        # Consider successors
        for successor in adjacency.get(node, set()):
            if successor not in index:
                strongconnect(successor)
                lowlinks[node] = min(lowlinks[node], lowlinks[successor])
            elif successor in on_stack:
                lowlinks[node] = min(lowlinks[node], index[successor])

        # If node is a root node, pop the stack
        if lowlinks[node] == index[node]:
            scc = set()
            while True:
                successor = stack.pop()
                on_stack.remove(successor)
                scc.add(successor)
                if successor == node:
                    break
            if len(scc) > 1:  # Only include multi-node SCCs
                sccs.append(scc)

    for node in adjacency:
        if node not in index:
            strongconnect(node)

    return sccs


def compare_algorithms():
    """Compare current mutual clusters vs. true SCC."""

    # Test Case 1: Simple bidirectional pair
    graph1 = {
        'A': {'B'},
        'B': {'A'},
        'C': set(),
    }

    # Test Case 2: Transitive cycle (A→B→C→A)
    graph2 = {
        'A': {'B'},
        'B': {'C'},
        'C': {'A'},
    }

    # Test Case 3: Mixed - one cycle + bidirectional pairs
    graph3 = {
        'doc1': {'doc2'},
        'doc2': {'doc3'},
        'doc3': {'doc1'},
        'auth': {'user'},
        'user': {'auth'},
        'config': set(),
    }

    # Test Case 4: Complex - nested cycles
    graph4 = {
        'A': {'B', 'C'},
        'B': {'C'},
        'C': {'A'},
        'D': {'E'},
        'E': {'F'},
        'F': {'D'},
        'G': {'H'},
        'H': {'G'},
    }

    test_cases = [
        ("Simple Bidirectional Pair", graph1),
        ("Transitive Cycle (A→B→C→A)", graph2),
        ("Mixed Cycles", graph3),
        ("Complex Nested Cycles", graph4),
    ]

    print("=" * 70)
    print("SCC ALGORITHM COMPARISON")
    print("=" * 70)

    for name, graph in test_cases:
        print(f"\n📊 Test Case: {name}")
        print(f"   Graph: {dict_to_string(graph)}")

        mutual = find_mutual_clusters(graph)
        true_scc = tarjan_scc(graph)

        print(f"\n   Current (Mutual Clusters):")
        if mutual:
            for cluster in mutual:
                print(f"      {sorted(cluster)}")
        else:
            print(f"      (none found)")

        print(f"\n   True SCC (Tarjan):")
        if true_scc:
            for scc in true_scc:
                print(f"      {sorted(scc)}")
        else:
            print(f"      (none found)")

        # Analysis
        same = set(map(frozenset, mutual)) == set(map(frozenset, true_scc))
        if same:
            print(f"\n   ✅ Results IDENTICAL")
        else:
            print(f"\n   ⚠️  Results DIFFERENT")
            print(f"      Mutual found {len(mutual)} clusters")
            print(f"      True SCC found {len(true_scc)} components")


def dict_to_string(graph):
    """Format graph dict for display."""
    parts = []
    for src, targets in sorted(graph.items()):
        if targets:
            for tgt in sorted(targets):
                parts.append(f"{src}→{tgt}")
    return ", ".join(parts) if parts else "(no edges)"


def analyze_real_world():
    """Analyze with realistic documentation graph."""

    print("\n" + "=" * 70)
    print("REALISTIC DOCUMENTATION GRAPH")
    print("=" * 70)

    # Based on claude-cognitive typical structure
    docs = {
        'systems/orin.md': {'integrations/pipe-to-orin.md', 'modules/t3-telos.md'},
        'integrations/pipe-to-orin.md': {'systems/orin.md'},  # Mutual with orin
        'modules/t3-telos.md': {'systems/orin.md', 'modules/pipeline.md'},  # Cycle back
        'modules/pipeline.md': {'modules/intelligence.md', 'modules/t3-telos.md'},
        'modules/intelligence.md': {'modules/pipeline.md'},  # Creates larger cycle
        'modules/auth.md': {'modules/user.md'},
        'modules/user.md': {'modules/auth.md'},  # Simple bidirectional
        'README.md': set(),  # Singleton
    }

    print(f"\nGraph structure ({len(docs)} files):")
    for src, targets in sorted(docs.items()):
        if targets:
            print(f"   {src}")
            for tgt in sorted(targets):
                print(f"      → {tgt}")

    mutual = find_mutual_clusters(docs)
    true_scc = tarjan_scc(docs)

    print(f"\n📈 Results:")
    print(f"\n   Current (Mutual Clusters): {len(mutual)} clusters")
    for i, cluster in enumerate(mutual, 1):
        print(f"      {i}. {{{', '.join(sorted(cluster))}}}")

    print(f"\n   True SCC: {len(true_scc)} components")
    for i, scc in enumerate(true_scc, 1):
        print(f"      {i}. {{{', '.join(sorted(scc))}}}")

    # Impact analysis
    print(f"\n📊 Impact Analysis:")

    if len(true_scc) > len(mutual):
        print(f"   ⚠️  True SCC found {len(true_scc) - len(mutual)} MORE components")
        print(f"      (detects transitive cycles that mutual clusters miss)")
    elif len(true_scc) < len(mutual):
        print(f"   ⚠️  True SCC found {len(mutual) - len(true_scc)} FEWER components")
        print(f"      (merges related clusters into larger components)")
    else:
        print(f"   ✅ Same number of components")

    # Check for differences in membership
    mutual_nodes = set()
    for cluster in mutual:
        mutual_nodes.update(cluster)

    scc_nodes = set()
    for scc in true_scc:
        scc_nodes.update(scc)

    print(f"\n   Files in clusters:")
    print(f"      Mutual: {len(mutual_nodes)} files")
    print(f"      True SCC: {len(scc_nodes)} files")

    if mutual_nodes != scc_nodes:
        print(f"      ⚠️ Different files clustered!")
        only_mutual = mutual_nodes - scc_nodes
        only_scc = scc_nodes - mutual_nodes
        if only_mutual:
            print(f"      Only in mutual: {only_mutual}")
        if only_scc:
            print(f"      Only in SCC: {only_scc}")


def main():
    """Run all comparisons."""
    compare_algorithms()
    analyze_real_world()

    print("\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)
    print("""
True SCC differs from mutual clusters when:
  1. Transitive cycles exist (A→B→C→A)
  2. Multiple paths connect nodes
  3. Complex graph structures

For documentation graphs:
  - Mutual clusters: Conservative, finds direct bidirectional pairs
  - True SCC: Complete, finds all nodes that can reach each other

Impact on hologram-cognitive:
  - Currently: ZERO (clusters only used for statistics)
  - Future: Could enable cluster-level features
  - Cost: ~20 more lines of code, same O(V+E) performance
    """)


if __name__ == "__main__":
    main()
