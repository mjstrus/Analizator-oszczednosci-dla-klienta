"""Tests for analyzer/config_loader.py + config.json – Unit 11."""
from __future__ import annotations

import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from analyzer.config_loader import (
    _FALLBACK,
    get_app_settings,
    get_optimizer_settings,
    get_pricing,
    get_ranking_weights,
    load_config,
)
from analyzer.optimizer import Pricing

_PROJECT_ROOT = Path(__file__).parent.parent
_CONFIG_FILE = _PROJECT_ROOT / "config.json"


# ---------------------------------------------------------------------------
# config.json validity
# ---------------------------------------------------------------------------

class TestConfigFile:
    def test_config_file_exists(self):
        assert _CONFIG_FILE.exists(), "config.json musi istnieć w katalogu głównym"

    def test_config_file_valid_json(self):
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_config_has_required_sections(self):
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        for section in ("app", "pricing", "ranking", "optimizer", "paths"):
            assert section in data, f"Brak sekcji '{section}' w config.json"

    def test_pricing_tiers_count(self):
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        tiers = data["pricing"]["tiers"]
        assert len(tiers) == 4

    def test_pricing_tiers_structure(self):
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        for tier in data["pricing"]["tiers"]:
            assert "min_docs" in tier
            assert "max_docs" in tier
            assert "price" in tier

    def test_ranking_weights_sum_to_one(self):
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        weights = data["ranking"]["weights"]
        total = sum(float(v) for v in weights.values())
        assert abs(total - 1.0) < 1e-9, f"Wagi sumują się do {total}, a nie do 1.0"

    def test_ranking_has_all_weight_keys(self):
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        weights = data["ranking"]["weights"]
        for key in ("savings", "compatibility", "safety"):
            assert key in weights

    def test_app_section_has_required_keys(self):
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        for key in ("title", "default_top_n", "default_forma", "formy_ksiegowosci"):
            assert key in data["app"]

    def test_default_top_n_is_positive_int(self):
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        top_n = data["app"]["default_top_n"]
        assert isinstance(top_n, int) and top_n > 0

    def test_formy_ksiegowosci_contains_known_values(self):
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        formy = data["app"]["formy_ksiegowosci"]
        for forma in ("KPIR", "KSH", "Ryczałt VAT"):
            assert forma in formy


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_loads_project_config(self):
        cfg = load_config()
        assert isinstance(cfg, dict)
        assert "pricing" in cfg

    def test_loads_custom_path(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump({"app": {"title": "Test"}}, f)
            path = Path(f.name)
        cfg = load_config(path)
        assert cfg["app"]["title"] == "Test"
        path.unlink()

    def test_missing_file_returns_fallback(self):
        cfg = load_config(Path("/nonexistent/config.json"))
        assert "pricing" in cfg
        assert "ranking" in cfg

    def test_invalid_json_returns_fallback(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("this is not json {{{")
            path = Path(f.name)
        cfg = load_config(path)
        assert "pricing" in cfg
        path.unlink()

    def test_fallback_weights_sum_to_one(self):
        weights = _FALLBACK["ranking"]["weights"]
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# get_pricing
# ---------------------------------------------------------------------------

class TestGetPricing:
    def test_returns_pricing_object(self):
        p = get_pricing()
        assert isinstance(p, Pricing)

    def test_has_four_tiers(self):
        p = get_pricing()
        assert len(p.tiers) == 4

    def test_first_tier_price(self):
        p = get_pricing()
        assert p.price_for(0) == Decimal("100")
        assert p.price_for(50) == Decimal("100")

    def test_second_tier_price(self):
        p = get_pricing()
        assert p.price_for(51) == Decimal("180")
        assert p.price_for(100) == Decimal("180")

    def test_third_tier_price(self):
        p = get_pricing()
        assert p.price_for(101) == Decimal("280")
        assert p.price_for(200) == Decimal("280")

    def test_fourth_tier_price(self):
        p = get_pricing()
        assert p.price_for(201) == Decimal("450")
        assert p.price_for(500) == Decimal("450")

    def test_matches_pricing_default(self):
        from analyzer.optimizer import Pricing as P
        config_pricing = get_pricing()
        default = P.default()
        for count in (0, 50, 51, 100, 101, 200, 201, 500):
            assert config_pricing.price_for(count) == default.price_for(count), \
                f"Niezgodność dla count={count}"

    def test_custom_config(self):
        custom = {
            "pricing": {
                "tiers": [
                    {"min_docs": 0, "max_docs": 9999, "price": "999"}
                ]
            }
        }
        p = get_pricing(custom)
        assert p.price_for(100) == Decimal("999")

    def test_empty_tiers_returns_default(self):
        p = get_pricing({"pricing": {"tiers": []}})
        assert isinstance(p, Pricing)
        assert len(p.tiers) > 0


# ---------------------------------------------------------------------------
# get_ranking_weights
# ---------------------------------------------------------------------------

class TestGetRankingWeights:
    def test_returns_dict(self):
        w = get_ranking_weights()
        assert isinstance(w, dict)

    def test_has_all_keys(self):
        w = get_ranking_weights()
        assert set(w.keys()) == {"savings", "compatibility", "safety"}

    def test_values_are_floats(self):
        w = get_ranking_weights()
        for v in w.values():
            assert isinstance(v, float)

    def test_sum_to_one(self):
        w = get_ranking_weights()
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_matches_ranker_defaults(self):
        from analyzer.ranker import DEFAULT_WEIGHTS
        w = get_ranking_weights()
        for key in DEFAULT_WEIGHTS:
            assert w[key] == DEFAULT_WEIGHTS[key]

    def test_empty_weights_returns_defaults(self):
        w = get_ranking_weights({"ranking": {}})
        assert "savings" in w

    def test_custom_weights(self):
        custom = {"ranking": {"weights": {"savings": 1.0, "compatibility": 0.0, "safety": 0.0}}}
        w = get_ranking_weights(custom)
        assert w["savings"] == 1.0


# ---------------------------------------------------------------------------
# get_app_settings
# ---------------------------------------------------------------------------

class TestGetAppSettings:
    def test_returns_dict(self):
        s = get_app_settings()
        assert isinstance(s, dict)

    def test_has_title(self):
        s = get_app_settings()
        assert "title" in s
        assert len(s["title"]) > 0

    def test_default_top_n(self):
        s = get_app_settings()
        assert s["default_top_n"] == 5

    def test_default_forma(self):
        s = get_app_settings()
        assert s["default_forma"] == "KPIR"

    def test_formy_list(self):
        s = get_app_settings()
        assert isinstance(s["formy_ksiegowosci"], list)
        assert len(s["formy_ksiegowosci"]) >= 3


# ---------------------------------------------------------------------------
# get_optimizer_settings
# ---------------------------------------------------------------------------

class TestGetOptimizerSettings:
    def test_returns_dict(self):
        s = get_optimizer_settings()
        assert isinstance(s, dict)

    def test_max_variants_positive(self):
        s = get_optimizer_settings()
        assert s["max_variants"] > 0

    def test_max_variants_value(self):
        s = get_optimizer_settings()
        assert s["max_variants"] == 100
