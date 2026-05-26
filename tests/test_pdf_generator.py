"""Tests for analyzer/pdf_generator.py – Unit 8."""
from __future__ import annotations

import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from analyzer.models import Document, Variant
from analyzer.pdf_generator import (
    _action_summary,
    _fmt_pln,
    _register_fonts,
    generate_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc(id_: str, wartość: float = 200.0, typ: str = "KP") -> Document:
    return Document(
        id=id_, numer=f"FV/2024/{id_}", data=datetime(2024, 11, 15),
        nip_dostawcy="1234567890", wartość=Decimal(str(wartość)),
        typ=typ, typ_płatności="przelew", risk_level="LOW",
    )


def _variant(
    id_: int = 1,
    savings: float = 180.0,
    risk: str = "LOW",
    pomijanie=None,
    zbiorczenie=None,
    przesunięcia=None,
    impact: str | None = None,
) -> Variant:
    v = Variant(
        id=id_,
        oszczędność=Decimal(str(savings)),
        dokumenty_do_pomijania=pomijanie or [],
        grupy_do_zbiorczenia=zbiorczenie or [],
        dokumenty_do_przesunięcia=przesunięcia or [],
        risk_level=risk,
        compatibility_score=0.75,
        score=0.85,
        impact_message=impact,
    )
    return v


def _generate(variants, **kwargs) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.pdf"
        result = generate_report(variants, klient_id="TEST_001", output_path=out, **kwargs)
        # Read bytes before dir is deleted
        data = result.read_bytes()
    return data  # return bytes for assertion


# ---------------------------------------------------------------------------
# _fmt_pln
# ---------------------------------------------------------------------------

class TestFmtPln:
    def test_basic(self):
        assert _fmt_pln(Decimal("180.00")) == "180.00 zł"

    def test_thousands(self):
        result = _fmt_pln(Decimal("1500.00"))
        # narrow no-break space (U+202F) is the correct Polish thousands separator
        assert "1 500.00 zł" == result

    def test_zero(self):
        assert "0.00 zł" in _fmt_pln(Decimal("0"))


# ---------------------------------------------------------------------------
# _action_summary
# ---------------------------------------------------------------------------

class TestActionSummary:
    def test_no_actions(self):
        v = _variant()
        assert _action_summary(v) == "–"

    def test_pomijanie_only(self):
        v = _variant(pomijanie=[_doc("a"), _doc("b")])
        assert "Pomiń 2" in _action_summary(v)

    def test_zbiorczenie(self):
        v = _variant(zbiorczenie=[("nip1", [_doc("x"), _doc("y")])])
        assert "Zbiorczy 2" in _action_summary(v)

    def test_przesunięcia(self):
        v = _variant(przesunięcia=[(_doc("p"), "2024-12")])
        assert "Przesuń 1" in _action_summary(v)

    def test_combined(self):
        v = _variant(
            pomijanie=[_doc("a")],
            przesunięcia=[(_doc("b"), "2024-12")],
        )
        summary = _action_summary(v)
        assert "Pomiń 1" in summary
        assert "Przesuń 1" in summary


# ---------------------------------------------------------------------------
# _register_fonts
# ---------------------------------------------------------------------------

class TestRegisterFonts:
    def test_returns_two_strings(self):
        font, bold = _register_fonts()
        assert isinstance(font, str) and len(font) > 0
        assert isinstance(bold, str) and len(bold) > 0

    def test_different_names(self):
        font, bold = _register_fonts()
        assert font != bold


# ---------------------------------------------------------------------------
# generate_report – file creation
# ---------------------------------------------------------------------------

class TestGenerateReport:
    def _run(self, variants, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.pdf"
            result = generate_report(
                variants, klient_id="KLIENT_XYZ", output_path=out, **kwargs
            )
            assert result == out
            data = out.read_bytes()
        return data

    def test_creates_valid_pdf(self):
        v = _variant(pomijanie=[_doc("d1"), _doc("d2")])
        data = self._run([v])
        assert data[:4] == b"%PDF"

    def test_non_trivial_size(self):
        v = _variant(pomijanie=[_doc("d1")])
        data = self._run([v])
        assert len(data) > 2000

    def test_empty_variants_creates_pdf(self):
        data = self._run([])
        assert data[:4] == b"%PDF"

    def test_returns_path_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.pdf"
            result = generate_report([], klient_id="K1", output_path=out)
            assert isinstance(result, Path)
            assert result.exists()

    def test_accepts_string_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "report.pdf")
            result = generate_report([], klient_id="K1", output_path=out)
            assert Path(result).exists()

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "nested" / "dir" / "report.pdf"
            generate_report([], klient_id="K1", output_path=out)
            assert out.exists()

    def test_with_period(self):
        v = _variant(savings=100.0)
        data = self._run([v], period="2024-11")
        assert data[:4] == b"%PDF"

    def test_custom_title(self):
        data = self._run([], title="Mój Raport")
        assert data[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# generate_report – content correctness (smoke)
# ---------------------------------------------------------------------------

class TestReportContent:
    """Smoke tests: verify the builder doesn't crash on various inputs."""

    def _smoke(self, variants, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.pdf"
            generate_report(variants, klient_id="K1", output_path=out, **kwargs)
            return out.stat().st_size

    def test_all_action_types(self):
        v = _variant(
            id_=1, savings=450.0, risk="LOW",
            pomijanie=[_doc("p1"), _doc("p2")],
            zbiorczenie=[("NIP_ABC", [_doc("z1"), _doc("z2"), _doc("z3")])],
            przesunięcia=[(_doc("s1"), "2024-12"), (_doc("s2"), "2024-12")],
            impact="Grudzień będzie miał 153 dokumentów (+2)",
        )
        size = self._smoke([v])
        assert size > 3000

    def test_high_risk_variant(self):
        v = _variant(id_=1, savings=300.0, risk="HIGH", pomijanie=[_doc("h1")])
        size = self._smoke([v])
        assert size > 2000

    def test_med_risk_variant(self):
        v = _variant(id_=1, savings=180.0, risk="MED", pomijanie=[_doc("m1")])
        assert self._smoke([v]) > 2000

    def test_multiple_variants(self):
        variants = [
            _variant(id_=i, savings=float(500 - i * 50), risk="LOW")
            for i in range(1, 6)
        ]
        size = self._smoke(variants)
        assert size > 4000

    def test_variant_no_actions(self):
        v = _variant(id_=1, savings=0.0)
        assert self._smoke([v]) > 2000

    def test_variant_with_impact_message(self):
        v = _variant(
            id_=1, savings=200.0,
            przesunięcia=[(_doc("x"), "2025-01")],
            impact="Styczeń będzie miał 53 dokumentów (+5) – zmiana taryfy +80 zł",
        )
        assert self._smoke([v]) > 2000

    def test_zbiorczenie_multiple_suppliers(self):
        v = _variant(
            id_=1, savings=260.0,
            zbiorczenie=[
                ("NIP_A", [_doc("a1"), _doc("a2")]),
                ("NIP_B", [_doc("b1"), _doc("b2"), _doc("b3")]),
            ],
        )
        assert self._smoke([v]) > 2000
