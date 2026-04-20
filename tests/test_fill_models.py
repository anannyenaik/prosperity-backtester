from __future__ import annotations

from pathlib import Path

from r1bt.fill_models import FILL_MODELS, derive_empirical_fill_profile, resolve_fill_model


ROOT = Path(__file__).resolve().parent.parent


def test_fill_model_ordering_is_monotonic():
    optimistic = FILL_MODELS['optimistic']
    base = FILL_MODELS['base']
    conservative = FILL_MODELS['conservative']

    assert optimistic.passive_fill_rate >= base.passive_fill_rate >= conservative.passive_fill_rate
    assert optimistic.queue_pressure <= base.queue_pressure <= conservative.queue_pressure
    assert optimistic.missed_fill_probability <= base.missed_fill_probability <= conservative.missed_fill_probability
    assert optimistic.adverse_selection_ticks <= base.adverse_selection_ticks <= conservative.adverse_selection_ticks


def test_empirical_fill_model_is_product_specific_and_size_slippage_increases():
    model = FILL_MODELS["empirical_baseline"]
    osmium, osmium_regime = model.config_for("ASH_COATED_OSMIUM", [(9990, 20)], [(10009, 20)])
    pepper, pepper_regime = model.config_for("INTARIAN_PEPPER_ROOT", [(12000, 20)], [(12016, 20)])

    assert osmium_regime in {"normal", "wide_spread"}
    assert pepper_regime == "normal"
    assert osmium.passive_fill_rate != pepper.passive_fill_rate
    assert pepper.size_slippage_ticks(20) > pepper.size_slippage_ticks(8)


def test_fill_model_config_can_be_loaded(tmp_path):
    config = tmp_path / "fills.json"
    config.write_text(
        """
{
  "profiles": {
    "custom_test": {
      "base": "empirical_baseline",
      "products": {
        "ASH_COATED_OSMIUM": {
          "passive_fill_rate": 0.42,
          "missed_fill_probability": 0.12
        }
      }
    }
  }
}
""".strip(),
        encoding="utf-8",
    )

    model = resolve_fill_model("custom_test", config)
    osmium, _regime = model.config_for("ASH_COATED_OSMIUM", [(9990, 20)], [(10009, 20)])

    assert osmium.passive_fill_rate == 0.42
    assert osmium.missed_fill_probability == 0.12


def test_empirical_fill_profile_derivation_writes_artifacts(tmp_path):
    artefact = derive_empirical_fill_profile(
        [ROOT / "live_exports" / "259168" / "259168.log"],
        tmp_path,
        profile_name="test_live",
    )

    assert artefact["row_count"] > 0
    assert "test_live" in artefact["profiles"]
    assert (tmp_path / "empirical_fill_profile.json").is_file()
    assert (tmp_path / "empirical_fill_summary.csv").is_file()
