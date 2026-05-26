from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from analyzer.models import Document
from analyzer.rules import ActionRule, RuleEngine


def make_doc(
    typ: str = "KP",
    wartość: str = "100",
    typ_płatności: str = "przelew",
    risk_level: str = None,
    numer: str = "FV/T/001",
) -> Document:
    return Document(
        id=f"id-{numer}",
        numer=numer,
        data=datetime(2025, 11, 1),
        nip_dostawcy="1234567890",
        wartość=Decimal(wartość),
        typ=typ,
        typ_płatności=typ_płatności,
        risk_level=risk_level,
    )


@pytest.fixture
def empty_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def sys_rules_dir(tmp_path: Path) -> Path:
    """Katalog z prostymi system action_rules do testów."""
    (tmp_path / "rules_system.json").write_text(
        json.dumps({
            "action_rules": [
                {
                    "id": "sys_small",
                    "nazwa": "Małe KPIR",
                    "działanie": "sugeruj_pomijanie",
                    "forma": "KPIR",
                    "wartość_max": 50,
                    "priorytet": 8,
                },
                {
                    "id": "sys_high",
                    "nazwa": "HIGH risk no-go",
                    "działanie": "nie_można_ruszać",
                    "risk_level": "HIGH",
                    "priorytet": 10,
                },
            ]
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class TestLoading:
    def test_brak_plikow_pusty_engine(self, empty_dir: Path):
        engine = RuleEngine("XYZ", data_dir=empty_dir)
        assert engine.system_rules == []
        assert engine.client_rules == []

    def test_laduje_system_action_rules(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        assert len(engine.system_rules) == 2
        assert {r.id for r in engine.system_rules} == {"sys_small", "sys_high"}

    def test_system_rules_decimal_parsing(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        small = next(r for r in engine.system_rules if r.id == "sys_small")
        assert small.wartość_max == Decimal("50")

    def test_uszkodzony_json_zwraca_puste(self, empty_dir: Path):
        (empty_dir / "rules_system.json").write_text("{not valid", encoding="utf-8")
        engine = RuleEngine("XYZ", data_dir=empty_dir)
        assert engine.system_rules == []

    def test_invalid_działanie_skipped(self, empty_dir: Path):
        (empty_dir / "rules_system.json").write_text(
            json.dumps({"action_rules": [
                {"id": "ok", "nazwa": "ok", "działanie": "sugeruj_pomijanie"},
                {"id": "bad", "nazwa": "bad", "działanie": "INVALID_ACTION"},
            ]}, ensure_ascii=False),
            encoding="utf-8",
        )
        engine = RuleEngine("XYZ", data_dir=empty_dir)
        assert len(engine.system_rules) == 1
        assert engine.system_rules[0].id == "ok"

    def test_invalid_risk_level_skipped(self, empty_dir: Path):
        (empty_dir / "rules_system.json").write_text(
            json.dumps({"action_rules": [
                {"id": "bad_risk", "nazwa": "x", "działanie": "sugeruj_pomijanie",
                 "risk_level": "EXTREME"},
            ]}, ensure_ascii=False),
            encoding="utf-8",
        )
        engine = RuleEngine("XYZ", data_dir=empty_dir)
        assert engine.system_rules == []


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

class TestQuery:
    def test_query_zwraca_pasujaca_regule(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        doc = make_doc(typ="KP", wartość="30")
        matches = engine.query(doc, forma="KPIR")
        assert len(matches) == 1
        assert matches[0].id == "sys_small"
        assert matches[0].działanie == "sugeruj_pomijanie"

    def test_query_high_risk_nogo(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        doc = make_doc(risk_level="HIGH")
        matches = engine.query(doc, forma="KSH")
        assert any(r.id == "sys_high" for r in matches)

    def test_query_one_zwraca_najwyzszy_priorytet(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        # KP, 20 zł, HIGH risk – pasują obie reguły; sys_high (prio 10) > sys_small (prio 8)
        doc = make_doc(typ="KP", wartość="20", risk_level="HIGH")
        rule = engine.query_one(doc, forma="KPIR")
        assert rule is not None
        assert rule.id == "sys_high"

    def test_query_brak_dopasowania(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        doc = make_doc(typ="KP", wartość="5000", risk_level="LOW")
        assert engine.query(doc, forma="KPIR") == []
        assert engine.query_one(doc, forma="KPIR") is None

    def test_query_zwraca_zero_dla_pustego_engine(self, empty_dir: Path):
        engine = RuleEngine("XYZ", data_dir=empty_dir)
        doc = make_doc()
        assert engine.query(doc, forma="KPIR") == []
        assert engine.query_one(doc, forma="KPIR") is None


# ---------------------------------------------------------------------------
# Add client rule + persistence
# ---------------------------------------------------------------------------

class TestAddClientRule:
    def test_add_persistuje_do_pliku(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        rule = ActionRule(
            id="client_001",
            nazwa="Klient: pomijaj małe przelewy",
            działanie="sugeruj_pomijanie",
            forma="KPIR",
            typ_płatności="przelew",
            wartość_max=Decimal("100"),
            priorytet=5,
        )
        engine.add_client_rule(rule)

        path = sys_rules_dir / "rules_klient_XYZ.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["klient_id"] == "XYZ"
        assert len(data["rules"]) == 1
        assert data["rules"][0]["id"] == "client_001"
        assert data["rules"][0]["typ"] == "client_preference"
        assert data["rules"][0]["wartość_max"] == "100"  # Decimal → str

    def test_add_ustawia_metadata_klienta(self, sys_rules_dir: Path):
        engine = RuleEngine("ABC", data_dir=sys_rules_dir)
        rule = ActionRule(id="c1", nazwa="test", działanie="sugeruj_zbiorczy")
        engine.add_client_rule(rule)
        added = engine.client_rules[0]
        assert added.typ == "client_preference"
        assert added.klient_id == "ABC"
        assert added.data_utworzenia is not None
        # Powinien być valid ISO datetime
        datetime.fromisoformat(added.data_utworzenia)

    def test_dodanie_tego_samego_id_zastepuje(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        engine.add_client_rule(
            ActionRule(id="x", nazwa="v1", działanie="sugeruj_pomijanie")
        )
        engine.add_client_rule(
            ActionRule(id="x", nazwa="v2", działanie="sugeruj_zbiorczy")
        )
        assert len(engine.client_rules) == 1
        assert engine.client_rules[0].nazwa == "v2"
        assert engine.client_rules[0].działanie == "sugeruj_zbiorczy"

    def test_reload_widzi_persistowane_reguly(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        engine.add_client_rule(
            ActionRule(id="persist", nazwa="ok", działanie="sugeruj_pomijanie")
        )
        engine2 = RuleEngine("XYZ", data_dir=sys_rules_dir)
        assert len(engine2.client_rules) == 1
        assert engine2.client_rules[0].id == "persist"

    def test_zachowuje_decisions_section(self, sys_rules_dir: Path):
        # Symulacja: w pliku jest już sekcja decisions z Unit 9
        path = sys_rules_dir / "rules_klient_XYZ.json"
        path.write_text(
            json.dumps({
                "klient_id": "XYZ",
                "rules": [],
                "decisions": [{"id": "dec_001", "miesiąc": "2025-11"}],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        engine.add_client_rule(ActionRule(id="r1", nazwa="x", działanie="sugeruj_pomijanie"))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["decisions"] == [{"id": "dec_001", "miesiąc": "2025-11"}]


# ---------------------------------------------------------------------------
# Conflict resolution: klient wygrywa
# ---------------------------------------------------------------------------

class TestConflictResolution:
    def test_klient_nadpisuje_system_to_samo_id(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        engine.add_client_rule(ActionRule(
            id="sys_small",  # to samo id co system rule
            nazwa="Klient: NIE pomijaj małych",
            działanie="nie_można_ruszać",
            forma="KPIR",
            wartość_max=Decimal("50"),
            priorytet=8,
        ))
        doc = make_doc(typ="KP", wartość="30")
        rule = engine.query_one(doc, forma="KPIR")
        assert rule is not None
        assert rule.id == "sys_small"
        assert rule.działanie == "nie_można_ruszać"
        assert rule.typ == "client_preference"

    def test_klient_wygrywa_przy_tym_samym_priorytecie(self, empty_dir: Path):
        (empty_dir / "rules_system.json").write_text(
            json.dumps({"action_rules": [
                {"id": "sys_a", "nazwa": "sys", "działanie": "sugeruj_pomijanie",
                 "priorytet": 5, "typ_dokumentu": "KP"},
            ]}, ensure_ascii=False),
            encoding="utf-8",
        )
        engine = RuleEngine("XYZ", data_dir=empty_dir)
        engine.add_client_rule(ActionRule(
            id="client_a",
            nazwa="Klient",
            działanie="sugeruj_zbiorczy",
            priorytet=5,
            typ_dokumentu="KP",
        ))
        doc = make_doc(typ="KP")
        rule = engine.query_one(doc, forma="KPIR")
        assert rule is not None
        assert rule.typ == "client_preference"


# ---------------------------------------------------------------------------
# mark_used – usage tracking
# ---------------------------------------------------------------------------

class TestMarkUsed:
    def test_client_rule_persistuje_licznik(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        engine.add_client_rule(ActionRule(id="cu", nazwa="x", działanie="sugeruj_pomijanie"))
        engine.mark_used("cu")
        assert engine.client_rules[0].liczba_zastosowań == 1
        assert engine.client_rules[0].data_ostatniego_użycia is not None

        data = json.loads((sys_rules_dir / "rules_klient_XYZ.json").read_text(encoding="utf-8"))
        assert data["rules"][0]["liczba_zastosowań"] == 1

    def test_system_rule_in_memory_only(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        engine.mark_used("sys_small")
        rule = next(r for r in engine.system_rules if r.id == "sys_small")
        assert rule.liczba_zastosowań == 1
        # Nie persistowane: plik systemowy nie zmodyfikowany
        original = json.loads((sys_rules_dir / "rules_system.json").read_text(encoding="utf-8"))
        sys_small = next(r for r in original["action_rules"] if r["id"] == "sys_small")
        assert sys_small.get("liczba_zastosowań", 0) == 0

    def test_nieistniejaca_rule_no_exception(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        engine.mark_used("not_a_rule")  # nie podnosi wyjątku

    def test_wielokrotne_uzycie_kumuluje(self, sys_rules_dir: Path):
        engine = RuleEngine("XYZ", data_dir=sys_rules_dir)
        engine.add_client_rule(ActionRule(id="cu", nazwa="x", działanie="sugeruj_pomijanie"))
        engine.mark_used("cu")
        engine.mark_used("cu")
        engine.mark_used("cu")
        assert engine.client_rules[0].liczba_zastosowań == 3


# ---------------------------------------------------------------------------
# ActionRule.matches – warunki dopasowania
# ---------------------------------------------------------------------------

class TestActionRuleMatches:
    def test_matches_risk_level(self):
        rule = ActionRule(id="r", nazwa="n", działanie="sugeruj_pomijanie", risk_level="LOW")
        assert rule.matches(make_doc(risk_level="LOW"), "KPIR")
        assert not rule.matches(make_doc(risk_level="HIGH"), "KPIR")
        assert not rule.matches(make_doc(risk_level=None), "KPIR")

    def test_matches_zakres_wartosci(self):
        rule = ActionRule(
            id="r", nazwa="n", działanie="sugeruj_pomijanie",
            wartość_min=Decimal("50"), wartość_max=Decimal("200"),
        )
        assert rule.matches(make_doc(wartość="100"), "KPIR")
        assert rule.matches(make_doc(wartość="50"), "KPIR")        # min inclusive
        assert not rule.matches(make_doc(wartość="200"), "KPIR")   # max exclusive
        assert not rule.matches(make_doc(wartość="30"), "KPIR")

    def test_matches_brak_warunkow_pasuje_zawsze(self):
        rule = ActionRule(id="r", nazwa="n", działanie="sugeruj_pomijanie")
        assert rule.matches(make_doc(typ="KP"), "KPIR")
        assert rule.matches(make_doc(typ="NT"), "KSH")

    def test_to_dict_round_trip(self):
        from analyzer.rules import _parse_action_rule

        original = ActionRule(
            id="rt",
            nazwa="round trip",
            działanie="sugeruj_pomijanie",
            forma="KPIR",
            wartość_min=Decimal("10.50"),
            wartość_max=Decimal("100"),
            risk_level="LOW",
            tagi=["a", "b"],
            liczba_zastosowań=3,
        )
        parsed = _parse_action_rule(original.to_dict())
        assert parsed.id == original.id
        assert parsed.działanie == original.działanie
        assert parsed.wartość_min == original.wartość_min
        assert parsed.wartość_max == original.wartość_max
        assert parsed.risk_level == "LOW"
        assert parsed.tagi == ["a", "b"]
        assert parsed.liczba_zastosowań == 3


# ---------------------------------------------------------------------------
# Integration: production rules_system.json
# ---------------------------------------------------------------------------

class TestProductionSystemRules:
    def test_laduje_systemowe_action_rules(self):
        """Smoke test – production data/rules_system.json ma poprawne action_rules."""
        engine = RuleEngine("smoke_test_client")
        ids = {r.id for r in engine.system_rules}
        assert "action_high_risk_nogo" in ids
        assert "action_kpir_male_skip" in ids

    def test_high_risk_dostaje_nogo(self):
        engine = RuleEngine("smoke_test_client")
        doc = make_doc(risk_level="HIGH")
        rule = engine.query_one(doc, forma="KSH")
        assert rule is not None
        assert rule.działanie == "nie_można_ruszać"
