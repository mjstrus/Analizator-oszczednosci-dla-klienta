"""Tests for analyzer/impact_prognozer.py – Unit 7."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from analyzer.impact_prognozer import prognosticate_impact, _month_label
from analyzer.models import Document, Variant
from analyzer.optimizer import Pricing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc(id_: str, wartość: float = 100.0) -> Document:
    return Document(
        id=id_, numer=f"FV/{id_}", data=datetime(2024, 11, 15),
        nip_dostawcy="1234567890", wartość=Decimal(str(wartość)),
        typ="KP", typ_płatności="przelew", risk_level="LOW",
    )


def _variant(shifts: list) -> Variant:
    return Variant(
        id=1,
        oszczędność=Decimal("0"),
        dokumenty_do_pomijania=[],
        grupy_do_zbiorczenia=[],
        dokumenty_do_przesunięcia=shifts,
        risk_level="LOW",
    )


# ---------------------------------------------------------------------------
# _month_label
# ---------------------------------------------------------------------------

class TestMonthLabel:
    def test_december(self):
        assert _month_label("2024-12") == "Grudzień"

    def test_january(self):
        assert _month_label("2025-01") == "Styczeń"

    def test_unknown_format(self):
        assert _month_label("2024") == "2024"

    def test_all_months(self):
        expected = [
            "Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
            "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień",
        ]
        for i, name in enumerate(expected, 1):
            assert _month_label(f"2024-{i:02d}") == name


# ---------------------------------------------------------------------------
# No shifts
# ---------------------------------------------------------------------------

class TestNoShifts:
    def test_returns_zero(self):
        v = _variant([])
        score = prognosticate_impact(v)
        assert score == 0.0

    def test_impact_message_is_none(self):
        v = _variant([])
        prognosticate_impact(v)
        assert v.impact_message is None


# ---------------------------------------------------------------------------
# Shift within same tier (no tier change)
# ---------------------------------------------------------------------------

class TestShiftNoTierChange:
    def test_december_150_plus_3(self):
        """Shift 3 docs to December which already has 150 → 153 (still 101-200 tier)."""
        docs = [_doc(f"d{i}") for i in range(3)]
        shifts = [(d, "2024-12") for d in docs]
        v = _variant(shifts)

        score = prognosticate_impact(v, docs_per_month={"2024-12": 150})

        assert score == 0.0
        assert v.impact_message is not None
        assert "Grudzień" in v.impact_message
        assert "153" in v.impact_message
        assert "+3" in v.impact_message

    def test_message_no_tier_warning(self):
        docs = [_doc("x1")]
        v = _variant([(docs[0], "2024-12")])
        prognosticate_impact(v, docs_per_month={"2024-12": 150})
        assert "zmiana taryfy" not in v.impact_message

    def test_unknown_month_defaults_to_zero(self):
        v = _variant([(_doc("a"), "2025-03")])
        score = prognosticate_impact(v, docs_per_month={})
        # 0 + 1 = 1 doc, still in lowest tier
        assert score == 0.0
        assert "1" in v.impact_message
        assert "+1" in v.impact_message


# ---------------------------------------------------------------------------
# Shift that causes tier change
# ---------------------------------------------------------------------------

class TestShiftTierChange:
    def test_tier_change_score_positive(self):
        """48 docs in next month + 5 shifted = 53 → crosses 50→51 boundary."""
        docs = [_doc(f"t{i}") for i in range(5)]
        shifts = [(d, "2025-01") for d in docs]
        v = _variant(shifts)

        score = prognosticate_impact(v, docs_per_month={"2025-01": 48})

        assert score > 0.0

    def test_tier_change_message_content(self):
        docs = [_doc(f"t{i}") for i in range(5)]
        shifts = [(d, "2025-01") for d in docs]
        v = _variant(shifts)

        prognosticate_impact(v, docs_per_month={"2025-01": 48})

        assert "zmiana taryfy" in v.impact_message
        assert "Styczeń" in v.impact_message
        assert "53" in v.impact_message
        assert "+5" in v.impact_message

    def test_tier_change_shows_price_diff(self):
        """Tier 0-50 (100zł) → 51-100 (180zł) = +80 zł."""
        docs = [_doc(f"t{i}") for i in range(5)]
        v = _variant([(d, "2025-01") for d in docs])

        prognosticate_impact(v, docs_per_month={"2025-01": 48})

        assert "+80 zł" in v.impact_message

    def test_score_capped_at_1(self):
        """Multiple tier-crossing shifts should not exceed impact_score=1.0."""
        pricing = Pricing.default()
        docs = [_doc(f"x{i}") for i in range(60)]
        shifts = [(d, "2025-06") for d in docs[:30]] + [(d, "2025-07") for d in docs[30:]]
        v = _variant(shifts)

        score = prognosticate_impact(
            v,
            docs_per_month={"2025-06": 45, "2025-07": 45},
            pricing=pricing,
        )

        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Multiple target months
# ---------------------------------------------------------------------------

class TestMultipleMonths:
    def test_two_months_in_message(self):
        d1, d2 = _doc("m1"), _doc("m2")
        v = _variant([(d1, "2025-01"), (d2, "2025-02")])
        prognosticate_impact(v, docs_per_month={"2025-01": 10, "2025-02": 20})

        assert "Styczeń" in v.impact_message
        assert "Luty" in v.impact_message

    def test_months_sorted_in_message(self):
        d1, d2 = _doc("s1"), _doc("s2")
        # Pass in reverse order to confirm sorting
        v = _variant([(d2, "2025-03"), (d1, "2025-01")])
        prognosticate_impact(v)

        idx_jan = v.impact_message.index("Styczeń")
        idx_mar = v.impact_message.index("Marzec")
        assert idx_jan < idx_mar

    def test_combined_impact_two_tier_changes(self):
        """Two separate months both cross tier boundary."""
        docs = [_doc(f"c{i}") for i in range(10)]
        shifts = [(d, "2025-01") for d in docs[:5]] + [(d, "2025-02") for d in docs[5:]]
        v = _variant(shifts)

        score = prognosticate_impact(
            v,
            docs_per_month={"2025-01": 48, "2025-02": 48},
        )

        assert score > 0.0


# ---------------------------------------------------------------------------
# Custom pricing
# ---------------------------------------------------------------------------

class TestCustomPricing:
    def test_custom_pricing_used(self):
        """Custom single-tier pricing means no tier changes are possible."""
        from analyzer.optimizer import PriceTier
        flat = Pricing(tiers=[PriceTier(0, 9999, Decimal("200"))])
        docs = [_doc(f"f{i}") for i in range(100)]
        v = _variant([(d, "2025-05") for d in docs])

        score = prognosticate_impact(v, docs_per_month={"2025-05": 0}, pricing=flat)

        assert score == 0.0
        assert "zmiana taryfy" not in v.impact_message


# ---------------------------------------------------------------------------
# Idempotency – calling twice overwrites impact_message
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_second_call_overwrites(self):
        d = _doc("idem")
        v = _variant([(d, "2024-12")])

        prognosticate_impact(v, docs_per_month={"2024-12": 150})
        first = v.impact_message

        prognosticate_impact(v, docs_per_month={"2024-12": 10})
        second = v.impact_message

        assert first != second
        assert second is not None
