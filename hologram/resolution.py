"""
Resolution Detection for Hologram Cognitive v0.3.0

Detects when the user has resolved their current focus area,
signaling that inherited state can be released.

Resolution types:
- "completion": User indicates task is done (fixed, solved, thanks)
- "topic_change": User explicitly changes topic
- "none": No resolution detected, continue inheriting state
"""

import re
from typing import Tuple, List, Optional, Dict
from dataclasses import dataclass


# =============================================================================
# Resolution Patterns
# =============================================================================

# Completion signals (user indicates task is done)
COMPLETION_PATTERNS = [
    (r'\b(fixed|solved|done|working now|works now|that\'s it|perfect)\b', 0.4),
    (r'\b(got it|figured it out|makes sense now|understand now)\b', 0.35),
    (r'\b(thanks|thank you|awesome|great job|nice)\b', 0.2),
    (r'\b(now let\'s|okay so|alright|moving on)\b', 0.15),
    (r'\b(all good|all set|sorted)\b', 0.3),
]

# Tension signals (user still working through something)
TENSION_PATTERNS = [
    (r'\b(but|however|still|yet|though)\b', 0.15),
    (r'\b(not sure|confused|don\'t understand|unclear|weird)\b', 0.25),
    (r'\b(why|how come|doesn\'t make sense)\b', 0.2),
    (r'\b(not working|broken|error|failed|bug)\b', 0.25),
    (r'\b(help|stuck|blocked)\b', 0.2),
    (r'\?$', 0.1),  # Ends with question mark
    (r'\?\s*$', 0.15),  # Question mark at end
]

# Topic change signals (explicit context switch)
TOPIC_CHANGE_PATTERNS = [
    (r'\b(unrelated|different question|off topic|by the way|btw)\b', 0.6),
    (r'\b(switching gears|change of subject|new topic|another thing)\b', 0.5),
    (r'\b(completely different|separate issue|quick question)\b', 0.4),
]

# Assistant completion signals (for contextual detection)
ASSISTANT_COMPLETION_PATTERNS = [
    r'\b(I\'ve (fixed|completed|finished|resolved|implemented))\b',
    r'\b(that should (work|fix|solve|resolve))\b',
    r'\b(all (set|done|fixed|ready))\b',
    r'\b(changes (are|have been) (made|applied|committed))\b',
    r'\b(the (fix|solution|change) (is|has been))\b',
]


# =============================================================================
# Detection Functions
# =============================================================================

def detect_resolution(
    query: str,
    prev_tension: float = 0.0
) -> Tuple[bool, str]:
    """
    Detect if query indicates resolution of current focus.

    Uses lexical heuristics to identify completion, tension, or topic change.

    Args:
        query: User query text
        prev_tension: Previous tension level (affects threshold)

    Returns:
        (is_resolved, resolution_type) where resolution_type is:
        - "completion": Task completed
        - "topic_change": Explicit topic switch
        - "none": No resolution
    """
    query_lower = query.lower()

    # Calculate pattern scores
    completion_score = sum(
        weight for pattern, weight in COMPLETION_PATTERNS
        if re.search(pattern, query_lower, re.IGNORECASE)
    )

    tension_score = sum(
        weight for pattern, weight in TENSION_PATTERNS
        if re.search(pattern, query_lower, re.IGNORECASE)
    )

    topic_change_score = sum(
        weight for pattern, weight in TOPIC_CHANGE_PATTERNS
        if re.search(pattern, query_lower, re.IGNORECASE)
    )

    # Topic change is high priority
    if topic_change_score >= 0.4:
        return True, "topic_change"

    # Adjust completion threshold based on tension
    # Higher tension = need stronger completion signal
    completion_threshold = 0.2 + (prev_tension * 0.1)

    # Completion must outweigh tension
    if completion_score > tension_score and completion_score >= completion_threshold:
        return True, "completion"

    return False, "none"


def detect_contextual_resolution(
    query: str,
    response: str,
    tool_calls: Optional[List[Dict]] = None,
    prev_tension_sources: Optional[List[str]] = None
) -> Tuple[bool, str]:
    """
    Enhanced resolution detection using response and tool call context.

    Called in post-response hook for more accurate detection.

    Args:
        query: User query text
        response: Assistant response text
        tool_calls: List of tool invocations (e.g., [{'tool': 'Write', 'path': '...'}])
        prev_tension_sources: Topics that were causing tension

    Returns:
        (is_resolved, resolution_type)
    """
    response_lower = response.lower()

    # Check if assistant indicated completion
    for pattern in ASSISTANT_COMPLETION_PATTERNS:
        if re.search(pattern, response, re.IGNORECASE):
            return True, "completion"

    # Check tool calls for completion indicators
    if tool_calls:
        for call in tool_calls:
            tool = call.get('tool', '')
            path = call.get('path', call.get('file_path', ''))

            # Writing a test file often indicates feature completion
            if tool == 'Write' and 'test' in path.lower():
                return True, "completion"

            # Git commit indicates completion
            if tool == 'Bash':
                command = call.get('command', '')
                if 'git commit' in command:
                    return True, "completion"

    # Check if tension sources were addressed in response
    if prev_tension_sources:
        sources_addressed = sum(
            1 for source in prev_tension_sources
            if source.lower() in response_lower
        )
        # If most tension sources were addressed, likely resolved
        if sources_addressed >= len(prev_tension_sources) * 0.7:
            return True, "completion"

    return False, "none"


def compute_query_tension(query: str) -> float:
    """
    Compute tension level from query text alone.

    Higher scores indicate more unresolved cognitive load.

    Args:
        query: User query text

    Returns:
        Tension score (0.0 to ~0.5)
    """
    query_lower = query.lower()

    tension = 0.0

    # Sum tension pattern scores
    for pattern, weight in TENSION_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            tension += weight

    # Question marks add tension
    question_count = query.count('?')
    tension += min(question_count * 0.05, 0.15)

    # Length can indicate complexity
    word_count = len(query.split())
    if word_count > 50:
        tension += 0.1
    elif word_count > 100:
        tension += 0.15

    return min(tension, 0.5)  # Cap at 0.5


def is_followup_query(query: str, prev_activated: List[str]) -> bool:
    """
    Detect if query is a follow-up to previous context.

    Follow-ups inherit context more strongly.

    Args:
        query: Current query text
        prev_activated: Files activated in previous turn

    Returns:
        True if query appears to be a follow-up
    """
    query_lower = query.lower()

    # Explicit follow-up indicators
    followup_patterns = [
        r'^(also|and|what about|how about)',
        r'^(another|one more|additionally)',
        r'\b(same|that|those|these|the)\s+(file|thing|issue|problem)s?\b',
        r'^(wait|actually|oh)',
        r'\b(you (just|mentioned|said))\b',
    ]

    for pattern in followup_patterns:
        if re.search(pattern, query_lower):
            return True

    # Check if query mentions previously activated files
    for path in prev_activated:
        # Extract filename without extension
        filename = path.split('/')[-1].rsplit('.', 1)[0].lower()
        if len(filename) > 3 and filename in query_lower:
            return True

    return False


# =============================================================================
# Integration Helpers
# =============================================================================

@dataclass
class ResolutionResult:
    """Result of resolution detection."""
    resolved: bool
    resolution_type: str  # "completion", "topic_change", "none"
    completion_score: float
    tension_score: float
    topic_change_score: float
    is_followup: bool


def analyze_query(
    query: str,
    prev_tension: float = 0.0,
    prev_activated: Optional[List[str]] = None
) -> ResolutionResult:
    """
    Full analysis of query for resolution and context signals.

    Args:
        query: User query text
        prev_tension: Previous tension level
        prev_activated: Previously activated files

    Returns:
        ResolutionResult with full analysis
    """
    query_lower = query.lower()

    # Calculate all scores
    completion_score = sum(
        weight for pattern, weight in COMPLETION_PATTERNS
        if re.search(pattern, query_lower, re.IGNORECASE)
    )

    tension_score = sum(
        weight for pattern, weight in TENSION_PATTERNS
        if re.search(pattern, query_lower, re.IGNORECASE)
    )

    topic_change_score = sum(
        weight for pattern, weight in TOPIC_CHANGE_PATTERNS
        if re.search(pattern, query_lower, re.IGNORECASE)
    )

    # Determine resolution
    resolved, resolution_type = detect_resolution(query, prev_tension)

    # Check follow-up
    is_followup = is_followup_query(query, prev_activated or [])

    return ResolutionResult(
        resolved=resolved,
        resolution_type=resolution_type,
        completion_score=completion_score,
        tension_score=tension_score,
        topic_change_score=topic_change_score,
        is_followup=is_followup,
    )
