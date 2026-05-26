from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List

import pytest

from analyzer.models import Document, Variant
from analyzer.optimizer import (
    PriceTier,
    Pricing,
    _build_variant,
    _deduplicate,
    _group_by_supplier,
    _risk_max,
    _signature,
    generate_variants,
)


def make_doc(
    numer: str = "FV/1",
    wartość: str = "100",
    risk_level: str = "LOW",
    nip: str = "111",
    typ: str = "KP",
    typ_płatności: str = "przelew",
) -> Document:
    return Document(
        id=f"id-{numer.replace('/', '-')}",
        numer=numer,
        data=datetime(2025, 11, 1),
        nip_dostawcy=nip,
        wartość=Decimal(wartość),
        typ=typ,
        typ_płatności=typ_płatności,
        risk_level=risk_level,
    )


@pytest.fixture
def small_pricing() -> Pricing:
    """Mały cennik dla czystych testów: 0-10 → 100, 11-20 → 200, 21-30 → 300."""
    return Pricing(tiers=[
        PriceTier(0, 10, Decimal("100")),
        PriceTier(11, 20, Decimal("200")),
        PriceTier(21, 30, Decimal("300")),
    ])


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

class TestPricing:
    def test_price_for_w_zakresie(self, small_pricing: Pricing):
        assert small_pricing.price_for(5) == Decimal("100")
        assert small_pricing.price_for(15) == Decimal("200")
        assert small_pricing.price_for(25) == Decimal("300")

    def test_price_for_na_granicach(self, small_pricing: Pricing):
        assert small_pricing.price_for(0) == Decimal("100")
        assert small_pricing.price_for(10) == Decimal("100")
        assert small_pricing.price_for(11) == Decimal("200")
        assert small_pricing.price_for(20) == Decimal("200")
        assert small_pricing.price_for(21) == Decimal("300")

    def test_price_for_powyzej_capping(self, small_pricing: Pricing):
        # Powyżej najwyższego progu → cena najwyższego progu
        assert small_pricing.price_for(1000) == Decimal("300")

    def test_lower_tier_max(self, small_pricing: Pricing):
        assert small_pricing.lower_tier_max(15) == 10  # 11-20 → niżej 0-10
        assert small_pricing.lower_tier_max(25) == 20  # 21-30 → niżej 11-20

    def test_lower_tier_max_na_najnizszym(self, small_pricing: Pricing):
        # 0-10 → już najniższy
        assert small_pricing.lower_tier_max(5) is None

    def test_default_pricing_ma_tiery_z_planu(self):
        p = Pricing.default()
        assert p.price_for(30) == Decimal("100")    # 0-50
        assert p.price_for(75) == Decimal("180")    # 51-100
        assert p.price_for(150) == Decimal("280")   # 101-200
        assert p.price_for(300) == Decimal("450")   # 201-500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestRiskMax:
    def test_high_wygrywa(self):
        docs = [make_doc(risk_level="LOW"), make_doc(risk_level="HIGH"), make_doc(risk_level="MED")]
        assert _risk_max(docs) == "HIGH"

    def test_med_gdy_brak_high(self):
        docs = [make_doc(risk_level="LOW"), make_doc(risk_level="MED")]
        assert _risk_max(docs) == "MED"

    def test_low_domyslnie(self):
        # Brak ocenionych dokumentów (None) → LOW
        docs = [make_doc(risk_level=None), make_doc(risk_level=None)]
        assert _risk_max(docs) == "LOW"

    def test_pusta_lista(self):
        assert _risk_max([]) == "LOW"


class TestGroupBySupplier:
    def test_grupuje_po_nip_i_typ(self):
        docs = [
            make_doc(numer="FV/1", nip="111", typ="KP"),
            make_doc(numer="FV/2", nip="111", typ="KP"),
            make_doc(numer="FV/3", nip="111", typ="NT"),
            make_doc(numer="FV/4", nip="222", typ="KP"),
        ]
        groups = _group_by_supplier(docs)
        assert len(groups) == 3
        assert len(groups[("111", "KP")]) == 2
        assert len(groups[("111", "NT")]) == 1
        assert len(groups[("222", "KP")]) == 1

    def test_pomija_bez_nip(self):
        docs = [
            make_doc(numer="FV/1", nip=""),
            make_doc(numer="FV/2", nip="111"),
        ]
        groups = _group_by_supplier(docs)
        assert len(groups) == 1
        assert ("111", "KP") in groups


# ---------------------------------------------------------------------------
# _build_variant
# ---------------------------------------------------------------------------

class TestBuildVariant:
    def test_zero_savings_zwraca_none(self, small_pricing: Pricing):
        # 5 dokumentów, pomiń 1 → 4 dokumenty, ten sam tier (0-10) → 0 savings
        skip = [make_doc(numer="FV/1")]
        v = _build_variant(skip, [], [], no_go_count=0, remaining_count=5, pricing=small_pricing)
        assert v is None

    def test_savings_wycenione_poprawnie(self, small_pricing: Pricing):
        # 12 docs (tier 200) → pomiń 2 → 10 docs (tier 100) → savings 100
        skip = [make_doc(numer=f"FV/{i}") for i in range(2)]
        v = _build_variant(skip, [], [], no_go_count=0, remaining_count=12, pricing=small_pricing)
        assert v is not None
        assert v.oszczędność == Decimal("100")

    def test_overlap_zwraca_none(self, small_pricing: Pricing):
        # Ten sam dokument w skip i w shift → invalid
        doc = make_doc(numer="FV/X")
        v = _build_variant(
            [doc], [], [(doc, "2025-12")],
            no_go_count=0, remaining_count=12, pricing=small_pricing,
        )
        assert v is None

    def test_konsolidacja_redukuje_o_K_minus_1(self, small_pricing: Pricing):
        # 12 docs total; konsolidacja 3 dokumentów → -2 → 10 docs → tier 100 → 100 savings
        group = [make_doc(numer=f"FV/G{i}", nip="555") for i in range(3)]
        v = _build_variant([], [("555", group)], [], no_go_count=0, remaining_count=12, pricing=small_pricing)
        assert v is not None
        assert v.oszczędność == Decimal("100")

    def test_risk_level_to_max(self, small_pricing: Pricing):
        # Pomiń jeden LOW i jeden HIGH → wariant ma risk HIGH
        skip = [
            make_doc(numer="FV/L", risk_level="LOW"),
            make_doc(numer="FV/H", risk_level="HIGH"),
        ]
        v = _build_variant(skip, [], [], no_go_count=0, remaining_count=12, pricing=small_pricing)
        assert v is not None
        assert v.risk_level == "HIGH"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_te_same_dokumenty_te_same_akcje_dedup(self, small_pricing: Pricing):
        skip = [make_doc(numer="FV/A"), make_doc(numer="FV/B")]
        v1 = _build_variant(skip, [], [], 0, 12, small_pricing)
        v2 = _build_variant(skip, [], [], 0, 12, small_pricing)
        result = _deduplicate([v1, v2])
        assert len(result) == 1

    def test_rozne_dokumenty_te_same_savings_keep_oba(self, small_pricing: Pricing):
        """Plan: 'wariant A (pomiń #1) i B (pomiń #2) → keep oba (różne akcje!)'"""
        skip_a = [make_doc(numer="FV/A1"), make_doc(numer="FV/A2")]
        skip_b = [make_doc(numer="FV/B1"), make_doc(numer="FV/B2")]
        v1 = _build_variant(skip_a, [], [], 0, 12, small_pricing)
        v2 = _build_variant(skip_b, [], [], 0, 12, small_pricing)
        result = _deduplicate([v1, v2])
        assert len(result) == 2
        assert v1.oszczędność == v2.oszczędność  # te same savings
        # ale różne sygnatury
        assert _signature(v1.dokumenty_do_pomijania, [], []) != \
               _signature(v2.dokumenty_do_pomijania, [], [])


# ---------------------------------------------------------------------------
# generate_variants – scenariusze z planu
# ---------------------------------------------------------------------------

class TestGenerateVariants:
    def test_brak_optymalizacji_na_najnizszym_tierze(self, small_pricing: Pricing):
        docs = [make_doc(numer=f"FV/{i}") for i in range(5)]
        variants = generate_variants(docs, no_go_count=0, pricing=small_pricing)
        assert variants == []

    def test_threshold_crossing_skip(self, small_pricing: Pricing):
        # 12 dokumentów, tier 11-20 (200 zł), niższy tier 0-10 (100 zł)
        # Trzeba pomijać ≥ 2 dokumenty żeby zejść
        docs = [make_doc(numer=f"FV/{i}", wartość=str(10 + i)) for i in range(12)]
        variants = generate_variants(docs, no_go_count=0, pricing=small_pricing)
        assert len(variants) > 0
        # Każdy wariant osiąga niższy tier
        for v in variants:
            removed = (
                len(v.dokumenty_do_pomijania)
                + sum(len(g) - 1 for _, g in v.grupy_do_zbiorczenia)
                + len(v.dokumenty_do_przesunięcia)
            )
            assert 12 - removed <= 10, f"Wariant {v.id} nie zszedł do niższego tier'a"

    def test_zero_savings_nie_generowane(self, small_pricing: Pricing):
        docs = [make_doc(numer=f"FV/{i}") for i in range(12)]
        variants = generate_variants(docs, no_go_count=0, pricing=small_pricing)
        assert all(v.oszczędność > 0 for v in variants)

    def test_id_nadawane_1_do_N(self, small_pricing: Pricing):
        docs = [make_doc(numer=f"FV/{i}") for i in range(12)]
        variants = generate_variants(docs, no_go_count=0, pricing=small_pricing)
        ids = [v.id for v in variants]
        assert ids == list(range(1, len(variants) + 1))

    def test_sortowanie_po_oszczednosci_desc(self, small_pricing: Pricing):
        # 25 docs, tier 21-30 (300 zł); można zejść do 200 lub 100
        docs = [make_doc(numer=f"FV/{i}", wartość=str(10 + i)) for i in range(25)]
        variants = generate_variants(docs, no_go_count=0, pricing=small_pricing)
        savings = [v.oszczędność for v in variants]
        assert savings == sorted(savings, reverse=True)

    def test_max_variants_respektowany(self, small_pricing: Pricing):
        docs = [make_doc(numer=f"FV/{i}", nip=str(i % 3), wartość="10") for i in range(20)]
        variants = generate_variants(docs, no_go_count=0, pricing=small_pricing, max_variants=3)
        assert len(variants) <= 3

    def test_konsolidacja_dostawcy(self, small_pricing: Pricing):
        # 12 docs: 8 od jednego dostawcy + 4 od innych
        # Konsolidacja 8 → 1 daje redukcję o 7 → 12-7=5 docs → tier 100 → savings 100
        docs = [make_doc(numer=f"FV/STACJA/{i}", nip="STACJA_PALIW") for i in range(8)]
        docs += [make_doc(numer=f"FV/INNY/{i}", nip=str(100 + i)) for i in range(4)]
        variants = generate_variants(docs, no_go_count=0, pricing=small_pricing)
        # Powinien być wariant z konsolidacją STACJA_PALIW
        consol_variants = [v for v in variants if v.grupy_do_zbiorczenia]
        assert len(consol_variants) > 0
        stacja_consol = [
            v for v in consol_variants
            if any(nip == "STACJA_PALIW" for nip, _ in v.grupy_do_zbiorczenia)
        ]
        assert len(stacja_consol) > 0

    def test_shift_z_target_period(self, small_pricing: Pricing):
        docs = [make_doc(numer=f"FV/{i}", wartość="10") for i in range(12)]
        variants = generate_variants(
            docs, no_go_count=0, pricing=small_pricing, target_period="2025-12"
        )
        shift_variants = [v for v in variants if v.dokumenty_do_przesunięcia]
        assert len(shift_variants) > 0
        for v in shift_variants:
            for _doc, target in v.dokumenty_do_przesunięcia:
                assert target == "2025-12"

    def test_brak_target_period_brak_shift(self, small_pricing: Pricing):
        docs = [make_doc(numer=f"FV/{i}", wartość="10") for i in range(12)]
        variants = generate_variants(docs, no_go_count=0, pricing=small_pricing, target_period=None)
        assert all(not v.dokumenty_do_przesunięcia for v in variants)

    def test_kombinacja_skip_consolidate_shift(self, small_pricing: Pricing):
        # 25 docs (tier 300): grupa 5 docs od STACJA + reszta
        # Kombinacja skip + consolidate + shift powinna się pojawić
        docs = [make_doc(numer=f"FV/STACJA/{i}", nip="STACJA") for i in range(5)]
        docs += [make_doc(numer=f"FV/X/{i}", nip=str(100 + i), wartość="20") for i in range(20)]
        variants = generate_variants(
            docs, no_go_count=0, pricing=small_pricing, target_period="2025-12"
        )
        all_three = [
            v for v in variants
            if v.dokumenty_do_pomijania
            and v.grupy_do_zbiorczenia
            and v.dokumenty_do_przesunięcia
        ]
        assert len(all_three) >= 1

    def test_risk_max_w_wariancie(self, small_pricing: Pricing):
        # 12 docs: 11 LOW + 1 HIGH → jeśli wariant dotyka HIGH, risk_level=HIGH
        docs = [make_doc(numer=f"FV/L/{i}", risk_level="LOW") for i in range(11)]
        docs.append(make_doc(numer="FV/H", risk_level="HIGH", wartość="5"))  # mała wartość = w pierwszej kolejności do skip
        variants = generate_variants(docs, no_go_count=0, pricing=small_pricing)
        # Co najmniej jeden wariant powinien zawierać HIGH risk
        high_variants = [v for v in variants if v.risk_level == "HIGH"]
        low_variants = [v for v in variants if v.risk_level == "LOW"]
        # Strategia by_safety sortuje LOW first, więc HIGH dokument NIE powinien być w pierwszych skipach
        # ale by_value sortuje po wartości → HIGH (wartość=5) idzie pierwszy
        # więc oba typy wariantów powinny istnieć
        assert len(low_variants) > 0
        # Risk level musi być wartym dokumentów touchowanych
        for v in variants:
            touched_risks = {d.risk_level for d in v.dokumenty_do_pomijania}
            for _nip, group in v.grupy_do_zbiorczenia:
                touched_risks.update(d.risk_level for d in group)
            for d, _m in v.dokumenty_do_przesunięcia:
                touched_risks.add(d.risk_level)
            if "HIGH" in touched_risks:
                assert v.risk_level == "HIGH"

    def test_no_go_count_wplywa_na_kalkulacje(self, small_pricing: Pricing):
        # 5 remaining + 7 no_go = 12 total → tier 200; pomiń 2 z remaining → 10 → tier 100
        docs = [make_doc(numer=f"FV/{i}", wartość="10") for i in range(5)]
        variants = generate_variants(docs, no_go_count=7, pricing=small_pricing)
        assert len(variants) > 0
        # Każdy wariant ma skip ≥ 2
        assert all(
            (len(v.dokumenty_do_pomijania)
             + sum(len(g) - 1 for _, g in v.grupy_do_zbiorczenia)
             + len(v.dokumenty_do_przesunięcia)) >= 2
            for v in variants
        )

    def test_pusty_remaining(self, small_pricing: Pricing):
        assert generate_variants([], no_go_count=0, pricing=small_pricing) == []
        assert generate_variants([], no_go_count=12, pricing=small_pricing) == []

    def test_niezmiennik_savings_pasuje_do_pricing(self, small_pricing: Pricing):
        docs = [make_doc(numer=f"FV/{i}", wartość="10") for i in range(15)]
        variants = generate_variants(docs, no_go_count=0, pricing=small_pricing, target_period="2025-12")
        for v in variants:
            removed = (
                len(v.dokumenty_do_pomijania)
                + sum(len(g) - 1 for _, g in v.grupy_do_zbiorczenia)
                + len(v.dokumenty_do_przesunięcia)
            )
            expected_savings = small_pricing.price_for(15) - small_pricing.price_for(15 - removed)
            assert v.oszczędność == expected_savings


# ---------------------------------------------------------------------------
# Integracja z Fazą 1
# ---------------------------------------------------------------------------

class TestIntegrationFaza1:
    def test_pelny_pipeline(self):
        """Parser → Tax Advisor → Constraints → Optimizer."""
        import shutil
        from pathlib import Path

        from analyzer.constraints import classify
        from analyzer.parser import parse_jpk_fa
        from analyzer.rules import RuleEngine
        from analyzer.tax_advisor import assess_all

        # Wczytaj fixture i przygotuj engine
        xml = (Path(__file__).parent.parent / "fixtures" / "sample_jpk_fa.xml").read_bytes()
        docs = parse_jpk_fa(xml)
        assess_all(docs, forma="KPIR")

        tmp = Path("/tmp/test_optimizer_integration")
        tmp.mkdir(exist_ok=True)
        shutil.copy(
            Path(__file__).parent.parent / "data" / "rules_system.json",
            tmp / "rules_system.json",
        )
        engine = RuleEngine("TEST_KLIENT", data_dir=tmp)
        result = classify(docs, forma="KPIR", engine=engine)

        # Pricing dobrany do liczebności fixture'a (małe)
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
        # Smoke: pipeline kończy się bez wyjątków
        assert isinstance(variants, list)
        for v in variants:
            assert isinstance(v, Variant)
            assert v.oszczędność > 0
            assert v.id >= 1
            assert v.risk_level in {"LOW", "MED", "HIGH"}
