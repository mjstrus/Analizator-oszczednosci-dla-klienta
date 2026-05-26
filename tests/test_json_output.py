"""Tests for analyzer/json_output.py – Unit 9 (JSON Output)."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from analyzer.json_output import (
    document_to_dict,
    load_analysis,
    save_analysis,
    serialize_analysis,
    variant_to_dict,
)
from analyzer.models import Document, Variant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc(id_: str = "d1", wartość: float = 150.0) -> Document:
    return Document(
        id=id_, numer=f"FV/{id_}", data=datetime(2024, 11, 15, 10, 30),
        nip_dostawcy="1234567890", wartość=Decimal(str(wartość)),
        typ="KP", typ_płatności="przelew", risk_level="LOW",
    )


def _variant(
    id_: int = 1,
    savings: float = 180.0,
    risk: str = "LOW",
    pomijanie=None,
    zbiorczenie=None,
    przesunięcia=None,
) -> Variant:
    return Variant(
        id=id_,
        oszczędność=Decimal(str(savings)),
        dokumenty_do_pomijania=pomijanie or [],
        grupy_do_zbiorczenia=zbiorczenie or [],
        dokumenty_do_przesunięcia=przesunięcia or [],
        risk_level=risk,
        compatibility_score=0.75,
        score=0.85,
        impact_message="Test impact",
    )


# ---------------------------------------------------------------------------
# document_to_dict
# ---------------------------------------------------------------------------

class TestDocumentToDict:
    def test_required_fields_present(self):
        d = document_to_dict(_doc())
        for key in ("id", "numer", "data", "nip_dostawcy", "wartość", "typ", "typ_płatności"):
            assert key in d

    def test_data_is_iso_string(self):
        d = document_to_dict(_doc())
        assert d["data"] == "2024-11-15T10:30:00"

    def test_wartość_is_string(self):
        d = document_to_dict(_doc(wartość=99.99))
        assert isinstance(d["wartość"], str)
        assert "99.99" in d["wartość"]

    def test_risk_level_preserved(self):
        doc = _doc()
        doc.risk_level = "HIGH"
        assert document_to_dict(doc)["risk_level"] == "HIGH"

    def test_status_preserved(self):
        doc = _doc()
        doc.status = "processed"
        assert document_to_dict(doc)["status"] == "processed"


# ---------------------------------------------------------------------------
# variant_to_dict
# ---------------------------------------------------------------------------

class TestVariantToDict:
    def test_required_fields_present(self):
        v = variant_to_dict(_variant())
        for key in ("id", "oszczędność", "risk_level", "compatibility_score", "score"):
            assert key in v

    def test_oszczędność_is_string(self):
        v = variant_to_dict(_variant(savings=180.0))
        assert isinstance(v["oszczędność"], str)

    def test_empty_lists_serialized(self):
        v = variant_to_dict(_variant())
        assert v["dokumenty_do_pomijania"] == []
        assert v["grupy_do_zbiorczenia"] == []
        assert v["dokumenty_do_przesunięcia"] == []

    def test_pomijanie_list(self):
        v = variant_to_dict(_variant(pomijanie=[_doc("p1"), _doc("p2")]))
        assert len(v["dokumenty_do_pomijania"]) == 2
        assert v["dokumenty_do_pomijania"][0]["id"] == "p1"

    def test_zbiorczenie_structure(self):
        v = variant_to_dict(_variant(zbiorczenie=[("NIP_A", [_doc("z1"), _doc("z2")])]))
        groups = v["grupy_do_zbiorczenia"]
        assert len(groups) == 1
        assert groups[0]["dostawca"] == "NIP_A"
        assert len(groups[0]["dokumenty"]) == 2

    def test_przesunięcia_structure(self):
        v = variant_to_dict(_variant(przesunięcia=[(_doc("s1"), "2024-12")]))
        shifts = v["dokumenty_do_przesunięcia"]
        assert len(shifts) == 1
        assert shifts[0]["target_month"] == "2024-12"
        assert shifts[0]["dokument"]["id"] == "s1"

    def test_impact_message_preserved(self):
        v = _variant()
        v.impact_message = "Grudzień będzie miał 153 dokumentów (+3)"
        d = variant_to_dict(v)
        assert d["impact_message"] == "Grudzień będzie miał 153 dokumentów (+3)"

    def test_impact_message_none(self):
        v = _variant()
        v.impact_message = None
        d = variant_to_dict(v)
        assert d["impact_message"] is None

    def test_scores_rounded(self):
        v = _variant()
        v.compatibility_score = 0.333333
        v.score = 0.666666
        d = variant_to_dict(v)
        assert d["compatibility_score"] == 0.3333
        assert d["score"] == 0.6667


# ---------------------------------------------------------------------------
# serialize_analysis
# ---------------------------------------------------------------------------

class TestSerializeAnalysis:
    def test_top_level_keys(self):
        data = serialize_analysis([], klient_id="K1")
        for key in ("klient_id", "period", "generated_at", "summary", "variants", "no_go"):
            assert key in data

    def test_klient_id_set(self):
        data = serialize_analysis([], klient_id="FIRMA_XYZ")
        assert data["klient_id"] == "FIRMA_XYZ"

    def test_period_set(self):
        data = serialize_analysis([], klient_id="K1", period="2024-11")
        assert data["period"] == "2024-11"

    def test_summary_empty_variants(self):
        data = serialize_analysis([], klient_id="K1")
        assert data["summary"]["total_variants"] == 0
        assert "best_savings" not in data["summary"]

    def test_summary_with_variants(self):
        v = _variant(id_=1, savings=300.0, risk="LOW")
        v.score = 0.9
        data = serialize_analysis([v], klient_id="K1")
        s = data["summary"]
        assert s["total_variants"] == 1
        assert s["best_savings"] == "300.0"
        assert s["best_risk_level"] == "LOW"
        assert s["best_score"] == 0.9

    def test_no_go_serialized(self):
        data = serialize_analysis([], klient_id="K1", no_go=[_doc("ng1")])
        assert len(data["no_go"]) == 1
        assert data["no_go"][0]["id"] == "ng1"

    def test_no_go_count_in_summary(self):
        data = serialize_analysis([], klient_id="K1", no_go=[_doc("x"), _doc("y")])
        assert data["summary"]["no_go_count"] == 2

    def test_multiple_variants(self):
        variants = [_variant(id_=i, savings=float(300 - i * 50)) for i in range(1, 4)]
        data = serialize_analysis(variants, klient_id="K1")
        assert len(data["variants"]) == 3

    def test_json_serializable(self):
        v = _variant(pomijanie=[_doc()], zbiorczenie=[("NIP", [_doc("z")])],
                     przesunięcia=[(_doc("s"), "2024-12")])
        data = serialize_analysis([v], klient_id="K1", no_go=[_doc("n")])
        # Should not raise
        json.dumps(data, ensure_ascii=False)


# ---------------------------------------------------------------------------
# save_analysis / load_analysis
# ---------------------------------------------------------------------------

class TestSaveLoadAnalysis:
    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "analysis.json"
            save_analysis([], klient_id="K1", output_path=out)
            assert out.exists()

    def test_save_returns_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.json"
            result = save_analysis([], klient_id="K1", output_path=out)
            assert result == out

    def test_save_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "nested" / "dir" / "analysis.json"
            save_analysis([], klient_id="K1", output_path=out)
            assert out.exists()

    def test_save_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.json"
            save_analysis([_variant()], klient_id="K1", output_path=out)
            data = json.loads(out.read_text(encoding="utf-8"))
            assert data["klient_id"] == "K1"

    def test_roundtrip_klient_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.json"
            save_analysis([], klient_id="ROUNDTRIP_ID", output_path=out)
            loaded = load_analysis(out)
            assert loaded["klient_id"] == "ROUNDTRIP_ID"

    def test_roundtrip_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.json"
            save_analysis([], klient_id="K1", output_path=out, period="2024-11")
            loaded = load_analysis(out)
            assert loaded["period"] == "2024-11"

    def test_roundtrip_variants(self):
        v = _variant(id_=3, savings=250.0, pomijanie=[_doc("d1")])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.json"
            save_analysis([v], klient_id="K1", output_path=out)
            loaded = load_analysis(out)
            assert len(loaded["variants"]) == 1
            assert loaded["variants"][0]["id"] == 3

    def test_roundtrip_no_go(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.json"
            save_analysis([], klient_id="K1", output_path=out, no_go=[_doc("ng1"), _doc("ng2")])
            loaded = load_analysis(out)
            assert len(loaded["no_go"]) == 2

    def test_utf8_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.json"
            save_analysis([], klient_id="Klient_Ząbkowski", output_path=out)
            raw = out.read_text(encoding="utf-8")
            assert "Klient_Ząbkowski" in raw

    def test_accepts_string_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "a.json")
            result = save_analysis([], klient_id="K1", output_path=out)
            assert Path(result).exists()
