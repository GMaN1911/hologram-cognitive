"""
Code-Level DAG for Hologram Cognitive
======================================
AST-based symbol extraction and cross-file dependency resolution.
Enriches the existing file-level DAG with function calls, class inheritance,
and import edges discovered via static analysis.

Architecture:
  Layer 1: .claude/ docs  ←→  text-based DAG (dag.py)
  Layer 2: Project code   ←→  AST-based code DAG (this module)
  Bridge:  docs mention `func_name()` → resolve to code file via symbol index

The bridge is the critical feature: users type vague queries that match docs,
docs mention function names, and the code DAG resolves those to exact files.

Language support: Python first (stdlib ast). Interface is language-agnostic —
FileSymbols has no Python-specific fields, so future parsers (JS/TS/Rust)
return the same type.
"""

import ast
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class CodeSymbol:
    """A function, class, or method extracted from source code."""
    name: str                                # "apply_activation"
    qualified_name: str                      # "pressure.apply_activation"
    kind: str                                # "function" | "class" | "method"
    file_path: str                           # project-relative path
    line: int
    end_line: int
    calls: List[str] = field(default_factory=list)       # names this symbol calls
    bases: List[str] = field(default_factory=list)        # base classes (for classes)
    decorators: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'qualified_name': self.qualified_name,
            'kind': self.kind,
            'file_path': self.file_path,
            'line': self.line,
            'end_line': self.end_line,
            'calls': self.calls,
            'bases': self.bases,
            'decorators': self.decorators,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'CodeSymbol':
        return cls(**d)


@dataclass
class ImportRef:
    """A single import statement."""
    module: str              # ".pressure" or "hologram.pressure"
    names: List[str]         # ["apply_activation", "propagate_pressure"]
    is_relative: bool = False
    level: int = 0           # dot count for relative imports

    def to_dict(self) -> dict:
        return {
            'module': self.module,
            'names': self.names,
            'is_relative': self.is_relative,
            'level': self.level,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'ImportRef':
        return cls(**d)


@dataclass
class FileSymbols:
    """All symbols and imports extracted from a single file."""
    file_path: str
    language: str = "python"
    symbols: List[CodeSymbol] = field(default_factory=list)
    imports: List[ImportRef] = field(default_factory=list)
    parse_error: Optional[str] = None
    content_hash: str = ""

    def to_dict(self) -> dict:
        return {
            'file_path': self.file_path,
            'language': self.language,
            'symbols': [s.to_dict() for s in self.symbols],
            'imports': [i.to_dict() for i in self.imports],
            'parse_error': self.parse_error,
            'content_hash': self.content_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'FileSymbols':
        return cls(
            file_path=d['file_path'],
            language=d.get('language', 'python'),
            symbols=[CodeSymbol.from_dict(s) for s in d.get('symbols', [])],
            imports=[ImportRef.from_dict(i) for i in d.get('imports', [])],
            parse_error=d.get('parse_error'),
            content_hash=d.get('content_hash', ''),
        )


@dataclass
class SymbolGraph:
    """Complete symbol-level graph for a project."""
    file_symbols: Dict[str, FileSymbols] = field(default_factory=dict)
    # source_file → target_file → symbol reference count
    cross_file_edges: Dict[str, Dict[str, int]] = field(default_factory=dict)
    # symbol_name → list of file_paths that define it (for bridge lookups)
    symbol_index: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'file_symbols': {k: v.to_dict() for k, v in self.file_symbols.items()},
            'cross_file_edges': self.cross_file_edges,
            'symbol_index': self.symbol_index,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'SymbolGraph':
        return cls(
            file_symbols={k: FileSymbols.from_dict(v)
                          for k, v in d.get('file_symbols', {}).items()},
            cross_file_edges=d.get('cross_file_edges', {}),
            symbol_index=d.get('symbol_index', {}),
        )


# =============================================================================
# Python AST Parser
# =============================================================================

class _PythonSymbolVisitor(ast.NodeVisitor):
    """Extract symbols and imports from a Python AST."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.file_stem = Path(file_path).stem
        self.symbols: List[CodeSymbol] = []
        self.imports: List[ImportRef] = []
        self._scope_stack: List[str] = []  # track enclosing class/function

    def visit_FunctionDef(self, node: ast.FunctionDef):
        kind = "method" if self._scope_stack else "function"
        qualified = f"{self.file_stem}.{'.'.join(self._scope_stack + [node.name])}"

        sym = CodeSymbol(
            name=node.name,
            qualified_name=qualified,
            kind=kind,
            file_path=self.file_path,
            line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            calls=self._extract_calls(node),
            decorators=[self._decorator_name(d) for d in node.decorator_list],
        )
        self.symbols.append(sym)

        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef):
        qualified = f"{self.file_stem}.{'.'.join(self._scope_stack + [node.name])}"
        bases = [self._name_from_node(b) for b in node.bases if self._name_from_node(b)]

        sym = CodeSymbol(
            name=node.name,
            qualified_name=qualified,
            kind="class",
            file_path=self.file_path,
            line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            bases=bases,
            decorators=[self._decorator_name(d) for d in node.decorator_list],
        )
        self.symbols.append(sym)

        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append(ImportRef(
                module=alias.name,
                names=[alias.asname or alias.name.split('.')[-1]],
                is_relative=False,
                level=0,
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom):
        names = [alias.name for alias in (node.names or [])]
        self.imports.append(ImportRef(
            module=node.module or '',
            names=names,
            is_relative=node.level > 0,
            level=node.level,
        ))

    def _extract_calls(self, func_node: ast.AST) -> List[str]:
        """Walk a function body for ast.Call nodes."""
        calls = []
        for node in ast.walk(func_node):
            if isinstance(node, ast.Call):
                name = self._call_name(node)
                if name:
                    calls.append(name)
        return list(set(calls))  # deduplicate

    def _call_name(self, node: ast.Call) -> Optional[str]:
        """Extract the called name from a Call node."""
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            # e.g. self.method() → "method", obj.func() → "func"
            return func.attr
        return None

    def _name_from_node(self, node: ast.expr) -> Optional[str]:
        """Extract a name from an expression node (for base classes etc)."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Subscript):
            return self._name_from_node(node.value)
        return None

    def _decorator_name(self, node: ast.expr) -> str:
        """Extract decorator name."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Call):
            return self._decorator_name(node.func)
        return "unknown"


def parse_python_file(file_path: str, content: str) -> FileSymbols:
    """
    Parse a Python file and extract symbols + imports.

    Args:
        file_path: Project-relative path (e.g., "hologram/pressure.py")
        content: File content string

    Returns:
        FileSymbols with extracted data, or with parse_error set on failure
    """
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]

    try:
        tree = ast.parse(content, filename=file_path)
    except SyntaxError as e:
        return FileSymbols(
            file_path=file_path,
            parse_error=f"SyntaxError: {e}",
            content_hash=content_hash,
        )

    visitor = _PythonSymbolVisitor(file_path)
    visitor.visit(tree)

    return FileSymbols(
        file_path=file_path,
        symbols=visitor.symbols,
        imports=visitor.imports,
        content_hash=content_hash,
    )


# =============================================================================
# Import Resolution
# =============================================================================

def resolve_import(
    import_ref: ImportRef,
    source_file: str,
    project_files: Set[str],
) -> Optional[str]:
    """
    Resolve an ImportRef to a project file path.

    Returns None for stdlib/third-party imports (not in project).
    """
    if import_ref.is_relative:
        # Walk up from source file by `level` directories
        source_dir = Path(source_file).parent
        base = source_dir
        for _ in range(import_ref.level - 1):
            base = base.parent

        # Convert module dotpath to path
        if import_ref.module:
            module_parts = import_ref.module.split('.')
            candidate = base / '/'.join(module_parts)
        else:
            candidate = base
    else:
        # Absolute import
        module_parts = import_ref.module.split('.')
        candidate = Path('/'.join(module_parts))

    # Try .py file first, then __init__.py
    candidates = [
        str(candidate) + '.py',
        str(candidate / '__init__.py'),
    ]

    # Normalize paths (remove leading ./ etc)
    for c in candidates:
        normalized = str(Path(c))
        if normalized in project_files:
            return normalized

    return None


def _build_import_map(
    file_symbols: FileSymbols,
    project_files: Set[str],
) -> Dict[str, str]:
    """
    Build mapping: imported_name → resolved_file_path.

    For `from .pressure import apply_activation, propagate_pressure`:
      {"apply_activation": "hologram/pressure.py",
       "propagate_pressure": "hologram/pressure.py"}
    """
    name_to_file: Dict[str, str] = {}

    for imp in file_symbols.imports:
        resolved = resolve_import(imp, file_symbols.file_path, project_files)
        if resolved:
            for name in imp.names:
                if name != '*':
                    name_to_file[name] = resolved

    return name_to_file


# =============================================================================
# Symbol Graph Builder
# =============================================================================

def build_symbol_graph(project_files: Dict[str, str]) -> SymbolGraph:
    """
    Build a complete symbol graph from project Python files.

    Args:
        project_files: Dict of rel_path → content (only .py files)

    Returns:
        SymbolGraph with parsed symbols, cross-file edges, and symbol index
    """
    graph = SymbolGraph()
    all_paths = set(project_files.keys())

    # Phase 1: Parse all files
    for path, content in project_files.items():
        if not path.endswith('.py'):
            continue
        fs = parse_python_file(path, content)
        graph.file_symbols[path] = fs

    # Phase 2: Build symbol index (name → defining files)
    for path, fs in graph.file_symbols.items():
        for sym in fs.symbols:
            if sym.name not in graph.symbol_index:
                graph.symbol_index[sym.name] = []
            graph.symbol_index[sym.name].append(path)

    # Phase 3: Resolve imports and build cross-file edges
    for path, fs in graph.file_symbols.items():
        if fs.parse_error:
            continue

        import_map = _build_import_map(fs, all_paths)

        # Count how many symbols from each target file are referenced
        target_counts: Dict[str, int] = {}

        # Direct import references
        for name, target_file in import_map.items():
            target_counts[target_file] = target_counts.get(target_file, 0) + 1

        # Function calls that resolve via imports
        for sym in fs.symbols:
            for call_name in sym.calls:
                if call_name in import_map:
                    target = import_map[call_name]
                    target_counts[target] = target_counts.get(target, 0) + 1
                # Also check if call resolves to a known symbol in another file
                elif call_name in graph.symbol_index:
                    for target in graph.symbol_index[call_name]:
                        if target != path:
                            target_counts[target] = target_counts.get(target, 0) + 1

        # Class inheritance edges
        for sym in fs.symbols:
            if sym.kind == 'class':
                for base in sym.bases:
                    if base in import_map:
                        target = import_map[base]
                        # Inheritance is a strong signal — count as 3
                        target_counts[target] = target_counts.get(target, 0) + 3
                    elif base in graph.symbol_index:
                        for target in graph.symbol_index[base]:
                            if target != path:
                                target_counts[target] = target_counts.get(target, 0) + 3

        if target_counts:
            graph.cross_file_edges[path] = target_counts

    return graph


# =============================================================================
# Doc-Code Bridge
# =============================================================================

# Patterns for finding code references in documentation
_BACKTICK_REF = re.compile(r'`([a-zA-Z_]\w+)`')           # `function_name`
_CALL_REF = re.compile(r'([a-zA-Z_]\w+)\(\)')              # function_name()
_DOTTED_REF = re.compile(r'([a-zA-Z_]\w+\.[a-zA-Z_]\w+)')  # module.function

# Common doc words that look like code but aren't
_DOC_STOPWORDS = frozenset([
    'the', 'and', 'for', 'this', 'that', 'with', 'from', 'will', 'can',
    'are', 'not', 'all', 'any', 'each', 'more', 'also', 'just', 'only',
    'file', 'files', 'path', 'line', 'lines', 'type', 'name', 'data',
    'list', 'dict', 'none', 'true', 'false', 'self', 'args', 'kwargs',
    'string', 'number', 'value', 'result', 'error', 'node',
    'table', 'tool', 'turn', 'used', 'note', 'status',
])


def extract_code_refs(
    doc_content: str,
    known_symbols: Set[str],
    min_name_length: int = 4,
) -> Set[str]:
    """
    Extract code symbol references from documentation text.

    Matches:
    - Backtick-delimited: `function_name`
    - Call syntax: function_name()
    - Known symbol names (4+ chars, not stopwords)

    Args:
        doc_content: Documentation text (markdown, etc.)
        known_symbols: Set of all known symbol names from the code DAG
        min_name_length: Minimum length for bare name matches

    Returns:
        Set of matched symbol names
    """
    found = set()

    # Backtick references — highest confidence
    for match in _BACKTICK_REF.finditer(doc_content):
        name = match.group(1)
        if name in known_symbols:
            found.add(name)

    # Call syntax references — high confidence
    for match in _CALL_REF.finditer(doc_content):
        name = match.group(1)
        if name in known_symbols:
            found.add(name)

    # Dotted references — check the second part
    for match in _DOTTED_REF.finditer(doc_content):
        parts = match.group(1).split('.')
        for part in parts:
            if part in known_symbols:
                found.add(part)

    # Bare name matches against known symbols (conservative)
    # Only match names that are long enough and underscore-style (likely code)
    for name in known_symbols:
        if len(name) < min_name_length:
            continue
        if name.lower() in _DOC_STOPWORDS:
            continue
        # Require underscore_case or PascalCase to reduce false positives
        is_code_style = '_' in name or (name[0].isupper() and any(c.islower() for c in name))
        if is_code_style and name in doc_content:
            found.add(name)

    return found


def build_bridge_edges(
    doc_files: Dict[str, str],
    symbol_graph: SymbolGraph,
) -> Dict[str, Set[str]]:
    """
    Build doc → code file edges via symbol reference extraction.

    For each documentation file, finds code symbol references and resolves
    them to the code files that define those symbols.

    Args:
        doc_files: Dict of doc_path → content (markdown, etc.)
        symbol_graph: The code-level symbol graph

    Returns:
        Dict of doc_path → set of code file paths
    """
    known_symbols = set(symbol_graph.symbol_index.keys())
    bridge: Dict[str, Set[str]] = {}

    for doc_path, content in doc_files.items():
        refs = extract_code_refs(content, known_symbols)
        code_files = set()
        for ref_name in refs:
            for code_path in symbol_graph.symbol_index.get(ref_name, []):
                code_files.add(code_path)
        if code_files:
            bridge[doc_path] = code_files

    return bridge


# =============================================================================
# Edge Weight Enrichment
# =============================================================================

def enrich_edge_weights(
    base_weights: Dict[str, Dict[str, float]],
    symbol_graph: SymbolGraph,
    bonus_per_ref: float = 0.15,
    max_bonus: float = 2.0,
) -> Dict[str, Dict[str, float]]:
    """
    Add symbol-derived bonuses to existing file-level edge weights.

    More symbol references between files = stronger edge weight.
    This enriches, never replaces, the text-based weights.

    Args:
        base_weights: Existing edge weights from dag.py
        symbol_graph: The code-level symbol graph
        bonus_per_ref: Weight bonus per symbol reference
        max_bonus: Maximum total bonus per edge

    Returns:
        New edge weight dict with symbol bonuses added
    """
    enriched = {k: dict(v) for k, v in base_weights.items()}

    for source, targets in symbol_graph.cross_file_edges.items():
        for target, count in targets.items():
            bonus = min(count * bonus_per_ref, max_bonus)
            if source in enriched:
                current = enriched[source].get(target, 1.0)
                enriched[source][target] = current + bonus
            else:
                enriched[source] = {target: 1.0 + bonus}

    return enriched


def discover_symbol_edges(
    symbol_graph: SymbolGraph,
) -> Dict[str, Set[str]]:
    """
    Extract new file→file edges discovered via AST that text matching may miss.

    Returns adjacency entries to merge into the existing DAG.
    """
    adjacency: Dict[str, Set[str]] = {}
    for source, targets in symbol_graph.cross_file_edges.items():
        adjacency[source] = set(targets.keys())
    return adjacency


# =============================================================================
# Serialization Helpers
# =============================================================================

def symbol_graph_to_dict(graph: SymbolGraph) -> dict:
    """Serialize SymbolGraph for JSON caching."""
    return graph.to_dict()


def symbol_graph_from_dict(data: dict) -> SymbolGraph:
    """Deserialize SymbolGraph from JSON cache."""
    return SymbolGraph.from_dict(data)


def content_hash(content: str) -> str:
    """Compute a short content hash for cache invalidation."""
    return hashlib.sha256(content.encode()).hexdigest()[:12]
