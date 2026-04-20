from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping

from .noise import resolve_noise_profile
from .platform import PerturbationConfig


@dataclass(frozen=True)
class ResearchScenario:
    name: str
    fill_model: str = "empirical_baseline"
    perturbation: PerturbationConfig = field(default_factory=PerturbationConfig)
    description: str = ""
    tags: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "fill_model": self.fill_model,
            "perturbation": self.perturbation.to_dict(),
            "description": self.description,
            "tags": list(self.tags),
        }


def default_research_scenarios() -> List[ResearchScenario]:
    fitted_noise = resolve_noise_profile("fitted")
    stress_noise = resolve_noise_profile("stress")
    crash_noise = resolve_noise_profile("crash")
    return [
        ResearchScenario(
            name="baseline",
            fill_model="empirical_baseline",
            perturbation=PerturbationConfig(
                latent_price_noise_by_product=fitted_noise,
                scenario_name="baseline",
            ),
            description="Empirical fill baseline with fitted latent Monte Carlo noise.",
            tags=("baseline", "calibrated"),
        ),
        ResearchScenario(
            name="stressed",
            fill_model="empirical_conservative",
            perturbation=PerturbationConfig(
                passive_fill_scale=0.90,
                missed_fill_additive=0.03,
                spread_shift_ticks=1,
                order_book_volume_scale=0.80,
                latent_price_noise_by_product=stress_noise,
                scenario_name="stressed",
            ),
            description="Worse fills, wider books, thinner depth and stressed noise.",
            tags=("stress", "calibrated_band"),
        ),
        ResearchScenario(
            name="crash_shock",
            fill_model="low_fill_quality",
            perturbation=PerturbationConfig(
                passive_fill_scale=0.70,
                missed_fill_additive=0.08,
                spread_shift_ticks=2,
                order_book_volume_scale=0.55,
                latent_price_noise_by_product=crash_noise,
                pepper_slope_scale=0.20,
                shock_tick=5_000,
                shock_by_product={
                    "ASH_COATED_OSMIUM": -25.0,
                    "INTARIAN_PEPPER_ROOT": -250.0,
                },
                slippage_multiplier=1.50,
                scenario_name="crash_shock",
            ),
            description="Late-session negative shock with poor fills and thin books.",
            tags=("crash", "shock"),
        ),
        ResearchScenario(
            name="wide_spread_thin_depth",
            fill_model="empirical_conservative",
            perturbation=PerturbationConfig(
                passive_fill_scale=0.85,
                missed_fill_additive=0.04,
                spread_shift_ticks=2,
                order_book_volume_scale=0.65,
                latent_price_noise_by_product=stress_noise,
                scenario_name="wide_spread_thin_depth",
            ),
            description="Spread and depth stress without an explicit price shock.",
            tags=("spread", "depth"),
        ),
        ResearchScenario(
            name="harsher_slippage",
            fill_model="slippage_stress",
            perturbation=PerturbationConfig(
                latent_price_noise_by_product=fitted_noise,
                slippage_multiplier=1.50,
                scenario_name="harsher_slippage",
            ),
            description="Same market path with larger size-dependent slippage.",
            tags=("slippage", "adverse_selection"),
        ),
        ResearchScenario(
            name="lower_fill_quality",
            fill_model="low_fill_quality",
            perturbation=PerturbationConfig(
                passive_fill_scale=0.75,
                missed_fill_additive=0.07,
                latent_price_noise_by_product=fitted_noise,
                scenario_name="lower_fill_quality",
            ),
            description="Lower passive conversion and more missed fills.",
            tags=("fills", "conservative"),
        ),
    ]


def scenario_from_dict(data: Mapping[str, object]) -> ResearchScenario:
    perturbation_data = dict(data.get("perturbation", {})) if isinstance(data.get("perturbation"), Mapping) else {}
    noise_profile = data.get("noise_profile") or perturbation_data.pop("noise_profile", None)
    noise_scale = float(data.get("noise_scale") or perturbation_data.pop("noise_scale", 1.0))
    if noise_profile and "latent_price_noise_by_product" not in perturbation_data:
        perturbation_data["latent_price_noise_by_product"] = resolve_noise_profile(str(noise_profile), noise_scale)
    perturbation_data.setdefault("scenario_name", str(data.get("name", "scenario")))
    return ResearchScenario(
        name=str(data.get("name", "scenario")),
        fill_model=str(data.get("fill_model", "empirical_baseline")),
        perturbation=PerturbationConfig(**perturbation_data),
        description=str(data.get("description", "")),
        tags=tuple(str(tag) for tag in data.get("tags", []) if tag is not None) if isinstance(data.get("tags"), (list, tuple)) else (),
    )


def scenarios_from_config(items: object | None) -> List[ResearchScenario]:
    if items is None:
        return default_research_scenarios()
    if not isinstance(items, list):
        raise ValueError("Scenario config must be a list")
    return [scenario_from_dict(item) for item in items if isinstance(item, Mapping)]


def scenario_manifest(scenarios: Iterable[ResearchScenario]) -> List[Dict[str, object]]:
    return [scenario.to_dict() for scenario in scenarios]
