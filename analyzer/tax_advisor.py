from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from .models import Document

logger = logging.getLogger(__name__)

_DEFAULT_RULES_PATH = Path(__file__).parent.parent / "data" / "rules_system.json"

VALID_RISK_LEVELS = {"LOW", "MED", "HIGH"}


@dataclass
class RiskRule:
    """Pojedyncza reguła oceny ryzyka. Wszystkie warunki muszą być spełnione (AND).

    Pole `None` oznacza, że dana warunek nie jest sprawdzany.
    """

    id: str
    nazwa: str
    risk_level: str             # LOW / MED / HIGH
    priorytet: int = 50         # wyższy = pierwszeństwo
    powód: str = ""
    typ_dokumentu: Optional[str] = None       # KP / NT / KD
    forma: Optional[str] = None               # KPIR / KSH / Ryczałt VAT
    typ_płatności: Optional[str] = None       # gotówka / przelew
    wartość_min: Optional[Decimal] = None     # inclusive
    wartość_max: Optional[Decimal] = None     # exclusive

    def matches(self, doc: Document, forma: str) -> bool:
        if self.typ_dokumentu is not None and doc.typ != self.typ_dokumentu:
            return False
        if self.forma is not None and forma != self.forma:
            return False
        if self.typ_płatności is not None and doc.typ_płatności != self.typ_płatności:
            return False
        if self.wartość_min is not None and doc.wartość < self.wartość_min:
            return False
        if self.wartość_max is not None and doc.wartość >= self.wartość_max:
            return False
        return True


@dataclass
class RiskAssessment:
    level: str                  # LOW / MED / HIGH
    powód: str
    matched_rule_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------

def load_risk_rules(path: Optional[Path] = None) -> List[RiskRule]:
    """Wczytuje reguły ryzyka z JSON; zwraca posortowane DESC po priorytecie."""
    path = path or _DEFAULT_RULES_PATH
    if not path.exists():
        logger.warning("Risk rules file not found at %s – returning empty list", path)
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load risk rules from %s: %s", path, exc)
        return []

    rules: List[RiskRule] = []
    for entry in raw.get("risk_rules", []):
        try:
            rules.append(_parse_rule(entry))
        except (KeyError, ValueError) as exc:
            logger.warning("Skipping malformed rule %r: %s", entry.get("id", "?"), exc)
    return sorted(rules, key=lambda r: -r.priorytet)


def _parse_rule(entry: dict) -> RiskRule:
    level = entry["risk_level"]
    if level not in VALID_RISK_LEVELS:
        raise ValueError(f"Invalid risk_level: {level!r}")
    return RiskRule(
        id=entry["id"],
        nazwa=entry.get("nazwa", entry["id"]),
        risk_level=level,
        priorytet=int(entry.get("priorytet", 50)),
        powód=entry.get("powód", ""),
        typ_dokumentu=entry.get("typ_dokumentu"),
        forma=entry.get("forma"),
        typ_płatności=entry.get("typ_płatności"),
        wartość_min=_to_decimal(entry.get("wartość_min")),
        wartość_max=_to_decimal(entry.get("wartość_max")),
    )


def _to_decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

def _assess_one(doc: Document, forma: str, sorted_rules: List[RiskRule]) -> RiskAssessment:
    for rule in sorted_rules:
        if rule.matches(doc, forma):
            return RiskAssessment(
                level=rule.risk_level,
                powód=rule.powód or f"Reguła: {rule.nazwa}",
                matched_rule_id=rule.id,
            )
    return RiskAssessment(
        level="MED",
        powód="Brak pasującej reguły – conservative default MED",
        matched_rule_id=None,
    )


def assess_document(
    doc: Document,
    forma: str,
    rules: Optional[List[RiskRule]] = None,
) -> RiskAssessment:
    """Ocenia poziom ryzyka pojedynczego dokumentu.

    Pierwsza pasująca reguła (sortowane DESC po priorytecie) wygrywa.
    Brak dopasowania → MED (conservative default).
    """
    rules = rules if rules is not None else load_risk_rules()
    sorted_rules = sorted(rules, key=lambda r: -r.priorytet)
    return _assess_one(doc, forma, sorted_rules)


def assess_all(
    documents: List[Document],
    forma: str,
    rules: Optional[List[RiskRule]] = None,
) -> List[Document]:
    """Ocenia ryzyko dla wszystkich dokumentów (mutuje listę in-place).

    Każdy dokument dostaje `risk_level`, `status='risk_assessed'` oraz
    wpis w `historia` z powodem oceny.
    """
    rules = rules if rules is not None else load_risk_rules()
    sorted_rules = sorted(rules, key=lambda r: -r.priorytet)

    for doc in documents:
        assessment = _assess_one(doc, forma, sorted_rules)
        doc.risk_level = assessment.level
        doc.status = "risk_assessed"
        doc.dodaj_historię(
            "risk_assessment",
            {
                "level": assessment.level,
                "powód": assessment.powód,
                "matched_rule_id": assessment.matched_rule_id,
                "forma": forma,
            },
        )
    return documents
