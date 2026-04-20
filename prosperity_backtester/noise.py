from __future__ import annotations

from typing import Dict

from .metadata import PRODUCTS


FITTED_PRICE_NOISE: Dict[str, float] = {
    "ASH_COATED_OSMIUM": 3.70,
    "INTARIAN_PEPPER_ROOT": 3.22,
}


NOISE_PROFILE_MULTIPLIERS = {
    "none": 0.0,
    "fitted": 1.0,
    "baseline": 1.0,
    "stress": 1.35,
    "crash": 2.25,
}


def resolve_noise_profile(name: str | None, scale: float = 1.0) -> Dict[str, float]:
    profile = (name or "none").lower()
    if profile not in NOISE_PROFILE_MULTIPLIERS:
        available = ", ".join(sorted(NOISE_PROFILE_MULTIPLIERS))
        raise KeyError(f"Unknown noise profile: {name}. Available: {available}")
    multiplier = NOISE_PROFILE_MULTIPLIERS[profile] * max(0.0, float(scale))
    if multiplier <= 0.0:
        return {}
    return {product: FITTED_PRICE_NOISE[product] * multiplier for product in PRODUCTS}


def describe_noise_profiles() -> Dict[str, object]:
    return {
        "fitted_values": dict(FITTED_PRICE_NOISE),
        "profiles": dict(NOISE_PROFILE_MULTIPLIERS),
        "notes": [
            "Fitted values are current R1/R2 empirical baselines, not permanent truths.",
            "Scenario profiles perturb the fitted baseline so robustness is visible.",
            "The profile controls latent Monte Carlo noise; --price-noise-std still controls visible-book jitter.",
        ],
    }
