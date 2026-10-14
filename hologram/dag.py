"""
DAG Discovery for Hologram Cognitive

Automatically discover edges (relationships) between files by analyzing content.
Replaces manual co_activation configuration.

Key insight: If file A mentions file B's name/concepts, there's an edge A→B.
The graph structure IS the co-activation network, discovered not configured.
"""

import re
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Dict, Set, List, Optional, Callable, Pattern
from pathlib import Path

# The only non-ASCII characters CPython's re.IGNORECASE matches to an ASCII letter or digit
# (enumerated over every code point on 3.12): İ ı ſ K. Content free of them can skip a stem regex
# whenever the lowercased stem is absent — the regex needs that literal to match.
_IGNORECASE_ASCII_EXTRAS = ('İ', 'ı', 'ſ', 'K')


@dataclass
class EdgeDiscoveryConfig:
    """Configuration for edge discovery strategies."""
    
    # Enable/disable strategies
    use_path_matching: bool = True      # Match full paths in content
    use_filename_matching: bool = True  # Match filenames without extension
    use_partial_path: bool = True       # Match path components
    use_keyword_parts: bool = True      # Match hyphenated parts
    use_import_statements: bool = True  # Parse import/from statements
    use_markdown_links: bool = True     # Parse [text](link) syntax
    
    # Minimum length for partial matches (avoid false positives)
    min_part_length: int = 4

    # Generic terms to exclude (prevents "ghost edges" from common terms)
    exclude_generic_terms: List[str] = field(default_factory=lambda: [
        'utils', 'helpers', 'config', 'test', 'tests',
        'init', 'main', 'index', 'common', 'base',
        'core', 'types', 'models', 'views', 'data',
        'lib', 'libs', 'tools', 'misc', 'temp',
    ])

    # Custom patterns to match
    custom_patterns: List[str] = field(default_factory=list)

    # Files to exclude from discovery
    exclude_patterns: List[str] = field(default_factory=lambda: [
        r'__pycache__',
        r'\.git',
        r'\.pyc$',
        r'node_modules',
    ])


def discover_edges(
    source_path: str,
    source_content: str,
    all_paths: List[str],
    config: Optional[EdgeDiscoveryConfig] = None
) -> Set[str]:
    """
    Discover edges from a source file to other files.
    
    Args:
        source_path: Path of the source file
        source_content: Content of the source file
        all_paths: List of all file paths to search for
        config: Discovery configuration
    
    Returns:
        Set of target paths that source references
    """
    if config is None:
        config = EdgeDiscoveryConfig()
    
    edges = set()
    content_lower = source_content.lower()
    
    for target_path in all_paths:
        if target_path == source_path:
            continue
        
        # Skip excluded patterns
        if any(re.search(pat, target_path) for pat in config.exclude_patterns):
            continue
        
        # Strategy 1: Full path reference
        if config.use_path_matching:
            if target_path.lower() in content_lower:
                edges.add(target_path)
                continue
        
        # Strategy 2: Filename without extension
        if config.use_filename_matching:
            filename = Path(target_path).stem  # e.g., "t3-telos" from "modules/t3-telos.md"
            if len(filename) >= config.min_part_length and filename.lower() in content_lower:
                edges.add(target_path)
                continue
        
        # Strategy 3: Partial path components
        if config.use_partial_path:
            path_parts = target_path.replace('.md', '').replace('.py', '').split('/')
            for part in path_parts:
                # Skip generic terms to avoid ghost edges
                if part.lower() in config.exclude_generic_terms:
                    continue
                if len(part) >= config.min_part_length and part.lower() in content_lower:
                    edges.add(target_path)
                    break
            if target_path in edges:
                continue
        
        # Strategy 4: Hyphenated/underscored parts
        if config.use_keyword_parts:
            filename = Path(target_path).stem
            parts = re.split(r'[-_]', filename)
            # Filter out short parts AND generic terms
            significant_parts = [
                p for p in parts
                if len(p) >= config.min_part_length
                and p.lower() not in config.exclude_generic_terms
            ]

            if len(significant_parts) >= 2:
                # All significant parts must match for multi-part names
                if all(p.lower() in content_lower for p in significant_parts):
                    edges.add(target_path)
                    continue
        
        # Strategy 5: Import statements
        if config.use_import_statements:
            filename = Path(target_path).stem
            import_pattern = rf'(?:from|import)\s+[\w.]*{re.escape(filename)}'
            if re.search(import_pattern, source_content, re.IGNORECASE):
                edges.add(target_path)
                continue
        
        # Strategy 6: Markdown links
        if config.use_markdown_links:
            filename = Path(target_path).stem
            link_pattern = rf'\[.*?\]\([^)]*{re.escape(filename)}[^)]*\)'
            if re.search(link_pattern, source_content, re.IGNORECASE):
                edges.add(target_path)
                continue
        
        # Strategy 7: Custom patterns
        for pattern in config.custom_patterns:
            if re.search(pattern, source_content, re.IGNORECASE):
                edges.add(target_path)
                break
    
    return edges


@dataclass
class TargetFeatures:
    """Everything discover_edges/get_edge_weight derive from a target path, computed once per
    target instead of once per (source, target) pair."""
    path: str
    lower: str
    stem_lower: str
    stem_ascii: bool
    stem_long: bool
    excluded: bool
    part_needles: List[str]
    keyword_needles: Optional[List[str]]
    import_re: Pattern
    link_re: Pattern
    parent: str


def prepare_targets(
    paths: List[str],
    config: Optional[EdgeDiscoveryConfig] = None
) -> List[TargetFeatures]:
    """Per-target features for discover_edges_prepared, in the order of `paths`."""
    if config is None:
        config = EdgeDiscoveryConfig()
    generic = config.exclude_generic_terms
    out = []
    for target_path in paths:
        filename = Path(target_path).stem
        path_parts = target_path.replace('.md', '').replace('.py', '').split('/')
        significant = [
            p.lower() for p in re.split(r'[-_]', filename)
            if len(p) >= config.min_part_length and p.lower() not in generic
        ]
        out.append(TargetFeatures(
            path=target_path,
            lower=target_path.lower(),
            stem_lower=filename.lower(),
            stem_ascii=filename.isascii(),
            stem_long=len(filename) >= config.min_part_length,
            excluded=any(re.search(pat, target_path) for pat in config.exclude_patterns),
            part_needles=[p.lower() for p in path_parts
                          if p.lower() not in generic and len(p) >= config.min_part_length],
            keyword_needles=significant if len(significant) >= 2 else None,
            import_re=re.compile(rf'(?:from|import)\s+[\w.]*{re.escape(filename)}', re.IGNORECASE),
            link_re=re.compile(rf'\[.*?\]\([^)]*{re.escape(filename)}[^)]*\)', re.IGNORECASE),
            parent=str(Path(target_path).parent),
        ))
    return out


def discover_edges_prepared(
    source_path: str,
    source_content: str,
    targets: List[TargetFeatures],
    config: Optional[EdgeDiscoveryConfig] = None,
    content_lower: Optional[str] = None,
) -> Set[str]:
    """discover_edges over prepared targets — identical edge set, no per-pair re-derivation."""
    if config is None:
        config = EdgeDiscoveryConfig()
    if content_lower is None:
        content_lower = source_content.lower()
    fold_safe = not any(ch in source_content for ch in _IGNORECASE_ASCII_EXTRAS)
    custom_hit = any(re.search(p, source_content, re.IGNORECASE) for p in config.custom_patterns)
    use_regex = config.use_import_statements or config.use_markdown_links

    edges = set()
    for t in targets:
        if t.path == source_path or t.excluded:
            continue
        if config.use_path_matching and t.lower in content_lower:
            edges.add(t.path)
            continue
        if config.use_filename_matching and t.stem_long and t.stem_lower in content_lower:
            edges.add(t.path)
            continue
        if config.use_partial_path and any(n in content_lower for n in t.part_needles):
            edges.add(t.path)
            continue
        if (config.use_keyword_parts and t.keyword_needles is not None
                and all(n in content_lower for n in t.keyword_needles)):
            edges.add(t.path)
            continue
        if use_regex and not (fold_safe and t.stem_ascii and t.stem_lower not in content_lower):
            if config.use_import_statements and t.import_re.search(source_content):
                edges.add(t.path)
                continue
            if config.use_markdown_links and t.link_re.search(source_content):
                edges.add(t.path)
                continue
        if custom_hit:
            edges.add(t.path)
    return edges


def edge_weights_prepared(
    source_path: str,
    content_lower: str,
    targets: List[TargetFeatures],
    base_weight: float = 1.0,
) -> Dict[str, float]:
    """get_edge_weight for each target in `targets`, with the source lowercased once."""
    source_dir = str(Path(source_path).parent)
    weights = {}
    for t in targets:
        weight = base_weight
        if t.lower in content_lower:
            weight += 0.5
        mention_count = content_lower.count(t.stem_lower)
        weight += min(mention_count * 0.1, 0.5)
        if source_dir == t.parent:
            weight += 0.3
        weights[t.path] = weight
    return weights


def config_fingerprint(config: Optional[EdgeDiscoveryConfig] = None) -> str:
    """Stable identity of a discovery config — edges cached under one config are invalid under another."""
    if config is None:
        config = EdgeDiscoveryConfig()
    return hashlib.sha256(repr(sorted(asdict(config).items())).encode()).hexdigest()[:16]


def build_dag(
    files: Dict[str, str],
    config: Optional[EdgeDiscoveryConfig] = None
) -> Dict[str, Set[str]]:
    """
    Build complete DAG from file contents.

    Args:
        files: Dict mapping path → content
        config: Discovery configuration

    Returns:
        Adjacency dict: source → set of targets
    """
    targets = prepare_targets(list(files.keys()), config)
    adjacency = {}

    for path, content in files.items():
        adjacency[path] = discover_edges_prepared(path, content, targets, config)

    return adjacency


def get_incoming_edges(adjacency: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    """
    Compute incoming edges (reverse of adjacency).
    
    Args:
        adjacency: Forward adjacency (source → targets)
    
    Returns:
        Reverse adjacency (target → sources that reference it)
    """
    incoming = {path: set() for path in adjacency}
    
    for source, targets in adjacency.items():
        for target in targets:
            if target in incoming:
                incoming[target].add(source)
    
    return incoming


def get_edge_weight(
    source_path: str,
    target_path: str,
    source_content: str,
    base_weight: float = 1.0
) -> float:
    """
    Compute edge weight based on reference strength.
    
    More mentions = stronger edge.
    Direct path match = stronger than partial match.
    
    Args:
        source_path: Source file path
        target_path: Target file path
        source_content: Source file content
        base_weight: Base weight for any edge
    
    Returns:
        Edge weight (higher = stronger relationship)
    """
    content_lower = source_content.lower()
    weight = base_weight
    
    # Full path match bonus
    if target_path.lower() in content_lower:
        weight += 0.5
    
    # Count filename mentions
    filename = Path(target_path).stem.lower()
    mention_count = content_lower.count(filename)
    weight += min(mention_count * 0.1, 0.5)  # Cap at 0.5 bonus
    
    # Structural relationship bonus (same directory)
    source_dir = str(Path(source_path).parent)
    target_dir = str(Path(target_path).parent)
    if source_dir == target_dir:
        weight += 0.3
    
    return weight


def compute_edge_weights(
    files: Dict[str, str],
    adjacency: Dict[str, Set[str]]
) -> Dict[str, Dict[str, float]]:
    """
    Compute weights for all edges.
    
    Returns:
        Nested dict: source → target → weight
    """
    weights = {}
    features: Dict[str, TargetFeatures] = {}

    for source, targets in adjacency.items():
        missing = [t for t in targets if t not in features]
        for f in prepare_targets(missing):
            features[f.path] = f
        content_lower = files.get(source, "").lower()
        weights[source] = edge_weights_prepared(
            source, content_lower, [features[t] for t in targets])

    return weights


def find_mutual_clusters(adjacency: Dict[str, Set[str]]) -> List[Set[str]]:
    """
    Find clusters of files with mutual (bidirectional) references.

    NOTE: This is NOT true strongly connected components (SCC).
    This finds sets of files that reference each other bidirectionally,
    but does NOT guarantee that every node can reach every other node
    in the component.

    For real SCC, use Tarjan or Kosaraju algorithm.

    Files in mutual clusters probably co-activate as a group.
    """
    # Simple implementation: files that mutually reference each other
    incoming = get_incoming_edges(adjacency)
    components = []
    visited = set()

    for path in adjacency:
        if path in visited:
            continue

        # Find all files reachable via mutual edges
        component = {path}
        queue = [path]

        while queue:
            current = queue.pop(0)

            # Check outgoing
            for target in adjacency.get(current, set()):
                if target not in component:
                    # Only add if there's a back-edge (mutual reference)
                    if current in adjacency.get(target, set()):
                        component.add(target)
                        queue.append(target)

        if len(component) > 1:
            components.append(component)
            visited.update(component)

    return components


def summarize_dag(adjacency: Dict[str, Set[str]]) -> dict:
    """
    Generate summary statistics about the DAG.
    """
    incoming = get_incoming_edges(adjacency)
    
    total_edges = sum(len(targets) for targets in adjacency.values())
    nodes_with_outgoing = sum(1 for targets in adjacency.values() if targets)
    nodes_with_incoming = sum(1 for sources in incoming.values() if sources)
    
    # Find hubs (high connectivity)
    by_outgoing = sorted(adjacency.items(), key=lambda x: len(x[1]), reverse=True)
    by_incoming = sorted(incoming.items(), key=lambda x: len(x[1]), reverse=True)
    
    return {
        'total_nodes': len(adjacency),
        'total_edges': total_edges,
        'nodes_with_outgoing': nodes_with_outgoing,
        'nodes_with_incoming': nodes_with_incoming,
        'avg_outgoing': total_edges / len(adjacency) if adjacency else 0,
        'top_sources': [(p, len(t)) for p, t in by_outgoing[:5]],
        'top_targets': [(p, len(s)) for p, s in by_incoming[:5]],
        'mutual_clusters': find_mutual_clusters(adjacency),
    }
