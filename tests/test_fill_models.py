from __future__ import annotations

from r1bt.fill_models import FILL_MODELS


def test_fill_model_ordering_is_monotonic():
    optimistic = FILL_MODELS['optimistic']
    base = FILL_MODELS['base']
    conservative = FILL_MODELS['conservative']

    assert optimistic.passive_fill_rate >= base.passive_fill_rate >= conservative.passive_fill_rate
    assert optimistic.queue_pressure <= base.queue_pressure <= conservative.queue_pressure
    assert optimistic.missed_fill_probability <= base.missed_fill_probability <= conservative.missed_fill_probability
    assert optimistic.adverse_selection_ticks <= base.adverse_selection_ticks <= conservative.adverse_selection_ticks
