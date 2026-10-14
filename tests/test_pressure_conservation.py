"""The pressure budget: fixed size, enforced so the leaders keep their lead."""

import pytest

from hologram.pressure import PressureConfig, apply_activation, compute_effective_budget, redistribute_pressure
from hologram.system import CognitiveFile


def _files(pressures):
    return {f'f{i}.md': CognitiveFile(f'f{i}.md', content='', raw_pressure=p)
            for i, p in enumerate(pressures)}


def test_budget_does_not_grow_with_the_corpus():
    config = PressureConfig()
    assert compute_effective_budget(8, config) == 10.0
    assert compute_effective_budget(500, config) == 10.0


def test_over_budget_the_tail_pays_and_the_leaders_keep_their_lead():
    files = _files([1.0, 0.95, 0.9] + [0.3] * 60)
    redistribute_pressure(files, PressureConfig())
    pressures = [f.raw_pressure for f in files.values()]
    assert sum(pressures) == pytest.approx(10.0)
    assert pressures[0] > 0.8 and pressures[0] - pressures[3] == pytest.approx(0.7)
    assert max(pressures[3:]) < 0.15
    # Proportional scaling taxes the leaders hardest: the same input halves them.
    scaled = _files([1.0, 0.95, 0.9] + [0.3] * 60)
    redistribute_pressure(scaled, PressureConfig(conservation_mode='scale'))
    assert scaled['f0.md'].raw_pressure < 0.5


def test_under_budget_nothing_is_taken_and_overshoot_is_clamped():
    files = _files([1.7, 0.4, 0.0])
    redistribute_pressure(files, PressureConfig())
    assert [f.raw_pressure for f in files.values()] == [1.0, 0.4, 0.0]


def test_a_strong_match_stays_ahead_of_weak_ones_through_the_budget():
    files = _files([0.2] * 40)
    scores = {f'f{i}.md': 0.9 for i in range(1, 30)}
    scores['f0.md'] = 2.5
    config = PressureConfig()
    apply_activation(files, scores, config)
    redistribute_pressure(files, config)
    assert files['f0.md'].raw_pressure > files['f1.md'].raw_pressure + 0.5
    assert files['f0.md'].raw_pressure == 1.0
    assert sum(f.raw_pressure for f in files.values()) <= 10.0
