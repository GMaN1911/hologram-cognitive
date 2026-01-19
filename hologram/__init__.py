"""
hologram-cognitive: Pressure-based context routing with lighthouse resurrection

Portable AI working memory for Claude.ai, Claude Code, ChatGPT, and any LLM.

Quick Start:
    import hologram
    
    # One-liner routing
    ctx = hologram.route('.claude', "user message here")
    
    # Session-based (multi-turn)
    session = hologram.Session('.claude')
    result = session.turn("user message")
    session.note("Topic", "Content")
    session.save()

CLI:
    hologram route .claude "message"
    hologram status .claude
    hologram note .claude "Title" "Body"
    hologram init .claude
    hologram export .claude backup.tar.gz

Author: Garret Sutherland <gsutherland@mirrorethic.com>
License: MIT
"""

__version__ = "0.3.1"
__author__ = "Garret Sutherland"
__email__ = "gsutherland@mirrorethic.com"

from .session import Session, TurnResult, route, bootstrap, get_session
from .router import HologramRouter, create_router_from_directory
from .system import CognitiveSystem, CognitiveFile, process_turn, get_context
from .pressure import (
    PressureConfig,
    compute_basin_depth,
    compute_effective_decay,
    update_basin_state,
)
from .dag import EdgeDiscoveryConfig
from .turn_state import (
    TurnState,
    TurnStateConfig,
    load_turn_state,
    save_turn_state,
    compute_next_state,
)
from .resolution import (
    detect_resolution,
    analyze_query,
    ResolutionResult,
)
from .crystallize import (
    CrystallizeConfig,
    should_crystallize,
    crystallize,
    list_sessions,
    SessionInfo,
)

# Optional imports for ecosystem integration
try:
    from . import hooks
    from . import claude_cognitive
    _INTEGRATIONS_AVAILABLE = True
except ImportError:
    _INTEGRATIONS_AVAILABLE = False

__all__ = [
    # High-level API
    'Session',
    'TurnResult',
    'route',
    'bootstrap',
    'get_session',
    # Core classes
    'HologramRouter',
    'create_router_from_directory',
    'CognitiveSystem',
    'CognitiveFile',
    'process_turn',
    'get_context',
    # Configuration
    'PressureConfig',
    'EdgeDiscoveryConfig',
    # Basin dynamics (v0.3.0)
    'compute_basin_depth',
    'compute_effective_decay',
    'update_basin_state',
    # Turn state (v0.3.0)
    'TurnState',
    'TurnStateConfig',
    'load_turn_state',
    'save_turn_state',
    'compute_next_state',
    # Resolution detection (v0.3.0)
    'detect_resolution',
    'analyze_query',
    'ResolutionResult',
    # Crystallization (v0.3.0)
    'CrystallizeConfig',
    'should_crystallize',
    'crystallize',
    'list_sessions',
    'SessionInfo',
    # Integration modules (if available)
    'hooks',
    'claude_cognitive',
]
