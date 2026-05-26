from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.json"

# Wartości fallback gdy brak pliku konfiguracyjnego
_FALLBACK: Dict[str, Any] = {
    "app": {
        "title": "Analizator Oszczędności Dokumentów",
        "subtitle": "Abacus Centrum Księgowe",
        "default_top_n": 5,
        "default_forma": "KPIR",
        "formy_ksiegowosci": ["KPIR", "KSH", "Ryczałt VAT"],
    },
    "pricing": {
        "tiers": [
            {"min_docs": 0,   "max_docs": 50,  "price": "100"},
            {"min_docs": 51,  "max_docs": 100, "price": "180"},
            {"min_docs": 101, "max_docs": 200, "price": "280"},
            {"min_docs": 201, "max_docs": 500, "price": "450"},
        ]
    },
    "ranking": {
        "weights": {"savings": 0.5, "compatibility": 0.3, "safety": 0.2},
        "baseline_compatibility": 0.5,
        "preference_threshold": 0.5,
    },
    "optimizer": {"max_variants": 100},
    "paths": {
        "data_dir": "data",
        "fonts_dir": "data/fonts",
        "system_rules": "data/rules_system.json",
    },
}


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Wczytuje config.json. Zwraca fallback przy braku/błędzie pliku."""
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        logger.warning("Config file not found at %s – using defaults", config_path)
        return _FALLBACK.copy()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        logger.debug("Config loaded from %s", config_path)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Cannot read config %s: %s – using defaults", config_path, exc)
        return _FALLBACK.copy()


def get_pricing(config: Optional[Dict[str, Any]] = None):
    """Buduje obiekt Pricing z konfiguracji.

    Import jest lokalny aby uniknąć cyklu przy inicjalizacji.
    """
    from .optimizer import Pricing, PriceTier

    cfg = config if config is not None else load_config()
    tiers_data: List[Dict] = cfg.get("pricing", {}).get("tiers", [])

    if not tiers_data:
        logger.warning("No pricing tiers in config – using Pricing.default()")
        return Pricing.default()

    tiers = [
        PriceTier(
            min_docs=int(t["min_docs"]),
            max_docs=int(t["max_docs"]),
            price=Decimal(str(t["price"])),
        )
        for t in tiers_data
    ]
    return Pricing(tiers=tiers)


def get_ranking_weights(config: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """Zwraca wagi rankowania z konfiguracji."""
    cfg = config if config is not None else load_config()
    weights = cfg.get("ranking", {}).get("weights", {})
    if not weights:
        from .ranker import DEFAULT_WEIGHTS
        return DEFAULT_WEIGHTS.copy()
    return {k: float(v) for k, v in weights.items()}


def get_app_settings(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Zwraca ustawienia aplikacji (tytuł, forma domyślna, top_n)."""
    cfg = config if config is not None else load_config()
    return dict(cfg.get("app", _FALLBACK["app"]))


def get_optimizer_settings(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Zwraca ustawienia optymizatora (max_variants)."""
    cfg = config if config is not None else load_config()
    return dict(cfg.get("optimizer", _FALLBACK["optimizer"]))
