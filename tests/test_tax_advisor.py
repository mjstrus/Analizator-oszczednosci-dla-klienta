from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from analyzer.models import Document
from analyzer.tax_advisor import (
    RiskAssessment,
    RiskRule,
    assess_all,
    assess_document,
    load_risk_rules,
)


def make_doc(
    typ: str = "KP",
    wartość: str = "100",
    typ_płatności: str = "przelew",
    numer: str = "FV/TEST/001",
) -> Document:
    return Document(
        id=f"id-{numer}",
        numer=numer,
        data=datetime(2025, 11, 1),
        nip_dostawcy="1234567890",
        wartość=Decimal(wartość),
        typ=typ,
        typ_płatności=typ_płatności,
    )


# ---------------------------------------------------------------------------
# Scenariusze z planu Unit 2
# ---------------------------------------------------------------------------

class TestPlannedScenarios:
    def test_kpir_gotowka_15zl_to_LOW(self):
        doc = make_doc(typ="KP", typ_płatności="gotówka", wartość="15")
        result = assess_document(doc, forma="KPIR")
        assert result.level == "LOW"
        assert result.matched_rule_id == "system_kpir_gotowka_male"

    def test_kpir_przelew_5000zl_to_MED(self):
        doc = make_doc(typ="KP", typ_płatności="przelew", wartość="5000")
        result = assess_document(doc, forma="KPIR")
        assert result.level == "MED"
        assert result.matched_rule_id == "system_kpir_przelew_duze"

    def test_ksh_przelew_zawsze_HIGH(self):
        for val in ["50", "500", "5000", "50000"]:
            doc = make_doc(typ="KP", typ_płatności="przelew", wartość=val)
            result = assess_document(doc, forma="KSH")
            assert result.level == "HIGH", f"KSH przelew {val} powinno być HIGH"

    def test_nota_zawsze_LOW_dla_kazdej_formy(self):
        for forma in ["KPIR", "KSH", "Ryczałt VAT"]:
            doc = make_doc(typ="NT", typ_płatności="przelew", wartość="1000")
            result = assess_document(doc, forma=forma)
            assert result.level == "LOW", f"NT w {forma} powinno być LOW"
            assert result.matched_rule_id == "system_nt_low"


# ---------------------------------------------------------------------------
# Custom rules / overrides
# ---------------------------------------------------------------------------

class TestCustomRules:
    def test_custom_rule_o_wyzszym_priorytecie_wygrywa(self):
        custom = [
            RiskRule(
                id="custom_override",
                nazwa="Override NT na HIGH",
                typ_dokumentu="NT",
                risk_level="HIGH",
                priorytet=200,
            )
        ]
        doc = make_doc(typ="NT", wartość="50")
        result = assess_document(doc, forma="KPIR", rules=custom)
        assert result.level == "HIGH"
        assert result.matched_rule_id == "custom_override"

    def test_brak_pasujacej_reguly_to_MED(self):
        doc = make_doc(typ="KP", typ_płatności="przelew", wartość="100")
        result = assess_document(doc, forma="KPIR", rules=[])
        assert result.level == "MED"
        assert result.matched_rule_id is None
        assert "default" in result.powód.lower()

    def test_pierwsza_pasujaca_po_priorytecie_wygrywa(self):
        rules = [
            RiskRule(id="r_low", nazwa="Low prio", risk_level="LOW",
                     priorytet=10, typ_dokumentu="KP"),
            RiskRule(id="r_high", nazwa="High prio", risk_level="HIGH",
                     priorytet=100, typ_dokumentu="KP"),
        ]
        doc = make_doc(typ="KP")
        result = assess_document(doc, forma="KPIR", rules=rules)
        assert result.matched_rule_id == "r_high"
        assert result.level == "HIGH"

    def test_rule_z_zakresem_wartosci(self):
        rule = RiskRule(
            id="zakres",
            nazwa="50-200",
            risk_level="MED",
            priorytet=50,
            wartość_min=Decimal("50"),
            wartość_max=Decimal("200"),
        )
        assert rule.matches(make_doc(wartość="100"), "KPIR")
        assert not rule.matches(make_doc(wartość="30"), "KPIR")
        assert not rule.matches(make_doc(wartość="200"), "KPIR")  # max jest exclusive
        assert rule.matches(make_doc(wartość="50"), "KPIR")        # min jest inclusive


# ---------------------------------------------------------------------------
# assess_all – batch mutation
# ---------------------------------------------------------------------------

class TestAssessAll:
    def test_mutuje_risk_level_na_dokumentach(self):
        docs = [
            make_doc(typ="NT", numer="FV/1"),
            make_doc(typ="KP", typ_płatności="gotówka", wartość="15", numer="FV/2"),
            make_doc(typ="KP", typ_płatności="przelew", wartość="5000", numer="FV/3"),
        ]
        assess_all(docs, forma="KPIR")
        assert docs[0].risk_level == "LOW"  # nota
        assert docs[1].risk_level == "LOW"  # małe + gotówka KPIR
        assert docs[2].risk_level == "MED"  # duże + przelew KPIR

    def test_zmienia_status_na_risk_assessed(self):
        docs = [make_doc(typ="NT", numer="FV/X")]
        assess_all(docs, forma="KPIR")
        assert docs[0].status == "risk_assessed"

    def test_zapisuje_historie_oceny(self):
        docs = [make_doc(typ="NT", numer="FV/HIST")]
        assess_all(docs, forma="KPIR")
        assert len(docs[0].historia) == 1
        entry = docs[0].historia[0]
        assert entry["zdarzenie"] == "risk_assessment"
        szczegóły = entry["szczegóły"]
        assert szczegóły["level"] == "LOW"
        assert szczegóły["matched_rule_id"] == "system_nt_low"
        assert szczegóły["forma"] == "KPIR"
        assert "powód" in szczegóły

    def test_pusty_list_dokumentow(self):
        result = assess_all([], forma="KPIR")
        assert result == []

    def test_korekta_dostaje_MED(self):
        docs = [make_doc(typ="KD", typ_płatności="przelew", wartość="-200", numer="KOR/1")]
        assess_all(docs, forma="KPIR")
        assert docs[0].risk_level == "MED"


# ---------------------------------------------------------------------------
# load_risk_rules
# ---------------------------------------------------------------------------

class TestLoadRiskRules:
    def test_laduje_systemowe_reguly(self):
        rules = load_risk_rules()
        assert len(rules) >= 6
        assert all(isinstance(r, RiskRule) for r in rules)
        ids = {r.id for r in rules}
        assert "system_nt_low" in ids
        assert "system_ksh_przelew_high" in ids

    def test_sortuje_DESC_po_priorytecie(self):
        rules = load_risk_rules()
        priorities = [r.priorytet for r in rules]
        assert priorities == sorted(priorities, reverse=True)

    def test_nieistniejacy_plik_zwraca_pusta_liste(self):
        rules = load_risk_rules(Path("/nonexistent/no_such_file.json"))
        assert rules == []

    def test_uszkodzony_json_zwraca_pusta_liste(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        assert load_risk_rules(bad) == []

    def test_nieprawidlowy_risk_level_skipped(self, tmp_path: Path):
        bad = tmp_path / "rules.json"
        bad.write_text(
            json.dumps({
                "risk_rules": [
                    {"id": "ok", "risk_level": "LOW", "priorytet": 50},
                    {"id": "bad", "risk_level": "INVALID", "priorytet": 60},
                ]
            }),
            encoding="utf-8",
        )
        rules = load_risk_rules(bad)
        assert len(rules) == 1
        assert rules[0].id == "ok"

    def test_decimal_wartosci_z_json(self, tmp_path: Path):
        path = tmp_path / "r.json"
        path.write_text(
            json.dumps({
                "risk_rules": [{
                    "id": "test",
                    "risk_level": "LOW",
                    "wartość_min": "10.50",
                    "wartość_max": 100,
                }]
            }),
            encoding="utf-8",
        )
        rules = load_risk_rules(path)
        assert rules[0].wartość_min == Decimal("10.50")
        assert rules[0].wartość_max == Decimal("100")


# ---------------------------------------------------------------------------
# Integration z parserem (smoke test)
# ---------------------------------------------------------------------------

class TestIntegrationWithParser:
    def test_assess_all_na_dokumentach_z_fixture(self):
        from analyzer.parser import parse_jpk_fa

        xml = (Path(__file__).parent.parent / "fixtures" / "sample_jpk_fa.xml").read_bytes()
        docs = parse_jpk_fa(xml)
        assess_all(docs, forma="KPIR")

        # Każdy dokument ma risk_level
        assert all(d.risk_level in {"LOW", "MED", "HIGH"} for d in docs)
        # Każdy ma status risk_assessed
        assert all(d.status == "risk_assessed" for d in docs)
        # Nota z fixture powinna być LOW
        nota = next(d for d in docs if d.typ == "NT")
        assert nota.risk_level == "LOW"
        # Korekta KOR (typ KD) powinna być MED
        korekta = next(d for d in docs if d.typ == "KD")
        assert korekta.risk_level == "MED"
