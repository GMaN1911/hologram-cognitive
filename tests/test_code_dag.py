#!/usr/bin/env python3
"""
Tests for Code-Level DAG (hologram/code_dag.py)

Run with: python -m pytest tests/test_code_dag.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from hologram.code_dag import (
    CodeSymbol,
    ImportRef,
    FileSymbols,
    SymbolGraph,
    parse_python_file,
    resolve_import,
    build_symbol_graph,
    extract_code_refs,
    build_bridge_edges,
    enrich_edge_weights,
    discover_symbol_edges,
    symbol_graph_to_dict,
    symbol_graph_from_dict,
)


# =============================================================================
# AST Parser Tests
# =============================================================================

class TestParsePythonFile:

    def test_parse_function(self):
        code = '''
def foo(x: int, y: str = "hello") -> bool:
    result = bar(x)
    return result > 0
'''
        fs = parse_python_file("test.py", code)
        assert fs.parse_error is None
        assert len(fs.symbols) == 1
        sym = fs.symbols[0]
        assert sym.name == "foo"
        assert sym.kind == "function"
        assert sym.qualified_name == "test.foo"
        assert "bar" in sym.calls
        assert sym.line == 2

    def test_parse_class_with_methods(self):
        code = '''
class MyClass(BaseClass):
    def __init__(self):
        self.value = compute_thing()

    def process(self, data):
        return transform(data)
'''
        fs = parse_python_file("module.py", code)
        assert fs.parse_error is None

        # Should find: MyClass, __init__, process
        names = {s.name for s in fs.symbols}
        assert "MyClass" in names
        assert "__init__" in names
        assert "process" in names

        cls = next(s for s in fs.symbols if s.name == "MyClass")
        assert cls.kind == "class"
        assert "BaseClass" in cls.bases

        init = next(s for s in fs.symbols if s.name == "__init__")
        assert init.kind == "method"
        assert "compute_thing" in init.calls

    def test_parse_async_function(self):
        code = '''
async def fetch_data(url):
    response = await http_get(url)
    return parse_json(response)
'''
        fs = parse_python_file("async_mod.py", code)
        assert len(fs.symbols) == 1
        sym = fs.symbols[0]
        assert sym.name == "fetch_data"
        assert sym.kind == "function"
        assert "http_get" in sym.calls
        assert "parse_json" in sym.calls

    def test_parse_imports_relative(self):
        code = '''
from .pressure import apply_activation, propagate_pressure
from ..utils import helper
'''
        fs = parse_python_file("hologram/system.py", code)
        assert len(fs.imports) == 2

        imp1 = fs.imports[0]
        assert imp1.module == "pressure"
        assert imp1.is_relative is True
        assert imp1.level == 1
        assert "apply_activation" in imp1.names
        assert "propagate_pressure" in imp1.names

        imp2 = fs.imports[1]
        assert imp2.module == "utils"
        assert imp2.is_relative is True
        assert imp2.level == 2

    def test_parse_imports_absolute(self):
        code = '''
import json
import os.path
from hologram.pressure import apply_activation
'''
        fs = parse_python_file("test.py", code)
        assert len(fs.imports) == 3

        abs_imp = next(i for i in fs.imports if i.module == "hologram.pressure")
        assert abs_imp.is_relative is False
        assert "apply_activation" in abs_imp.names

    def test_parse_syntax_error_graceful(self):
        code = '''
def broken(
    # missing closing paren and colon
'''
        fs = parse_python_file("broken.py", code)
        assert fs.parse_error is not None
        assert "SyntaxError" in fs.parse_error
        assert fs.symbols == []
        assert fs.imports == []

    def test_parse_decorators(self):
        code = '''
@property
def value(self):
    return self._value

@staticmethod
def create():
    pass
'''
        fs = parse_python_file("deco.py", code)
        syms = {s.name: s for s in fs.symbols}
        assert "property" in syms["value"].decorators
        assert "staticmethod" in syms["create"].decorators

    def test_parse_empty_file(self):
        fs = parse_python_file("empty.py", "")
        assert fs.parse_error is None
        assert fs.symbols == []
        assert fs.imports == []

    def test_content_hash_changes(self):
        fs1 = parse_python_file("test.py", "def foo(): pass")
        fs2 = parse_python_file("test.py", "def bar(): pass")
        assert fs1.content_hash != fs2.content_hash

    def test_content_hash_stable(self):
        code = "def foo(): pass"
        fs1 = parse_python_file("test.py", code)
        fs2 = parse_python_file("test.py", code)
        assert fs1.content_hash == fs2.content_hash


# =============================================================================
# Import Resolution Tests
# =============================================================================

class TestResolveImport:

    def test_relative_same_package(self):
        imp = ImportRef(module="pressure", names=["apply_activation"],
                        is_relative=True, level=1)
        result = resolve_import(imp, "hologram/system.py",
                                {"hologram/pressure.py", "hologram/system.py"})
        assert result == "hologram/pressure.py"

    def test_relative_parent_package(self):
        imp = ImportRef(module="utils", names=["helper"],
                        is_relative=True, level=2)
        result = resolve_import(imp, "hologram/mcp/server.py",
                                {"hologram/utils.py", "hologram/mcp/server.py"})
        assert result == "hologram/utils.py"

    def test_relative_init(self):
        imp = ImportRef(module="", names=["CognitiveFile"],
                        is_relative=True, level=1)
        result = resolve_import(imp, "hologram/system.py",
                                {"hologram/__init__.py", "hologram/system.py"})
        assert result == "hologram/__init__.py"

    def test_absolute_import(self):
        imp = ImportRef(module="hologram.pressure", names=["apply_activation"],
                        is_relative=False, level=0)
        result = resolve_import(imp, "scripts/run.py",
                                {"hologram/pressure.py", "scripts/run.py"})
        assert result == "hologram/pressure.py"

    def test_external_import_returns_none(self):
        imp = ImportRef(module="json", names=["loads"],
                        is_relative=False, level=0)
        result = resolve_import(imp, "test.py", {"test.py"})
        assert result is None

    def test_numpy_returns_none(self):
        imp = ImportRef(module="numpy", names=["ndarray"],
                        is_relative=False, level=0)
        result = resolve_import(imp, "test.py", {"test.py"})
        assert result is None


# =============================================================================
# Symbol Graph Builder Tests
# =============================================================================

class TestBuildSymbolGraph:

    def test_basic_graph(self):
        files = {
            "a.py": "from b import helper\ndef main():\n    helper()\n",
            "b.py": "def helper():\n    return 42\n",
        }
        graph = build_symbol_graph(files)
        assert "a.py" in graph.file_symbols
        assert "b.py" in graph.file_symbols
        assert "helper" in graph.symbol_index
        assert "b.py" in graph.symbol_index["helper"]

    def test_cross_file_edges(self):
        files = {
            "caller.py": "from lib import func_a, func_b\ndef run():\n    func_a()\n    func_b()\n",
            "lib.py": "def func_a(): pass\ndef func_b(): pass\n",
        }
        graph = build_symbol_graph(files)
        assert "caller.py" in graph.cross_file_edges
        assert "lib.py" in graph.cross_file_edges["caller.py"]
        # 2 imports + 2 call matches = at least 4 refs
        assert graph.cross_file_edges["caller.py"]["lib.py"] >= 4

    def test_inheritance_edges(self):
        files = {
            "child.py": "from base import BaseClass\nclass Child(BaseClass):\n    pass\n",
            "base.py": "class BaseClass:\n    pass\n",
        }
        graph = build_symbol_graph(files)
        assert "child.py" in graph.cross_file_edges
        assert "base.py" in graph.cross_file_edges["child.py"]
        # Inheritance counts as 3 per base
        assert graph.cross_file_edges["child.py"]["base.py"] >= 3

    def test_no_self_edges(self):
        files = {
            "mod.py": "def foo(): bar()\ndef bar(): foo()\n",
        }
        graph = build_symbol_graph(files)
        # Self-calls within same file should not create cross-file edges
        assert "mod.py" not in graph.cross_file_edges.get("mod.py", {})

    def test_skips_non_python(self):
        files = {
            "readme.md": "# Hello\nThis is docs",
            "code.py": "def hello(): pass",
        }
        graph = build_symbol_graph(files)
        assert "readme.md" not in graph.file_symbols
        assert "code.py" in graph.file_symbols

    def test_parse_error_graceful(self):
        files = {
            "good.py": "def foo(): pass\n",
            "bad.py": "def broken(\n",  # syntax error
        }
        graph = build_symbol_graph(files)
        assert graph.file_symbols["bad.py"].parse_error is not None
        assert graph.file_symbols["good.py"].parse_error is None
        assert "foo" in graph.symbol_index


# =============================================================================
# Doc-Code Bridge Tests
# =============================================================================

class TestExtractCodeRefs:

    def test_backtick_refs(self):
        doc = "Use `apply_activation` to boost pressure on activated files."
        known = {"apply_activation", "propagate_pressure", "apply_decay"}
        refs = extract_code_refs(doc, known)
        assert "apply_activation" in refs
        assert "propagate_pressure" not in refs

    def test_call_syntax_refs(self):
        doc = "Call propagate_pressure() after activation."
        known = {"propagate_pressure", "apply_decay"}
        refs = extract_code_refs(doc, known)
        assert "propagate_pressure" in refs

    def test_bare_underscore_name(self):
        doc = "The apply_activation function handles this."
        known = {"apply_activation"}
        refs = extract_code_refs(doc, known)
        assert "apply_activation" in refs

    def test_bare_pascal_case(self):
        doc = "The CognitiveFile class stores file state."
        known = {"CognitiveFile", "CognitiveSystem"}
        refs = extract_code_refs(doc, known)
        assert "CognitiveFile" in refs
        assert "CognitiveSystem" not in refs

    def test_ignores_short_names(self):
        doc = "We use foo and bar here."
        known = {"foo", "bar"}
        refs = extract_code_refs(doc, known, min_name_length=4)
        assert len(refs) == 0

    def test_ignores_doc_stopwords(self):
        doc = "The file type is list."
        known = {"file", "type", "list"}
        refs = extract_code_refs(doc, known)
        assert len(refs) == 0

    def test_dotted_references(self):
        doc = "Access system.process_turn to handle routing."
        known = {"process_turn", "apply_decay"}
        refs = extract_code_refs(doc, known)
        # process_turn should be found via dotted ref AND bare underscore match
        assert "process_turn" in refs
        assert "apply_decay" not in refs

    def test_multiple_ref_types(self):
        doc = """
Use `apply_activation` for boosting. Then call propagate_pressure()
to spread through the DAG. The CognitiveFile class holds state.
"""
        known = {"apply_activation", "propagate_pressure", "CognitiveFile", "apply_decay"}
        refs = extract_code_refs(doc, known)
        assert "apply_activation" in refs
        assert "propagate_pressure" in refs
        assert "CognitiveFile" in refs
        assert "apply_decay" not in refs


class TestBuildBridgeEdges:

    def test_bridge_connects_doc_to_code(self):
        doc_files = {
            "docs/arch.md": "Use `apply_activation` and `propagate_pressure` for routing.",
        }
        graph = SymbolGraph(
            symbol_index={
                "apply_activation": ["hologram/pressure.py"],
                "propagate_pressure": ["hologram/pressure.py"],
                "apply_decay": ["hologram/pressure.py"],
            }
        )
        bridge = build_bridge_edges(doc_files, graph)
        assert "docs/arch.md" in bridge
        assert "hologram/pressure.py" in bridge["docs/arch.md"]

    def test_bridge_multiple_targets(self):
        doc_files = {
            "README.md": "`CognitiveSystem` uses `build_dag` for edges.",
        }
        graph = SymbolGraph(
            symbol_index={
                "CognitiveSystem": ["hologram/system.py"],
                "build_dag": ["hologram/dag.py"],
            }
        )
        bridge = build_bridge_edges(doc_files, graph)
        targets = bridge["README.md"]
        assert "hologram/system.py" in targets
        assert "hologram/dag.py" in targets

    def test_bridge_no_match(self):
        doc_files = {
            "unrelated.md": "This doc mentions nothing about code.",
        }
        graph = SymbolGraph(
            symbol_index={"apply_activation": ["pressure.py"]}
        )
        bridge = build_bridge_edges(doc_files, graph)
        assert "unrelated.md" not in bridge


# =============================================================================
# Edge Weight Enrichment Tests
# =============================================================================

class TestEnrichEdgeWeights:

    def test_adds_bonus(self):
        base = {"a.py": {"b.py": 1.5}}
        graph = SymbolGraph(cross_file_edges={"a.py": {"b.py": 4}})
        enriched = enrich_edge_weights(base, graph)
        # 4 refs * 0.15 = 0.6 bonus
        assert enriched["a.py"]["b.py"] == pytest.approx(1.5 + 0.6)

    def test_capped_at_max(self):
        base = {"a.py": {"b.py": 1.0}}
        graph = SymbolGraph(cross_file_edges={"a.py": {"b.py": 100}})
        enriched = enrich_edge_weights(base, graph)
        # 100 * 0.15 = 15, capped at 2.0
        assert enriched["a.py"]["b.py"] == pytest.approx(1.0 + 2.0)

    def test_new_edge_from_symbols(self):
        base = {"a.py": {"c.py": 1.0}}
        graph = SymbolGraph(cross_file_edges={"a.py": {"b.py": 2}})
        enriched = enrich_edge_weights(base, graph)
        # New edge a.py→b.py discovered by symbols
        assert "b.py" in enriched["a.py"]
        assert enriched["a.py"]["b.py"] == pytest.approx(1.0 + 0.3)

    def test_preserves_existing(self):
        base = {"a.py": {"c.py": 2.0}}
        graph = SymbolGraph(cross_file_edges={})
        enriched = enrich_edge_weights(base, graph)
        assert enriched["a.py"]["c.py"] == pytest.approx(2.0)


class TestDiscoverSymbolEdges:

    def test_extracts_adjacency(self):
        graph = SymbolGraph(cross_file_edges={
            "a.py": {"b.py": 3, "c.py": 1},
            "b.py": {"c.py": 2},
        })
        adj = discover_symbol_edges(graph)
        assert adj["a.py"] == {"b.py", "c.py"}
        assert adj["b.py"] == {"c.py"}


# =============================================================================
# Serialization Tests
# =============================================================================

class TestSerialization:

    def test_round_trip(self):
        graph = SymbolGraph(
            file_symbols={
                "test.py": FileSymbols(
                    file_path="test.py",
                    symbols=[CodeSymbol(
                        name="foo", qualified_name="test.foo",
                        kind="function", file_path="test.py",
                        line=1, end_line=3, calls=["bar"],
                    )],
                    imports=[ImportRef(module="os", names=["path"],
                                      is_relative=False, level=0)],
                    content_hash="abc123",
                ),
            },
            cross_file_edges={"test.py": {"other.py": 2}},
            symbol_index={"foo": ["test.py"]},
        )

        d = symbol_graph_to_dict(graph)
        restored = symbol_graph_from_dict(d)

        assert "test.py" in restored.file_symbols
        assert restored.file_symbols["test.py"].symbols[0].name == "foo"
        assert restored.file_symbols["test.py"].symbols[0].calls == ["bar"]
        assert restored.cross_file_edges["test.py"]["other.py"] == 2
        assert restored.symbol_index["foo"] == ["test.py"]


# =============================================================================
# Integration Test: Parse hologram-pro itself
# =============================================================================

class TestHologramIntegration:
    """Parse the actual hologram-pro codebase as an integration test."""

    @pytest.fixture
    def hologram_files(self):
        """Load all Python files from hologram/ package."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        hologram_dir = os.path.join(project_root, "hologram")
        files = {}
        for root, dirs, filenames in os.walk(hologram_dir):
            for fname in filenames:
                if fname.endswith('.py'):
                    full = os.path.join(root, fname)
                    rel = os.path.relpath(full, project_root)
                    try:
                        content = open(full).read()
                        files[rel] = content
                    except Exception:
                        pass
        return files

    def test_parses_all_files(self, hologram_files):
        graph = build_symbol_graph(hologram_files)
        # Should parse all .py files
        assert len(graph.file_symbols) == len(hologram_files)
        # No parse errors in our own code
        for path, fs in graph.file_symbols.items():
            assert fs.parse_error is None, f"Parse error in {path}: {fs.parse_error}"

    def test_known_symbols_exist(self, hologram_files):
        graph = build_symbol_graph(hologram_files)
        # These symbols should be discovered
        expected = [
            "CognitiveFile", "CognitiveSystem", "process_turn",
            "apply_activation", "propagate_pressure", "apply_decay",
            "discover_edges", "build_dag", "HologramRouter",
            "Session", "TurnResult",
        ]
        for name in expected:
            assert name in graph.symbol_index, f"Expected symbol '{name}' not found"

    def test_cross_file_edges_exist(self, hologram_files):
        graph = build_symbol_graph(hologram_files)
        # system.py imports from pressure.py
        system_path = next(p for p in hologram_files if p.endswith("system.py")
                          and "mcp" not in p)
        pressure_path = next(p for p in hologram_files if p.endswith("pressure.py"))
        assert system_path in graph.cross_file_edges
        assert pressure_path in graph.cross_file_edges[system_path], \
            f"Expected edge {system_path} → {pressure_path}"

    def test_bridge_with_architecture_doc(self, hologram_files):
        """SYSTEM_ARCHITECTURE.md mentions many functions — bridge should find them."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        arch_path = os.path.join(project_root, "SYSTEM_ARCHITECTURE.md")
        if not os.path.exists(arch_path):
            pytest.skip("SYSTEM_ARCHITECTURE.md not found")

        graph = build_symbol_graph(hologram_files)
        doc_content = open(arch_path).read()
        bridge = build_bridge_edges({"SYSTEM_ARCHITECTURE.md": doc_content}, graph)

        assert "SYSTEM_ARCHITECTURE.md" in bridge
        code_files = bridge["SYSTEM_ARCHITECTURE.md"]
        # Should find references to at least some hologram modules
        assert len(code_files) >= 2, \
            f"Expected bridge to find multiple code files, got: {code_files}"
        # system.py should be found (CognitiveFile, CognitiveSystem mentioned)
        assert any("system" in f for f in code_files), \
            f"Expected bridge to system.py, got: {code_files}"

    def test_symbol_count_reasonable(self, hologram_files):
        graph = build_symbol_graph(hologram_files)
        total_symbols = sum(len(fs.symbols) for fs in graph.file_symbols.values())
        # Hologram has at least 50 functions/classes across all files
        assert total_symbols > 50, f"Only found {total_symbols} symbols"
        # But not absurdly many
        assert total_symbols < 5000, f"Found {total_symbols} symbols — suspicious"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
