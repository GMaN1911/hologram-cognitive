# SCC Impact Analysis: True SCC vs. Mutual Clusters

## Executive Summary

**Current State:** `find_mutual_clusters()` finds bidirectional pairs (A↔B) but NOT transitive cycles (A→B→C→A).

**Question:** Would implementing true SCC (Tarjan/Kosaraju) help or hurt?

**Answer:** **NEUTRAL to SLIGHTLY POSITIVE** - True SCC would be theoretically correct and provide better diagnostics with no performance penalty, but has **ZERO impact on routing behavior** since clusters are only used for statistics.

---

## Current Implementation Analysis

### What `find_mutual_clusters()` Does

```python
# Current approach in dag.py:246-287
def find_mutual_clusters(adjacency):
    """Finds bidirectional edges only."""
    # For each node, finds neighbors with mutual references
    # A→B AND B→A = clustered
    # A→B→C→A = NOT detected as cluster (missing transitivity)
```

**Example:**
```
Graph: A→B→C→A (true SCC with 3 nodes)
Current: Finds {A,B}, {B,C}, {C,A} if there are mutual edges
True SCC: Would find {A,B,C} as single component
```

### Where It's Used

**ONLY in `summarize_dag()` (dag.py:312)** - for diagnostic output:

```python
return {
    'total_nodes': ...,
    'total_edges': ...,
    'mutual_clusters': find_mutual_clusters(adjacency),  # ← ONLY HERE
}
```

**NOT used in routing logic:**
- ✅ Edge-weighted priority calculation (router.py:208-264)
- ✅ Pressure propagation (system.py)
- ✅ Context injection (router.py:266-400)
- ❌ Cluster detection (no impact on behavior)

---

## True SCC: Pros and Cons

### ✅ Advantages

1. **Theoretically Correct**
   - Proper definition of strongly connected components
   - Finds maximal components (all reachable nodes)
   - Better reflects actual cluster structure

2. **Better Diagnostics**
   - Would identify transitive cycles: A→B→C→A
   - More accurate "co-activation groups"
   - Useful for understanding documentation structure

3. **Same Performance**
   - Tarjan: O(V + E) - same as current
   - Kosaraju: O(V + E) - same as current
   - No computational penalty

4. **Future-Proof**
   - If clusters are ever used for routing decisions, true SCC would be correct
   - Potential features: cluster-level pressure, group activation

### ❌ Disadvantages

1. **Implementation Complexity**
   - Current: ~30 lines, simple BFS
   - Tarjan: ~50 lines, requires stack + indices
   - Kosaraju: ~40 lines, requires two DFS passes

2. **Over-Clustering Risk**
   - In documentation: A mentions B, B mentions C, C mentions A
   - True SCC treats as single unit
   - But files might not be as tightly coupled as algorithm suggests

3. **Reduced Granularity**
   - Mutual clusters: Shows direct pairs (A↔B, B↔C)
   - True SCC: Merges into single {A,B,C}
   - Loss of detail about actual edge structure

4. **Zero Impact on Current Behavior**
   - Since only used for statistics, no functional benefit
   - Pure cosmetic change to diagnostic output

---

## Empirical Analysis

### Typical Documentation Graph Characteristics

Based on `examples/migration_example.py` and typical usage:

1. **Sparse Graphs**
   - 10-100 files typical
   - 1-5 edges per file average
   - Few dense clusters

2. **Reference Patterns**
   - Direct mentions: "See modules/auth.md"
   - Bidirectional: auth.md ↔ user.md (mutual references)
   - Transitive: Less common in docs

3. **Expected SCC Structure**
   - Most files: Singleton SCCs (no cycles)
   - Some files: Small SCCs (2-3 files in tight coupling)
   - Rare: Large SCCs (5+ files in full cycle)

### Test Case: Would True SCC Find More?

```
Example Graph (from migration_example.py):
orin.md → pipe-to-orin.md
orin.md → t3-telos.md
t3-telos.md → orin.md (mentions "uses orin for perception")

Current: Finds {orin.md, t3-telos.md} (bidirectional)
True SCC: Same result (only 2 nodes in cycle)

If we had:
orin.md → t3-telos.md → pipeline.md → orin.md

Current: Might find pairs {orin,t3}, {t3,pipeline} if bidirectional
True SCC: Would find {orin, t3-telos, pipeline} as single component
```

**Verdict:** True SCC would find *some* additional clusters, but likely not many in typical documentation.

---

## Recommendation

### Short Term: **KEEP CURRENT**

**Rationale:**
1. Zero functional impact (only affects diagnostic output)
2. Simpler code, easier to understand
3. Working fine for current use case
4. No performance issues to solve

### Long Term: **CONSIDER TRUE SCC IF...**

Implement true SCC if:
1. ✅ Planning to use clusters for routing decisions
2. ✅ Want to identify tightly-coupled doc groups for refactoring
3. ✅ Building cluster-level features (group activation, cluster pressure)
4. ✅ Documentation grows large (100+ files with complex cycles)

### Implementation Priority: **LOW**

- Not blocking any features
- Not causing bugs
- Not a performance bottleneck
- Pure nice-to-have for completeness

---

## Proposed Approach

If implementing true SCC, use **Tarjan's algorithm** (preferred):

**Advantages:**
- Single pass (vs. Kosaraju's two passes)
- More efficient for dense graphs
- Standard textbook algorithm
- Well-tested implementations available

**Implementation:**
```python
def find_true_sccs(adjacency: Dict[str, Set[str]]) -> List[Set[str]]:
    """
    Find strongly connected components using Tarjan's algorithm.
    Returns list of SCCs, each as a set of file paths.
    """
    # ~50 lines: index tracking, stack, recursive DFS
    # Returns: [{'A', 'B', 'C'}, {'D'}, {'E', 'F'}]
```

---

## Conclusion

### Does True SCC Help or Hurt?

**Answer: NEUTRAL (slight lean toward HELP)**

**Helps:**
- ✅ More theoretically correct
- ✅ Better diagnostics
- ✅ No performance cost
- ✅ Future-proof for potential features

**Hurts:**
- ❌ More complex code
- ❌ No immediate functional benefit
- ❌ Risk of over-clustering
- ❌ Development time cost

### Final Recommendation

**For v0.1.0:** Keep current implementation
- It works fine
- Focus on features that actually impact routing behavior
- Document the limitation clearly (already done)

**For v0.2.0+:** Consider true SCC if:
- Adding cluster-based features
- User reports missing cluster detections
- Growing codebase shows more transitive cycles

---

## Test Plan (If Implementing)

1. **Unit Tests**
   - Known SCC examples: A→B→C→A
   - Compare output with current `find_mutual_clusters()`
   - Verify all components found

2. **Real-World Test**
   - Run on actual .claude/ directories
   - Compare cluster counts: current vs. true SCC
   - Measure size distribution of SCCs

3. **Performance Test**
   - Benchmark on large graphs (1000+ nodes)
   - Verify O(V+E) complexity
   - Compare wall-clock time vs. current

4. **Integration Test**
   - Verify `summarize_dag()` output
   - Check no breaking changes to API
   - Validate JSON serialization

---

**Generated:** 2026-01-13
**Version:** hologram-cognitive v0.1.0
**Branch:** claude/evaluate-scc-impact-RSoqk
