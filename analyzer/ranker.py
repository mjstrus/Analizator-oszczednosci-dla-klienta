from __future__ import annotations

import json
import logging
from collections import Counter
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set

from .models import Variant
from .rules import RuleEngine

logger = logging.getLogger(__name__)

# Domyślne wagi z planu Unit 6
DEFAULT_WEIGHTS: Dict[str, float] = {
    "savings": 0.5,
    "compatibility": 0.3,
    "safety": 0.2,
}

# Wartość ryzyka 0-1 (im większa = mniej bezpieczne)
RISK_VALUE: Dict[str, float] = {"LOW": 0.0, "MED": 0.5, "HIGH": 1.0}

# Baseline compatibility gdy brak danych historycznych
BASELINE_COMPATIBILITY = 0.5

# Próg częstotliwości – feature musi się pojawić w ≥ 50% decyzji żeby być "preferencją"
PREFERENCE_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def _decision_features(decision: Dict[str, Any]) -> Set[str]:
    """Wyciąga zbiór cech z pojedynczej decyzji klienta.

    Oczekiwany schemat decyzji (zapisywany przez Unit 9):
    {
      "risk_level": "LOW" | "MED" | "HIGH",
      "akcje": {
        "pomijanie": bool,
        "zbiorczy": bool,
        "przesunięcie": bool
      }
    }
    """
    features: Set[str] = set()
    risk = decision.get("risk_level")
    if risk in RISK_VALUE:
        features.add(f"risk:{risk}")
    akcje = decision.get("akcje", {}) or {}
    if akcje.get("pomijanie"):
        features.add("akcja:pomijanie")
    if akcje.get("zbiorczy"):
        features.add("akcja:zbiorczy")
    if akcje.get("przesunięcie"):
        features.add("akcja:przesunięcie")
    return features


def _variant_features(variant: Variant) -> Set[str]:
    """Wyciąga zbiór cech z wariantu (mirroring _decision_features)."""
    features: Set[str] = {f"risk:{variant.risk_level}"}
    if variant.dokumenty_do_pomijania:
        features.add("akcja:pomijanie")
    if variant.grupy_do_zbiorczenia:
        features.add("akcja:zbiorczy")
    if variant.dokumenty_do_przesunięcia:
        features.add("akcja:przesunięcie")
    return features


# ---------------------------------------------------------------------------
# Compatibility scoring
# ---------------------------------------------------------------------------

def compute_compatibility(
    variant: Variant,
    decisions: List[Dict[str, Any]],
    threshold: float = PREFERENCE_THRESHOLD,
) -> float:
    """Oblicza compatibility 0..1 wariantu vs historia decyzji.

    Formuła: matchujące_preferencje / wszystkie_preferencje.
    Preferencja = cecha występująca w ≥ `threshold` decyzji.
    Brak decyzji lub brak wykrywalnych preferencji → BASELINE 0.5.
    """
    if not decisions:
        return BASELINE_COMPATIBILITY

    counts: Counter[str] = Counter()
    for dec in decisions:
        counts.update(_decision_features(dec))

    if not counts:
        return BASELINE_COMPATIBILITY

    min_count = max(1, int(len(decisions) * threshold))
    preferences = {f for f, c in counts.items() if c >= min_count}
    if not preferences:
        return BASELINE_COMPATIBILITY

    matching = len(preferences & _variant_features(variant))
    return matching / len(preferences)


# ---------------------------------------------------------------------------
# Weighted scoring
# ---------------------------------------------------------------------------

def compute_score(
    variant: Variant,
    max_savings: Decimal,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """Łączny score 0..1 jako weighted sum (savings + compatibility + safety)."""
    weights = weights or DEFAULT_WEIGHTS

    if max_savings > 0:
        savings_norm = float(variant.oszczędność) / float(max_savings)
    else:
        savings_norm = 0.0
    savings_norm = max(0.0, min(1.0, savings_norm))

    safety = 1.0 - RISK_VALUE.get(variant.risk_level, 0.5)
    compatibility = variant.compatibility_score

    return (
        weights["savings"] * savings_norm
        + weights["compatibility"] * compatibility
        + weights["safety"] * safety
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rank_variants(
    variants: List[Variant],
    decisions: Optional[List[Dict[str, Any]]] = None,
    top_n: int = 5,
    weights: Optional[Dict[str, float]] = None,
) -> List[Variant]:
    """Ranguje warianty i zwraca TOP N.

    Mutuje przekazane warianty: ustawia `compatibility_score` i `score`.
    Sortuje DESC po `score`, przy remisie LOW risk first.
    """
    if not variants:
        return []

    decisions = decisions or []
    weights = weights or DEFAULT_WEIGHTS

    for v in variants:
        v.compatibility_score = compute_compatibility(v, decisions)

    max_savings = max((v.oszczędność for v in variants), default=Decimal("0"))

    for v in variants:
        v.score = compute_score(v, max_savings, weights)

    ranked = sorted(
        variants,
        key=lambda v: (-v.score, RISK_VALUE.get(v.risk_level, 0.5)),
    )
    top = ranked[:top_n]

    logger.info(
        "Ranked %d variants → TOP %d (max_savings=%s, decisions=%d)",
        len(variants), len(top), max_savings, len(decisions),
    )
    return top


def load_decisions_from_engine(engine: RuleEngine) -> List[Dict[str, Any]]:
    """Wczytuje historię decyzji z pliku klienta zarządzanego przez RuleEngine."""
    path = engine.client_rules_path
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load decisions from %s: %s", path, exc)
        return []
    return data.get("decisions", []) or []
