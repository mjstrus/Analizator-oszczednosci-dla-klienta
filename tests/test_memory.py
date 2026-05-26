"""Tests for analyzer/memory.py – Unit 9 (Memory)."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from analyzer.memory import (
    clear_decisions,
    load_decisions,
    record_decision,
    variant_to_decision,
)
from analyzer.models import Document, Variant
from analyzer.rules import RuleEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc(id_: str = "d1") -> Document:
    return Document(
        id=id_, numer=f"FV/{id_}", data=datetime(2024, 11, 15),
        nip_dostawcy="1234567890", wartość=Decimal("100"),
        typ="KP", typ_płatności="przelew", risk_level="LOW",
    )


def _variant(risk: str = "LOW", pomijanie=None, zbiorczenie=None, przesunięcia=None) -> Variant:
    return Variant(
        id=1,
        oszczędność=Decimal("180"),
        dokumenty_do_pomijania=pomijanie or [],
        grupy_do_zbiorczenia=zbiorczenie or [],
        dokumenty_do_przesunięcia=przesunięcia or [],
        risk_level=risk,
    )


def _engine(tmp_dir: str) -> RuleEngine:
    return RuleEngine(klient_id="TEST_CLIENT", data_dir=Path(tmp_dir))


# ---------------------------------------------------------------------------
# variant_to_decision
# ---------------------------------------------------------------------------

class TestVariantToDecision:
    def test_required_keys(self):
        d = variant_to_decision(_variant())
        assert "risk_level" in d
        assert "akcje" in d

    def test_akcje_keys(self):
        d = variant_to_decision(_variant())
        assert "pomijanie" in d["akcje"]
        assert "zbiorczy" in d["akcje"]
        assert "przesunięcie" in d["akcje"]

    def test_no_actions_all_false(self):
        d = variant_to_decision(_variant())
        assert d["akcje"] == {"pomijanie": False, "zbiorczy": False, "przesunięcie": False}

    def test_pomijanie_true(self):
        v = _variant(pomijanie=[_doc()])
        d = variant_to_decision(v)
        assert d["akcje"]["pomijanie"] is True
        assert d["akcje"]["zbiorczy"] is False
        assert d["akcje"]["przesunięcie"] is False

    def test_zbiorczenie_true(self):
        v = _variant(zbiorczenie=[("NIP", [_doc()])])
        d = variant_to_decision(v)
        assert d["akcje"]["zbiorczy"] is True

    def test_przesunięcia_true(self):
        v = _variant(przesunięcia=[(_doc(), "2024-12")])
        d = variant_to_decision(v)
        assert d["akcje"]["przesunięcie"] is True

    def test_risk_level_preserved(self):
        assert variant_to_decision(_variant(risk="HIGH"))["risk_level"] == "HIGH"
        assert variant_to_decision(_variant(risk="MED"))["risk_level"] == "MED"
        assert variant_to_decision(_variant(risk="LOW"))["risk_level"] == "LOW"

    def test_combined_actions(self):
        v = _variant(
            pomijanie=[_doc()],
            zbiorczenie=[("NIP", [_doc("z")])],
            przesunięcia=[(_doc("s"), "2024-12")],
        )
        d = variant_to_decision(v)
        assert all(d["akcje"].values())


# ---------------------------------------------------------------------------
# record_decision
# ---------------------------------------------------------------------------

class TestRecordDecision:
    def test_creates_file_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            assert not engine.client_rules_path.exists()
            record_decision(engine, _variant())
            assert engine.client_rules_path.exists()

    def test_decision_appended(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            record_decision(engine, _variant())
            data = json.loads(engine.client_rules_path.read_text(encoding="utf-8"))
            assert len(data["decisions"]) == 1

    def test_multiple_decisions_accumulate(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            record_decision(engine, _variant(risk="LOW"))
            record_decision(engine, _variant(risk="MED"))
            record_decision(engine, _variant(risk="HIGH"))
            data = json.loads(engine.client_rules_path.read_text(encoding="utf-8"))
            assert len(data["decisions"]) == 3

    def test_decision_has_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            record_decision(engine, _variant())
            data = json.loads(engine.client_rules_path.read_text(encoding="utf-8"))
            assert "timestamp" in data["decisions"][0]

    def test_decision_has_variant_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            v = _variant()
            v.id = 42
            record_decision(engine, v)
            data = json.loads(engine.client_rules_path.read_text(encoding="utf-8"))
            assert data["decisions"][0]["variant_id"] == 42

    def test_preserves_rules_section(self):
        """record_decision must not destroy existing rules."""
        from analyzer.rules import ActionRule
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            rule = ActionRule(
                id="test_rule", nazwa="Test", działanie="sugeruj_pomijanie",
                typ="client_preference",
            )
            engine.add_client_rule(rule)
            record_decision(engine, _variant())

            data = json.loads(engine.client_rules_path.read_text(encoding="utf-8"))
            assert any(r["id"] == "test_rule" for r in data["rules"])
            assert len(data["decisions"]) == 1

    def test_decision_risk_level_correct(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            record_decision(engine, _variant(risk="MED", pomijanie=[_doc()]))
            data = json.loads(engine.client_rules_path.read_text(encoding="utf-8"))
            dec = data["decisions"][0]
            assert dec["risk_level"] == "MED"
            assert dec["akcje"]["pomijanie"] is True

    def test_klient_id_in_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            record_decision(engine, _variant())
            data = json.loads(engine.client_rules_path.read_text(encoding="utf-8"))
            assert data["klient_id"] == "TEST_CLIENT"


# ---------------------------------------------------------------------------
# load_decisions
# ---------------------------------------------------------------------------

class TestLoadDecisions:
    def test_empty_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            assert load_decisions(engine) == []

    def test_returns_recorded_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            record_decision(engine, _variant(risk="LOW", pomijanie=[_doc()]))
            decisions = load_decisions(engine)
            assert len(decisions) == 1
            assert decisions[0]["risk_level"] == "LOW"

    def test_returns_all_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            for _ in range(5):
                record_decision(engine, _variant())
            assert len(load_decisions(engine)) == 5

    def test_decision_schema_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            record_decision(engine, _variant(pomijanie=[_doc()]))
            dec = load_decisions(engine)[0]
            assert "risk_level" in dec
            assert "akcje" in dec
            assert {"pomijanie", "zbiorczy", "przesunięcie"} == set(dec["akcje"].keys())


# ---------------------------------------------------------------------------
# clear_decisions
# ---------------------------------------------------------------------------

class TestClearDecisions:
    def test_clears_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            record_decision(engine, _variant())
            record_decision(engine, _variant())
            clear_decisions(engine)
            assert load_decisions(engine) == []

    def test_no_op_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            clear_decisions(engine)  # must not raise

    def test_preserves_rules_on_clear(self):
        from analyzer.rules import ActionRule
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            rule = ActionRule(
                id="keep_me", nazwa="Keep", działanie="sugeruj_pomijanie",
                typ="client_preference",
            )
            engine.add_client_rule(rule)
            record_decision(engine, _variant())
            clear_decisions(engine)

            data = json.loads(engine.client_rules_path.read_text(encoding="utf-8"))
            assert any(r["id"] == "keep_me" for r in data["rules"])
            assert data["decisions"] == []

    def test_decisions_empty_after_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            for _ in range(3):
                record_decision(engine, _variant())
            clear_decisions(engine)
            data = json.loads(engine.client_rules_path.read_text(encoding="utf-8"))
            assert data["decisions"] == []
