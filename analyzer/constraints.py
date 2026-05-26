from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import Document
from .rules import RuleEngine

logger = logging.getLogger(__name__)


@dataclass
class ConstraintResult:
    """Wynik klasyfikacji dokumentów: NO-GO vs pula do optymalizacji.

    Gwarancja: len(no_go) + len(remaining) == liczba wejściowych dokumentów.
    """

    no_go: List[Document]
    remaining: List[Document]
    reasons: Dict[str, str] = field(default_factory=dict)  # doc.id → powód NO-GO

    @property
    def all_documents(self) -> List[Document]:
        return self.no_go + self.remaining

    def summary(self) -> str:
        return (
            f"NO-GO: {len(self.no_go)}, "
            f"do optymalizacji: {len(self.remaining)}, "
            f"razem: {len(self.all_documents)}"
        )


def classify(
    documents: List[Document],
    forma: str,
    engine: RuleEngine,
) -> ConstraintResult:
    """Klasyfikuje dokumenty na NO-GO i remaining_set.

    Dokument trafia do NO-GO gdy spełniony jest co najmniej jeden warunek:
    1. risk_level == "HIGH"  (ocena Tax Advisora)
    2. Pierwsza pasująca reguła z Rule Engine ma działanie="nie_można_ruszać"

    Każdy NO-GO dokument dostaje wpis w `historia` z powodem.
    Reguły użyte do klasyfikacji są zaliczane przez `engine.mark_used`.
    """
    no_go: List[Document] = []
    remaining: List[Document] = []
    reasons: Dict[str, str] = {}

    for doc in documents:
        reason = _check_no_go(doc, forma, engine)
        if reason is not None:
            no_go.append(doc)
            reasons[doc.id] = reason
            doc.dodaj_historię("constraint_no_go", {"powód": reason})
            logger.debug("NO-GO: %s (%s) – %s", doc.numer, doc.id, reason)
        else:
            remaining.append(doc)

    logger.info("Constraints: %s", ConstraintResult(no_go, remaining, reasons).summary())
    return ConstraintResult(no_go=no_go, remaining=remaining, reasons=reasons)


def split(
    documents: List[Document],
    forma: str,
    engine: RuleEngine,
) -> Tuple[List[Document], List[Document]]:
    """Convenience wrapper – zwraca (no_go, remaining)."""
    result = classify(documents, forma, engine)
    return result.no_go, result.remaining


def _check_no_go(
    doc: Document,
    forma: str,
    engine: RuleEngine,
) -> Optional[str]:
    """Zwraca powód NO-GO lub None jeśli dokument wchodzi do puli optymalizacji."""
    # 1. HIGH RISK zawsze NO-GO
    if doc.risk_level == "HIGH":
        powód = _extract_risk_reason(doc)
        return f"HIGH risk – {powód}"

    # 2. Pierwsza pasująca reguła = nie_można_ruszać → NO-GO
    for rule in engine.query(doc, forma):
        if rule.działanie == "nie_można_ruszać":
            engine.mark_used(rule.id)
            return f"Reguła '{rule.nazwa}' (id={rule.id}): nie można ruszać"

    return None


def _extract_risk_reason(doc: Document) -> str:
    """Wyciąga powód przypisania risk_level z historii dokumentu."""
    for entry in reversed(doc.historia):
        if entry.get("zdarzenie") == "risk_assessment":
            return entry.get("szczegóły", {}).get("powód", "HIGH risk")
    return "HIGH risk"
