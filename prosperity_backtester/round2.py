from __future__ import annotations

import random
from dataclasses import asdict, dataclass, replace
from typing import Dict, Iterable, List, Mapping


@dataclass(frozen=True)
class AccessScenario:
    """Configurable Round 2 Market Access Fee and extra-quote assumption.

    This object deliberately models only local assumptions. The official website
    auction and matching details are not known from the public CSVs, so callers
    choose whether the contract is won and how useful the extra access is.
    """

    name: str = "no_access"
    enabled: bool = False
    contract_won: bool = False
    mode: str = "none"
    maf_bid: float = 0.0
    extra_quote_fraction: float = 0.25
    access_quality: float = 1.0
    access_probability: float = 1.0
    book_volume_share: float = 1.0
    passive_fill_rate_multiplier: float = 1.0
    passive_fill_rate_bonus: float = 0.0
    missed_fill_reduction: float = 0.0
    trade_volume_share: float = 1.0

    def to_dict(self) -> Dict[str, object]:
        data = asdict(self)
        data["active_if_won"] = self.active_if_won
        data["expected_extra_quote_fraction"] = self.expected_extra_quote_fraction
        data["maf_cost"] = self.maf_cost
        return data

    @property
    def active_if_won(self) -> bool:
        return (
            self.enabled
            and self.contract_won
            and self.mode != "none"
            and self.extra_quote_fraction > 0
            and self.access_quality > 0
        )

    @property
    def expected_extra_quote_fraction(self) -> float:
        probability = self.access_probability if self.mode == "stochastic" else 1.0
        return self._base_extra_fraction() * max(0.0, min(1.0, probability))

    @property
    def maf_cost(self) -> float:
        return float(self.maf_bid) if self.contract_won else 0.0

    def _base_extra_fraction(self) -> float:
        return max(0.0, float(self.extra_quote_fraction)) * max(0.0, float(self.access_quality))

    def active_extra_fraction(self, rng: random.Random) -> float:
        if not self.active_if_won:
            return 0.0
        if self.mode == "stochastic":
            probability = max(0.0, min(1.0, float(self.access_probability)))
            if rng.random() > probability:
                return 0.0
        return self._base_extra_fraction()

    def book_volume_multiplier(self, extra_fraction: float) -> float:
        return 1.0 + max(0.0, extra_fraction) * max(0.0, float(self.book_volume_share))

    def passive_rate_multiplier(self, extra_fraction: float) -> float:
        if extra_fraction <= 0:
            return 1.0
        return max(0.0, float(self.passive_fill_rate_multiplier))

    def passive_rate_bonus(self, extra_fraction: float) -> float:
        if extra_fraction <= 0:
            return 0.0
        return max(0.0, float(self.passive_fill_rate_bonus))

    def effective_missed_fill_reduction(self, extra_fraction: float) -> float:
        if extra_fraction <= 0:
            return 0.0
        return max(0.0, float(self.missed_fill_reduction))

    def trade_volume_multiplier(self, extra_fraction: float) -> float:
        return 1.0 + max(0.0, extra_fraction) * max(0.0, float(self.trade_volume_share))

    def has_access_effect(self, extra_fraction: float) -> bool:
        if extra_fraction <= 0:
            return False
        return (
            self.book_volume_multiplier(extra_fraction) != 1.0
            or self.passive_rate_multiplier(extra_fraction) != 1.0
            or self.passive_rate_bonus(extra_fraction) > 0.0
            or self.effective_missed_fill_reduction(extra_fraction) > 0.0
            or self.trade_volume_multiplier(extra_fraction) != 1.0
        )


NO_ACCESS_SCENARIO = AccessScenario()


ASSUMPTION_REGISTRY = {
    "grounded": [
        "Round 2 trades ASH_COATED_OSMIUM and INTARIAN_PEPPER_ROOT.",
        "The Market Access Fee can grant access to an extra 25% of quotes.",
        "Only the top 50% of total MAF bids get the contract.",
        "Traders that do not win the contract do not pay the MAF and do not get extra quote access.",
    ],
    "configurable": [
        "Whether a local scenario assumes the contract is won.",
        "How much of the extra 25% quote access is useful.",
        "Whether access is deterministic or stochastic by tick.",
        "How access changes visible book volume, passive fill probability and fill opportunity volume.",
        "The MAF bid deducted from net PnL when the contract is won.",
    ],
    "unknown": [
        "The official website's exact extra-quote selection process.",
        "Exact queue priority and passive fill mechanics for the extra quotes.",
        "Whether local hidden quote access maps one-to-one to displayed volume, trades, or fill odds.",
        "The distribution of other teams' MAF bids before upload.",
    ],
}


DEFAULT_ROUND2_SCENARIOS = [
    NO_ACCESS_SCENARIO,
    AccessScenario(
        name="access_low_quality",
        enabled=True,
        contract_won=True,
        mode="deterministic",
        access_quality=0.40,
        passive_fill_rate_multiplier=1.05,
        missed_fill_reduction=0.01,
    ),
    AccessScenario(
        name="access_base",
        enabled=True,
        contract_won=True,
        mode="deterministic",
        access_quality=0.75,
        passive_fill_rate_multiplier=1.12,
        missed_fill_reduction=0.02,
    ),
    AccessScenario(
        name="access_stochastic",
        enabled=True,
        contract_won=True,
        mode="stochastic",
        access_quality=0.80,
        access_probability=0.65,
        passive_fill_rate_multiplier=1.15,
        missed_fill_reduction=0.02,
    ),
]


def access_scenario_from_dict(data: Mapping[str, object] | None) -> AccessScenario:
    if not data:
        return NO_ACCESS_SCENARIO
    allowed = set(AccessScenario.__dataclass_fields__)
    cleaned = {key: value for key, value in dict(data).items() if key in allowed}
    scenario = AccessScenario(**cleaned)
    if scenario.mode not in {"none", "deterministic", "stochastic"}:
        raise ValueError(f"Unknown access scenario mode: {scenario.mode}")
    return scenario


def expand_scenarios(
    scenario_configs: Iterable[Mapping[str, object]] | None,
    maf_values: Iterable[object] | None = None,
) -> List[AccessScenario]:
    base = [access_scenario_from_dict(item) for item in scenario_configs] if scenario_configs else list(DEFAULT_ROUND2_SCENARIOS)
    values = list(maf_values or [])
    if not values:
        return base

    expanded: List[AccessScenario] = []
    for scenario in base:
        if not scenario.enabled:
            expanded.append(scenario)
            continue
        for value in values:
            maf_bid = float(value)
            suffix = str(int(maf_bid)) if maf_bid.is_integer() else str(maf_bid).replace(".", "_")
            expanded.append(replace(scenario, name=f"{scenario.name}_maf_{suffix}", maf_bid=maf_bid))
    return expanded
