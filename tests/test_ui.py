"""Tests for UI helper functions – Unit 10."""
from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal

import pytest

from analyzer.models import Document, Variant
from ui.sidebar import validate_period
from ui.upload import _file_hash
from ui.variant_card import (
    _action_lines,
    _count_actions,
    format_compatibility,
    format_risk,
    format_savings,
    format_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc(id_: str = "d1", wartość: float = 100.0) -> Document:
    return Document(
        id=id_, numer=f"FV/{id_}", data=datetime(2024, 11, 15),
        nip_dostawcy="1234567890", wartość=Decimal(str(wartość)),
        typ="KP", typ_płatności="przelew", risk_level="LOW",
    )


def _variant(
    risk: str = "LOW",
    pomijanie=None,
    zbiorczenie=None,
    przesunięcia=None,
) -> Variant:
    return Variant(
        id=1,
        oszczędność=Decimal("180"),
        dokumenty_do_pomijania=pomijanie or [],
        grupy_do_zbiorczenia=zbiorczenie or [],
        dokumenty_do_przesunięcia=przesunięcia or [],
        risk_level=risk,
        compatibility_score=0.75,
        score=0.85,
    )


# ---------------------------------------------------------------------------
# validate_period
# ---------------------------------------------------------------------------

class TestValidatePeriod:
    def test_valid_period(self):
        assert validate_period("2024-11") is True

    def test_valid_january(self):
        assert validate_period("2025-01") is True

    def test_valid_december(self):
        assert validate_period("2026-12") is True

    def test_invalid_month_13(self):
        assert validate_period("2024-13") is False

    def test_invalid_month_0(self):
        assert validate_period("2024-00") is False

    def test_invalid_no_dash(self):
        assert validate_period("202411") is False

    def test_invalid_wrong_separator(self):
        assert validate_period("2024/11") is False

    def test_empty_string(self):
        assert validate_period("") is False

    def test_with_whitespace(self):
        assert validate_period(" 2024-11 ") is True

    def test_year_too_old(self):
        assert validate_period("1999-01") is False

    def test_year_too_future(self):
        assert validate_period("2101-01") is False


# ---------------------------------------------------------------------------
# _file_hash
# ---------------------------------------------------------------------------

class TestFileHash:
    def test_returns_string(self):
        assert isinstance(_file_hash(b"test"), str)

    def test_deterministic(self):
        assert _file_hash(b"abc") == _file_hash(b"abc")

    def test_different_for_different_bytes(self):
        assert _file_hash(b"abc") != _file_hash(b"xyz")

    def test_sha256_length(self):
        assert len(_file_hash(b"test")) == 64

    def test_matches_sha256(self):
        data = b"hello world"
        expected = hashlib.sha256(data).hexdigest()
        assert _file_hash(data) == expected


# ---------------------------------------------------------------------------
# format_risk
# ---------------------------------------------------------------------------

class TestFormatRisk:
    def test_low_contains_niskie(self):
        assert "Niskie" in format_risk("LOW")

    def test_med_contains_średnie(self):
        assert "Średnie" in format_risk("MED")

    def test_high_contains_wysokie(self):
        assert "Wysokie" in format_risk("HIGH")

    def test_low_is_green(self):
        assert "green" in format_risk("LOW")

    def test_high_is_red(self):
        assert "red" in format_risk("HIGH")

    def test_med_is_orange(self):
        assert "orange" in format_risk("MED")

    def test_unknown_level(self):
        result = format_risk("UNKNOWN")
        assert "UNKNOWN" in result


# ---------------------------------------------------------------------------
# format_savings
# ---------------------------------------------------------------------------

class TestFormatSavings:
    def test_basic(self):
        result = format_savings(Decimal("180.00"))
        assert "180" in result
        assert "zł" in result

    def test_zero(self):
        assert "0" in format_savings(Decimal("0"))

    def test_large_amount(self):
        result = format_savings(Decimal("1500.00"))
        assert "1" in result and "500" in result and "zł" in result

    def test_returns_string(self):
        assert isinstance(format_savings(Decimal("100")), str)


# ---------------------------------------------------------------------------
# format_score
# ---------------------------------------------------------------------------

class TestFormatScore:
    def test_three_decimals(self):
        assert format_score(0.87654) == "0.877"

    def test_zero(self):
        assert format_score(0.0) == "0.000"

    def test_one(self):
        assert format_score(1.0) == "1.000"


# ---------------------------------------------------------------------------
# format_compatibility
# ---------------------------------------------------------------------------

class TestFormatCompatibility:
    def test_percent_sign(self):
        assert "%" in format_compatibility(0.75)

    def test_value_75(self):
        assert "75" in format_compatibility(0.75)

    def test_value_100(self):
        assert "100" in format_compatibility(1.0)

    def test_value_0(self):
        assert "0" in format_compatibility(0.0)

    def test_half(self):
        assert "50" in format_compatibility(0.5)


# ---------------------------------------------------------------------------
# _action_lines
# ---------------------------------------------------------------------------

class TestActionLines:
    def test_empty_variant(self):
        assert _action_lines(_variant()) == []

    def test_pomijanie_in_lines(self):
        v = _variant(pomijanie=[_doc("a"), _doc("b")])
        lines = _action_lines(v)
        assert any("Pomiń" in l and "2" in l for l in lines)

    def test_zbiorczenie_in_lines(self):
        v = _variant(zbiorczenie=[("NIP_A", [_doc("z1"), _doc("z2"), _doc("z3")])])
        lines = _action_lines(v)
        assert any("Zbiorczy" in l and "3" in l for l in lines)

    def test_przesunięcia_in_lines(self):
        v = _variant(przesunięcia=[(_doc("s"), "2024-12")])
        lines = _action_lines(v)
        assert any("Przesuń" in l and "2024-12" in l for l in lines)

    def test_all_actions(self):
        v = _variant(
            pomijanie=[_doc()],
            zbiorczenie=[("NIP", [_doc("z")])],
            przesunięcia=[(_doc("s"), "2024-12")],
        )
        assert len(_action_lines(v)) == 3


# ---------------------------------------------------------------------------
# _count_actions
# ---------------------------------------------------------------------------

class TestCountActions:
    def test_no_actions(self):
        assert _count_actions(_variant()) == "–"

    def test_counts_pomijanie(self):
        v = _variant(pomijanie=[_doc("a"), _doc("b"), _doc("c")])
        assert _count_actions(v) == "3"

    def test_counts_zbiorczenie_docs(self):
        v = _variant(zbiorczenie=[("NIP", [_doc("z1"), _doc("z2")])])
        assert _count_actions(v) == "2"

    def test_counts_combined(self):
        v = _variant(
            pomijanie=[_doc("p")],
            zbiorczenie=[("NIP", [_doc("z1"), _doc("z2")])],
            przesunięcia=[(_doc("s"), "2024-12")],
        )
        assert _count_actions(v) == "4"


# ---------------------------------------------------------------------------
# app.py pipeline (no Streamlit rendering)
# ---------------------------------------------------------------------------

class TestRunAnalysisPipeline:
    """Smoke tests for the run_analysis pipeline without Streamlit."""

    def test_pipeline_with_sample_fixture(self, tmp_path):
        from pathlib import Path
        from app import run_analysis

        xml_bytes = (
            Path(__file__).parent.parent / "fixtures" / "sample_jpk_fa.xml"
        ).read_bytes()

        config = {"klient_id": "TEST", "forma": "KPIR", "period": "2024-11", "top_n": 5}
        variants, no_go, engine = run_analysis(xml_bytes, config, data_dir=tmp_path)

        assert isinstance(variants, list)
        assert isinstance(no_go, list)
        assert engine is not None

    def test_pipeline_empty_xml_returns_empty(self, tmp_path):
        from app import run_analysis

        minimal_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<JPK xmlns="http://crd.gov.pl/wzor/2021/11/29/11089/"></JPK>"""

        config = {"klient_id": "EMPTY", "forma": "KPIR", "period": "2024-11", "top_n": 5}
        variants, no_go, engine = run_analysis(minimal_xml, config, data_dir=tmp_path)

        assert variants == []
        assert no_go == []

    def test_config_key_changes_on_klient_id(self):
        from app import _config_key

        cfg1 = {"klient_id": "A", "forma": "KPIR", "period": "2024-11", "top_n": 5}
        cfg2 = {"klient_id": "B", "forma": "KPIR", "period": "2024-11", "top_n": 5}
        assert _config_key(cfg1) != _config_key(cfg2)

    def test_config_key_changes_on_forma(self):
        from app import _config_key

        cfg1 = {"klient_id": "A", "forma": "KPIR", "period": "2024-11", "top_n": 5}
        cfg2 = {"klient_id": "A", "forma": "KSH", "period": "2024-11", "top_n": 5}
        assert _config_key(cfg1) != _config_key(cfg2)
