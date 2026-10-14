"""Per-file activation boost and decay learned from real usage.

Standalone on purpose (stdlib only, no package imports): the Stop-hook learner loads this file
by path so the rule it writes to t3_file_state.json is the one route_replay.py measures.
"""

DEFAULT_BOOST = 0.6
BOOST_RANGE = (0.4, 0.8)
DECAY_RANGE = (0.80, 0.92)
# One expected use's worth of prior: a file needs to miss about that many expected uses before
# its absence counts against it.
PRIOR_USES = 1.0


def base_rate(used_total: int, seen_total: int) -> float:
    """How often, across the project, a file a query activated was then touched (smoothed)."""
    return (used_total + 1.0) / (seen_total + 20.0)


def learned_constants(used: int, seen: int, rate: float, prior_uses: float = PRIOR_USES):
    """(boost, decay) for a file touched in `used` of the `seen` turns a query activated it,
    relative to the project's base `rate`.

    The file's lift is its uses over the uses an average file would have had in the same
    number of turns, both shrunk by `prior_uses`. A file used as often as the average keeps
    the defaults (0.6, 0.86). Not being opened only counts against a file once it has missed
    uses it was expected to get: where docs are opened once in 500 activations, 200 activations
    without a read say almost nothing, so the corpus cannot drift to the floor.
    """
    lift = (used + prior_uses) / (seen * max(rate, 0.0) + prior_uses)
    boost = min(BOOST_RANGE[1], max(BOOST_RANGE[0], DEFAULT_BOOST * lift ** 0.5))
    decay = DECAY_RANGE[0] + (DECAY_RANGE[1] - DECAY_RANGE[0]) * min(1.0, lift / 2.0)
    return boost, decay
