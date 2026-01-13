"""
DAG Discovery for Hologram Cognitive

Automatically discover edges (relationships) between files by analyzing content.
Replaces manual co_activation configuration.

Key insight: If file A mentions file B's name/concepts, there's an edge A→B.
The graph structure IS the co-activation network, discovered not configured.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, Set, List, Optional, Callable
from pathlib import Path


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
                if len(part) >= config.min_part_length and part.lower() in content_lower:
                    edges.add(target_path)
                    break
            if target_path in edges:
                continue
        
        # Strategy 4: Hyphenated/underscored parts
        if config.use_keyword_parts:
            filename = Path(target_path).stem
            parts = re.split(r'[-_]', filename)
            significant_parts = [p for p in parts if len(p) >= config.min_part_length]
            
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
    all_paths = list(files.keys())
    adjacency = {}
    
    for path, content in files.items():
        edges = discover_edges(path, content, all_paths, config)
        adjacency[path] = edges
    
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
    
    for source, targets in adjacency.items():
        weights[source] = {}
        content = files.get(source, "")
        
        for target in targets:
            weights[source][target] = get_edge_weight(
                source, target, content
            )
    
    return weights


def find_strongly_connected(adjacency: Dict[str, Set[str]]) -> List[Set[str]]:
    """
    Find strongly connected components (clusters of tightly related files).
    
    Files in the same SCC should probably co-activate as a group.
    """
    # Simple implementation: files that mutually reference each other
    incoming = get_incoming_edges(adjacency)
    components = []
    visited = set()
    
    for path in adjacency:
        if path in visited:
            continue
        
        # Find all files reachable in both directions
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
        'strongly_connected': find_strongly_connected(adjacency),
    }
