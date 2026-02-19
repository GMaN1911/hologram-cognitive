import sys
import os

# Add the project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hologram.dag import get_incoming_edges

def test_get_incoming_edges_empty():
    """Test with an empty graph."""
    print("Running test_get_incoming_edges_empty...")
    assert get_incoming_edges({}) == {}
    print("✅ Passed")

def test_get_incoming_edges_single_node_no_edges():
    """Test with a single node and no edges."""
    print("Running test_get_incoming_edges_single_node_no_edges...")
    assert get_incoming_edges({"A": set()}) == {"A": set()}
    print("✅ Passed")

def test_get_incoming_edges_simple_edge():
    """Test with a simple directed edge A -> B."""
    print("Running test_get_incoming_edges_simple_edge...")
    adjacency = {"A": {"B"}, "B": set()}
    expected = {"A": set(), "B": {"A"}}
    assert get_incoming_edges(adjacency) == expected
    print("✅ Passed")

def test_get_incoming_edges_multiple_incoming():
    """Test with multiple incoming edges A -> C, B -> C."""
    print("Running test_get_incoming_edges_multiple_incoming...")
    adjacency = {"A": {"C"}, "B": {"C"}, "C": set()}
    expected = {"A": set(), "B": set(), "C": {"A", "B"}}
    assert get_incoming_edges(adjacency) == expected
    print("✅ Passed")

def test_get_incoming_edges_circular():
    """Test with a circular reference A -> B, B -> A."""
    print("Running test_get_incoming_edges_circular...")
    adjacency = {"A": {"B"}, "B": {"A"}}
    expected = {"A": {"B"}, "B": {"A"}}
    assert get_incoming_edges(adjacency) == expected
    print("✅ Passed")

def test_get_incoming_edges_self_loop():
    """Test with a self-loop A -> A."""
    print("Running test_get_incoming_edges_self_loop...")
    adjacency = {"A": {"A"}}
    expected = {"A": {"A"}}
    assert get_incoming_edges(adjacency) == expected
    print("✅ Passed")

def test_get_incoming_edges_disconnected():
    """Test with disconnected components."""
    print("Running test_get_incoming_edges_disconnected...")
    adjacency = {"A": {"B"}, "B": set(), "C": {"D"}, "D": set()}
    expected = {"A": set(), "B": {"A"}, "C": set(), "D": {"C"}}
    assert get_incoming_edges(adjacency) == expected
    print("✅ Passed")

def test_get_incoming_edges_target_not_in_keys():
    """
    Test when a target node is not present in the adjacency keys.
    This helps identify if the function handles all nodes in the graph.
    """
    print("Running test_get_incoming_edges_target_not_in_keys...")
    adjacency = {"A": {"B"}}
    # If B is not in keys, should it be in the output?
    # Current implementation ignores it.
    result = get_incoming_edges(adjacency)
    assert "B" in result
    assert result["B"] == {"A"}
    print("✅ Passed")

if __name__ == "__main__":
    tests = [
        test_get_incoming_edges_empty,
        test_get_incoming_edges_single_node_no_edges,
        test_get_incoming_edges_simple_edge,
        test_get_incoming_edges_multiple_incoming,
        test_get_incoming_edges_circular,
        test_get_incoming_edges_self_loop,
        test_get_incoming_edges_disconnected,
        test_get_incoming_edges_target_not_in_keys,
    ]

    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"❌ Failed: {test.__name__}")
            failed += 1
        except Exception as e:
            print(f"💥 Error in {test.__name__}: {e}")
            failed += 1

    if failed == 0:
        print("\nAll tests passed! ✨")
        sys.exit(0)
    else:
        print(f"\n{failed} tests failed. 🚧")
        sys.exit(1)
