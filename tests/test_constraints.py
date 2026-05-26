from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from analyzer.constraints import ConstraintResult, classify, split
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
        id=f"id-{numer.replace('/', '-')}",
        numer=numer,
        data=datetime(2025, 11, 1),
        nip_dostawcy="1234567890",
        wartość=Decimal(wartość),
        typ=typ,
        typ_płatności=typ_płatności,
        risk_level=risk_level,
    )


@pytest.fixture
def empty_engine(tmp_path: Path) -> RuleEngine:
    """Engine bez żadnych reguł."""
    return RuleEngine("XYZ", data_dir=tmp_path)


@pytest.fixture
def nogo_rule_engine(tmp_path: Path) -> RuleEngine:
    """Engine z regułą nie_można_ruszać dla KPIR + wartość < 50."""
    (tmp_path / "rules_system.json").write_text(
        json.dumps({"action_rules": [
            {
                "id": "test_nogo",
                "nazwa": "Małe KPIR – nie ruszać (testowa)",
                "działanie": "nie_można_ruszać",
                "forma": "KPIR",
                "wartość_max": 50,
                "priorytet": 8,
            },
        ]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return RuleEngine("XYZ", data_dir=tmp_path)


@pytest.fixture
def production_engine(tmp_path: Path) -> RuleEngine:
    """Engine z produkcyjnymi regułami (rules_system.json z repo)."""
    import shutil
    src = Path(__file__).parent.parent / "data" / "rules_system.json"
    shutil.copy(src, tmp_path / "rules_system.json")
    return RuleEngine("XYZ", data_dir=tmp_path)


# ---------------------------------------------------------------------------
# Scenariusze z planu Unit 4
# ---------------------------------------------------------------------------

class TestPlannedScenarios:
    def test_wszystkie_low_risk_to_remaining(self, empty_engine: RuleEngine):
        docs = [
            make_doc(risk_level="LOW", numer="FV/1"),
            make_doc(risk_level="LOW", numer="FV/2"),
            make_doc(risk_level="LOW", numer="FV/3"),
        ]
        result = classify(docs, forma="KPIR", engine=empty_engine)
        assert result.no_go == []
        assert len(result.remaining) == 3

    def test_jeden_high_risk_reszta_low(self, empty_engine: RuleEngine):
        docs = [
            make_doc(risk_level="HIGH", numer="FV/HIGH"),
            make_doc(risk_level="LOW", numer="FV/LOW/1"),
            make_doc(risk_level="LOW", numer="FV/LOW/2"),
        ]
        result = classify(docs, forma="KPIR", engine=empty_engine)
        assert len(result.no_go) == 1
        assert result.no_go[0].numer == "FV/HIGH"
        assert len(result.remaining) == 2

    def test_rule_nie_mozna_ruszac_ignoruje_risk_level(self, nogo_rule_engine: RuleEngine):
        # LOW risk, ale reguła "nie_można_ruszać" → NO-GO
        doc = make_doc(risk_level="LOW", typ="KP", wartość="30")
        result = classify([doc], forma="KPIR", engine=nogo_rule_engine)
        assert len(result.no_go) == 1
        assert len(result.remaining) == 0

    def test_ksh_przelew_high_risk_trafia_do_nogo(self, empty_engine: RuleEngine):
        # Tax Advisor ustawia HIGH dla KSH+przelew; tu symulujemy już oceniony dokument
        doc = make_doc(
            typ="KP", typ_płatności="przelew", risk_level="HIGH", numer="FV/KSH"
        )
        result = classify([doc], forma="KSH", engine=empty_engine)
        assert len(result.no_go) == 1
        assert len(result.remaining) == 0


# ---------------------------------------------------------------------------
# Niezmiennik: no_go + remaining = wszystkie dokumenty
# ---------------------------------------------------------------------------

class TestInvariant:
    def test_partycja_pokrywa_wszystkie_dokumenty(self, production_engine: RuleEngine):
        docs = [
            make_doc(risk_level="HIGH", numer="FV/H"),
            make_doc(risk_level="LOW", numer="FV/L"),
            make_doc(risk_level="MED", numer="FV/M"),
        ]
        result = classify(docs, forma="KPIR", engine=production_engine)
        all_ids = {d.id for d in docs}
        result_ids = {d.id for d in result.all_documents}
        assert all_ids == result_ids

    def test_kazdy_dokument_w_dokladnie_jednym_zbiorze(self, empty_engine: RuleEngine):
        docs = [make_doc(numer=f"FV/{i}", risk_level="LOW") for i in range(10)]
        result = classify(docs, forma="KPIR", engine=empty_engine)
        no_go_ids = {d.id for d in result.no_go}
        remaining_ids = {d.id for d in result.remaining}
        # Rozłączne
        assert no_go_ids.isdisjoint(remaining_ids)
        # Razem = wszystkie
        assert len(no_go_ids) + len(remaining_ids) == len(docs)

    def test_brak_high_risk_w_remaining(self, empty_engine: RuleEngine):
        docs = [
            make_doc(risk_level="HIGH", numer="FV/H1"),
            make_doc(risk_level="HIGH", numer="FV/H2"),
            make_doc(risk_level="LOW", numer="FV/L"),
            make_doc(risk_level="MED", numer="FV/M"),
        ]
        result = classify(docs, forma="KPIR", engine=empty_engine)
        assert all(d.risk_level != "HIGH" for d in result.remaining)

    def test_pusty_input(self, empty_engine: RuleEngine):
        result = classify([], forma="KPIR", engine=empty_engine)
        assert result.no_go == []
        assert result.remaining == []
        assert result.all_documents == []


# ---------------------------------------------------------------------------
# Powody NO-GO i historia dokumentu
# ---------------------------------------------------------------------------

class TestReasonsAndHistory:
    def test_powod_w_reasons_dla_high_risk(self, empty_engine: RuleEngine):
        doc = make_doc(risk_level="HIGH", numer="FV/H")
        result = classify([doc], forma="KPIR", engine=empty_engine)
        assert doc.id in result.reasons
        assert "HIGH" in result.reasons[doc.id]

    def test_powod_zawiera_risk_reason_z_historii(self, empty_engine: RuleEngine):
        doc = make_doc(risk_level="HIGH", numer="FV/H")
        doc.dodaj_historię("risk_assessment", {
            "level": "HIGH",
            "powód": "KSH + przelew = obligatoryjny",
        })
        result = classify([doc], forma="KSH", engine=empty_engine)
        assert "KSH + przelew" in result.reasons[doc.id]

    def test_powod_w_reasons_dla_nogo_rule(self, nogo_rule_engine: RuleEngine):
        doc = make_doc(risk_level="LOW", typ="KP", wartość="30")
        result = classify([doc], forma="KPIR", engine=nogo_rule_engine)
        assert doc.id in result.reasons
        assert "test_nogo" in result.reasons[doc.id]

    def test_historia_zawiera_constraint_no_go_event(self, empty_engine: RuleEngine):
        doc = make_doc(risk_level="HIGH", numer="FV/H")
        classify([doc], forma="KPIR", engine=empty_engine)
        events = [e["zdarzenie"] for e in doc.historia]
        assert "constraint_no_go" in events
        nogo_entry = next(e for e in doc.historia if e["zdarzenie"] == "constraint_no_go")
        assert "powód" in nogo_entry["szczegóły"]

    def test_remaining_nie_dostaje_wpisu_w_historii(self, empty_engine: RuleEngine):
        doc = make_doc(risk_level="LOW", numer="FV/L")
        classify([doc], forma="KPIR", engine=empty_engine)
        events = [e["zdarzenie"] for e in doc.historia]
        assert "constraint_no_go" not in events

    def test_reasons_tylko_dla_nogo(self, empty_engine: RuleEngine):
        docs = [
            make_doc(risk_level="HIGH", numer="FV/H"),
            make_doc(risk_level="LOW", numer="FV/L"),
        ]
        result = classify(docs, forma="KPIR", engine=empty_engine)
        # Tylko no_go mają powód
        assert len(result.reasons) == 1
        assert docs[0].id in result.reasons
        assert docs[1].id not in result.reasons


# ---------------------------------------------------------------------------
# Tracking: mark_used na dopasowanych regułach
# ---------------------------------------------------------------------------

class TestMarkUsed:
    def test_uzyta_regula_dostaje_mark_used(self, nogo_rule_engine: RuleEngine):
        doc = make_doc(risk_level="LOW", typ="KP", wartość="30")
        classify([doc], forma="KPIR", engine=nogo_rule_engine)
        rule = next(r for r in nogo_rule_engine.system_rules if r.id == "test_nogo")
        assert rule.liczba_zastosowań == 1

    def test_nieuzyta_regula_nie_zmienia_licznika(self, nogo_rule_engine: RuleEngine):
        # Dokument, który NIE pasuje do reguły (wartość > 50)
        doc = make_doc(risk_level="LOW", typ="KP", wartość="200")
        classify([doc], forma="KPIR", engine=nogo_rule_engine)
        rule = next(r for r in nogo_rule_engine.system_rules if r.id == "test_nogo")
        assert rule.liczba_zastosowań == 0


# ---------------------------------------------------------------------------
# split() – convenience wrapper
# ---------------------------------------------------------------------------

class TestSplit:
    def test_split_zwraca_krotkę(self, empty_engine: RuleEngine):
        docs = [
            make_doc(risk_level="HIGH", numer="FV/H"),
            make_doc(risk_level="LOW", numer="FV/L"),
        ]
        no_go, remaining = split(docs, forma="KPIR", engine=empty_engine)
        assert len(no_go) == 1
        assert len(remaining) == 1
        assert no_go[0].numer == "FV/H"
        assert remaining[0].numer == "FV/L"


# ---------------------------------------------------------------------------
# Integracja z Tax Advisorem (Faza 1: parser → tax_advisor → constraints)
# ---------------------------------------------------------------------------

class TestIntegrationFaza1:
    def test_pelny_pipeline_kpir(self):
        """Parser → Tax Advisor → Constraints na fixture JPK_FA."""
        from pathlib import Path

        import shutil

        from analyzer.parser import parse_jpk_fa
        from analyzer.tax_advisor import assess_all

        xml = (Path(__file__).parent.parent / "fixtures" / "sample_jpk_fa.xml").read_bytes()
        docs = parse_jpk_fa(xml)
        assess_all(docs, forma="KPIR")

        tmp = Path("/tmp/test_constraints_integration")
        tmp.mkdir(exist_ok=True)
        shutil.copy(
            Path(__file__).parent.parent / "data" / "rules_system.json",
            tmp / "rules_system.json",
        )
        engine = RuleEngine("TEST_KLIENT", data_dir=tmp)
        result = classify(docs, forma="KPIR", engine=engine)

        # Niezmiennik
        assert len(result.all_documents) == len(docs)

        # KOR (KD) → MED → z produkcyjną regułą action_kd_korekta_nogo → NO-GO
        kor_docs = [d for d in docs if d.typ == "KD"]
        for kor in kor_docs:
            assert kor in result.no_go, f"Korekta {kor.numer} powinna być NO-GO"

        # Nota NT → LOW risk, produkcyjna reguła action_nota_skip = sugeruj_pomijanie
        # (NIE nie_można_ruszać) → nota powinna być w remaining
        nota_docs = [d for d in docs if d.typ == "NT"]
        for nota in nota_docs:
            assert nota in result.remaining, f"Nota {nota.numer} powinna być w remaining"
