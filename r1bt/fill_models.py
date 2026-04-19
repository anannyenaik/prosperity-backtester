from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class FillModel:
    name: str
    passive_fill_rate: float
    same_price_queue_share: float
    queue_pressure: float
    missed_fill_probability: float
    adverse_selection_ticks: int
    aggressive_slippage_ticks: int = 0

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


FILL_MODELS: Dict[str, FillModel] = {
    "optimistic": FillModel(
        name="optimistic",
        passive_fill_rate=1.00,
        same_price_queue_share=0.00,
        queue_pressure=0.00,
        missed_fill_probability=0.00,
        adverse_selection_ticks=0,
    ),
    "base": FillModel(
        name="base",
        passive_fill_rate=0.65,
        same_price_queue_share=0.60,
        queue_pressure=0.85,
        missed_fill_probability=0.03,
        adverse_selection_ticks=0,
    ),
    "conservative": FillModel(
        name="conservative",
        passive_fill_rate=0.35,
        same_price_queue_share=1.00,
        queue_pressure=1.25,
        missed_fill_probability=0.10,
        adverse_selection_ticks=1,
    ),
}


def resolve_fill_model(name: Optional[str] = None) -> FillModel:
    if not name:
        return FILL_MODELS["base"]
    if name not in FILL_MODELS:
        raise KeyError(f"Unknown fill model: {name}. Available: {', '.join(sorted(FILL_MODELS))}")
    return FILL_MODELS[name]
