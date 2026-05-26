from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import pytest

from analyzer.models import Document, Variant
from analyzer.ranker import (
    BASELINE_COMPATIBILITY,
    DEFAULT_WEIGHTS,
    RISK_VALUE,
    compute_compatibility,
    compute_score,
    load_decisions_from_engine,
    rank_variants,
)
from analyzer.rules import RuleEngine


def make_doc(numer: str = "FV/T", wartość: str = "100", risk: str = "LOW") -> Document:
    return Document(
        id=f"id-{numer.replace('/', '-')}",
        numer=numer,
        data=datetime(2025, 11, 1),
        nip_dostawcy="111",
        wartość=Decimal(wartość),
        typ="KP",
        typ_płatności="przelew",
        risk_level=risk,
    )


def make_variant(
    id: int = 1,
    oszczędność: str = "100",
    risk_level: str = "LOW",
    skips: int = 0,
    consolidates: int = 0,
    shifts: int = 0,
    compatibility_score: float = 0.5,
) -> Variant:
    return Variant(
        id=id,
        oszczędność=Decimal(oszczędność),
        dokumenty_do_pomijania=[make_doc(numer=f"S/{i}") for i in range(skips)],
        grupy_do_zbiorczenia=[
            (f"NIP-{i}", [make_doc(numer=f"C/{i}/{j}") for j in range(2)])
            for i in range(consolidates)
        ],
        dokumenty_do_przesunięcia=[
            (make_doc(numer=f"P/{i}"), "2025-12") for i in range(shifts)
        ],
        risk_level=risk_level,
        compatibility_score=compatibility_score,
    )


# ---------------------------------------------------------------------------
# compute_compatibility
# ---------------------------------------------------------------------------

class TestCompatibility:
    def test_pusta_historia_baseline_05(self):
        v = make_variant(risk_level="LOW")
        assert compute_compatibility(v, []) == BASELINE_COMPATIBILITY

    def test_decyzje_bez_features_baseline_05(self):
        v = make_variant(risk_level="LOW")
        # Decyzje istnieją, ale bez risk_level/akcje
        assert compute_compatibility(v, [{}, {"id": "x"}]) == BASELINE_COMPATIBILITY

    def test_klient_preferuje_LOW(self):
        decisions = [
            {"risk_level": "LOW"},
            {"risk_level": "LOW"},
            {"risk_level": "LOW"},
        ]
        c_low = compute_compatibility(make_variant(risk_level="LOW"), decisions)
        c_high = compute_compatibility(make_variant(risk_level="HIGH"), decisions)
        assert c_low > c_high
        assert c_low == 1.0     # 1 preferencja (risk:LOW), 1 match
        assert c_high == 0.0    # 0 matches

    def test_klient_preferuje_pomijanie(self):
        decisions = [
            {"akcje": {"pomijanie": True}},
            {"akcje": {"pomijanie": True}},
        ]
        v_skip = make_variant(skips=1)
        v_no_skip = make_variant(skips=0)
        assert compute_compatibility(v_skip, decisions) > compute_compatibility(v_no_skip, decisions)

    def test_wiele_preferencji_proporcja_matchow(self):
        # Klient preferuje LOW + pomijanie + przesunięcie (3 preferencje)
        decisions = [
            {"risk_level": "LOW", "akcje": {"pomijanie": True, "przesunięcie": True}},
            {"risk_level": "LOW", "akcje": {"pomijanie": True, "przesunięcie": True}},
        ]
        # Wariant matchuje 2/3 → 0.666...
        v = make_variant(risk_level="LOW", skips=1, shifts=0)
        c = compute_compatibility(v, decisions)
        assert abs(c - 2 / 3) < 0.001

    def test_preferencja_tylko_gdy_w_polowie_decyzji(self):
        # Tylko 1 z 4 decyzji ma "zbiorczy" → poniżej threshold 50% → nie jest preferencją
        decisions = [
            {"risk_level": "LOW"},
            {"risk_level": "LOW"},
            {"risk_level": "LOW"},
            {"risk_level": "LOW", "akcje": {"zbiorczy": True}},
        ]
        # Tylko risk:LOW jest preferencją (4/4) → wariant LOW dostaje 1.0
        v_low = make_variant(risk_level="LOW", consolidates=0)
        assert compute_compatibility(v_low, decisions) == 1.0

    def test_custom_threshold(self):
        decisions = [
            {"risk_level": "LOW"},
            {"risk_level": "HIGH"},
        ]
        # threshold=0.5 → preferencje: oba (każdy 1/2 = 50%)
        v_low = make_variant(risk_level="LOW")
        # 2 preferencje (risk:LOW, risk:HIGH), wariant ma 1 → 0.5
        assert compute_compatibility(v_low, decisions, threshold=0.5) == 0.5


# ---------------------------------------------------------------------------
# compute_score
# ---------------------------------------------------------------------------

class TestComputeScore:
    def test_low_risk_dostaje_safety_bonus(self):
        v_low = make_variant(oszczędność="100", risk_level="LOW", compatibility_score=0.5)
        v_high = make_variant(oszczędność="100", risk_level="HIGH", compatibility_score=0.5)
        max_s = Decimal("100")
        assert compute_score(v_low, max_s) > compute_score(v_high, max_s)

    def test_savings_normalizowane(self):
        v_full = make_variant(oszczędność="100")
        v_half = make_variant(oszczędność="50")
        # max_savings = 100; v_full savings_norm = 1.0; v_half = 0.5
        s_full = compute_score(v_full, Decimal("100"))
        s_half = compute_score(v_half, Decimal("100"))
        # Różnica = 0.5 (savings_norm diff) * 0.5 (weight) = 0.25
        assert abs((s_full - s_half) - 0.25) < 0.001

    def test_max_savings_zero_bezpieczny_div(self):
        v = make_variant(oszczędność="100", risk_level="LOW", compatibility_score=0.5)
        # max=0 → savings_norm=0 → score = 0.3*0.5 + 0.2*1.0 = 0.35
        score = compute_score(v, Decimal("0"))
        assert abs(score - 0.35) < 0.001

    def test_custom_weights(self):
        v = make_variant(oszczędność="100", risk_level="LOW", compatibility_score=0.5)
        # All weight on savings → score = 1.0 * 1.0 = 1.0
        weights = {"savings": 1.0, "compatibility": 0.0, "safety": 0.0}
        assert compute_score(v, Decimal("100"), weights) == 1.0

    def test_risk_value_LOW_MED_HIGH(self):
        assert RISK_VALUE["LOW"] == 0.0
        assert RISK_VALUE["MED"] == 0.5
        assert RISK_VALUE["HIGH"] == 1.0


# ---------------------------------------------------------------------------
# rank_variants – główne API
# ---------------------------------------------------------------------------

class TestRankVariants:
    def test_pusty_input_zwraca_puste(self):
        assert rank_variants([], []) == []

    def test_top_n_dokladnie_5_jesli_dosc_wariantow(self):
        variants = [make_variant(id=i, oszczędność=str(100 + i)) for i in range(10)]
        result = rank_variants(variants, decisions=[], top_n=5)
        assert len(result) == 5

    def test_mniej_niz_top_n_zwraca_wszystkie(self):
        variants = [make_variant(id=i, oszczędność=str(100 + i)) for i in range(3)]
        result = rank_variants(variants, decisions=[], top_n=5)
        assert len(result) == 3

    def test_sortowanie_DESC_po_score(self):
        variants = [make_variant(id=i, oszczędność=str(100 * (i + 1))) for i in range(5)]
        result = rank_variants(variants, decisions=[], top_n=5)
        scores = [v.score for v in result]
        assert scores == sorted(scores, reverse=True)

    def test_mutuje_compatibility_i_score(self):
        v = make_variant(id=1, oszczędność="100")
        original_score = v.score
        rank_variants([v], decisions=[{"risk_level": "LOW"}], top_n=5)
        assert v.compatibility_score != BASELINE_COMPATIBILITY or v.score != original_score

    def test_planowany_scenariusz_LOW_z_match_wygrywa_z_HIGH_z_savings(self):
        """Plan: V1 (500 zł, LOW, 95% match) > V2 (600 zł, HIGH, 40% match)."""
        # Build history that gives v1 ≈95% match (LOW)
        decisions: List[Dict[str, Any]] = [{"risk_level": "LOW"} for _ in range(10)]

        v1 = make_variant(id=1, oszczędność="500", risk_level="LOW")
        v2 = make_variant(id=2, oszczędność="600", risk_level="HIGH")

        result = rank_variants([v1, v2], decisions=decisions, top_n=5)
        # V1 powinien być first mimo niższych savings
        assert result[0].id == 1
        assert result[1].id == 2

    def test_baseline_compatibility_dla_pustej_historii(self):
        variants = [make_variant(id=1, oszczędność="100", risk_level="LOW")]
        result = rank_variants(variants, decisions=[], top_n=5)
        assert result[0].compatibility_score == BASELINE_COMPATIBILITY

    def test_remis_score_LOW_first(self):
        # Identyczne savings + identyczna historia → safety bonus decyduje
        v_low = make_variant(id=1, oszczędność="100", risk_level="LOW")
        v_high = make_variant(id=2, oszczędność="100", risk_level="HIGH")
        result = rank_variants([v_high, v_low], decisions=[], top_n=5)
        assert result[0].risk_level == "LOW"

    def test_savings_norm_w_zakresie(self):
        variants = [
            make_variant(id=1, oszczędność="50"),
            make_variant(id=2, oszczędność="100"),
            make_variant(id=3, oszczędność="200"),
        ]
        rank_variants(variants, decisions=[], top_n=5)
        # Wszystkie score w 0-1
        for v in variants:
            assert 0.0 <= v.score <= 1.0


# ---------------------------------------------------------------------------
# load_decisions_from_engine
# ---------------------------------------------------------------------------

class TestLoadDecisionsFromEngine:
    def test_brak_pliku_zwraca_puste(self, tmp_path: Path):
        engine = RuleEngine("XYZ", data_dir=tmp_path)
        assert load_decisions_from_engine(engine) == []

    def test_laduje_decisions_z_pliku(self, tmp_path: Path):
        path = tmp_path / "rules_klient_XYZ.json"
        path.write_text(
            json.dumps({
                "klient_id": "XYZ",
                "rules": [],
                "decisions": [
                    {"id": "dec_001", "miesiąc": "2025-11", "risk_level": "LOW"},
                    {"id": "dec_002", "miesiąc": "2025-12", "risk_level": "MED"},
                ],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        engine = RuleEngine("XYZ", data_dir=tmp_path)
        decisions = load_decisions_from_engine(engine)
        assert len(decisions) == 2
        assert decisions[0]["id"] == "dec_001"

    def test_brak_sekcji_decisions(self, tmp_path: Path):
        path = tmp_path / "rules_klient_XYZ.json"
        path.write_text(
            json.dumps({"klient_id": "XYZ", "rules": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        engine = RuleEngine("XYZ", data_dir=tmp_path)
        assert load_decisions_from_engine(engine) == []

    def test_uszkodzony_json_zwraca_puste(self, tmp_path: Path):
        path = tmp_path / "rules_klient_XYZ.json"
        path.write_text("{not valid", encoding="utf-8")
        engine = RuleEngine("XYZ", data_dir=tmp_path)
        assert load_decisions_from_engine(engine) == []


# ---------------------------------------------------------------------------
# Integration: pełny pipeline Faza 1+2+3
# ---------------------------------------------------------------------------

class TestIntegrationFaza3:
    def test_pelny_pipeline_z_ranking(self):
        """Parser → Tax Advisor → Constraints → Optimizer → Ranker."""
        import shutil

        from analyzer.constraints import classify
        from analyzer.optimizer import PriceTier, Pricing, generate_variants
        from analyzer.parser import parse_jpk_fa
        from analyzer.tax_advisor import assess_all

        xml = (Path(__file__).parent.parent / "fixtures" / "sample_jpk_fa.xml").read_bytes()
        docs = parse_jpk_fa(xml)
        assess_all(docs, forma="KPIR")

        tmp = Path("/tmp/test_ranker_integration")
        tmp.mkdir(exist_ok=True)
        shutil.copy(
            Path(__file__).parent.parent / "data" / "rules_system.json",
            tmp / "rules_system.json",
        )
        engine = RuleEngine("TEST_RANKER", data_dir=tmp)
        result = classify(docs, forma="KPIR", engine=engine)

        pricing = Pricing([
            PriceTier(0, 2, Decimal("100")),
            PriceTier(3, 5, Decimal("200")),
            PriceTier(6, 10, Decimal("300")),
        ])
        variants = generate_variants(
            result.remaining,
            no_go_count=len(result.no_go),
            pricing=pricing,
            target_period="2025-12",
        )

        decisions = load_decisions_from_engine(engine)
        top_5 = rank_variants(variants, decisions=decisions, top_n=5)

        assert len(top_5) <= 5
        for v in top_5:
            assert 0.0 <= v.score <= 1.0
            assert 0.0 <= v.compatibility_score <= 1.0
        # Sortowanie zachowane
        assert [v.score for v in top_5] == sorted([v.score for v in top_5], reverse=True)
