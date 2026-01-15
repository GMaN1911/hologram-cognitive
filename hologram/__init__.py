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

__version__ = "0.2.0"
__author__ = "Garret Sutherland"
__email__ = "gsutherland@mirrorethic.com"

from .session import Session, TurnResult, route, bootstrap, get_session
from .router import HologramRouter, create_router_from_directory
from .system import CognitiveSystem, CognitiveFile, process_turn, get_context
from .pressure import PressureConfig
from .dag import EdgeDiscoveryConfig

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
    # Integration modules (if available)
    'hooks',
    'claude_cognitive',
]
