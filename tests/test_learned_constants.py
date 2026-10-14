"""Learned boost/decay: relative to the project's base rate, so the corpus cannot drift to the floor."""

import pytest

from hologram.learned_constants import base_rate, learned_constants


def test_an_average_file_keeps_the_defaults():
    for used_total, seen_total, used, seen in [(49, 980, 10, 200), (399, 980, 80, 200)]:
        boost, decay = learned_constants(used, seen, base_rate(used_total, seen_total))
        assert boost == pytest.approx(0.6)
        assert decay == pytest.approx(0.86)


def test_unopened_files_are_not_floored_where_docs_are_rarely_opened():
    """The old learner had cl33_oplm's main work log at 'useful 7/1028' and the weakest boost."""
    rate = base_rate(1, 1000)
    boost, _ = learned_constants(0, 200, rate)
    assert boost > 0.5
    assert learned_constants(7, 1028, rate)[0] == 0.8


def test_missing_expected_uses_weakens_and_real_use_strengthens():
    rate = base_rate(49, 980)                      # opened once in 20 activations
    worklog = learned_constants(30, 40, rate)      # expected 2 uses, got 30
    ignored = learned_constants(0, 200, rate)      # expected 10 uses, got none
    fresh = learned_constants(0, 0, rate)
    assert worklog == (0.8, pytest.approx(0.92))
    assert ignored[0] == 0.4 and ignored[1] < 0.81
    assert fresh == (pytest.approx(0.6), pytest.approx(0.86))


def test_a_single_unused_activation_barely_moves_a_file():
    boost, _ = learned_constants(0, 1, base_rate(49, 980))
    assert 0.58 < boost < 0.6
