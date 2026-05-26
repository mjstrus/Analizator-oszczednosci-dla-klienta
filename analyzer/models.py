from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple


@dataclass
class Document:
    id: str
    numer: str
    data: datetime
    nip_dostawcy: str
    wartość: Decimal
    typ: str            # KP / NT / KD
    typ_płatności: str  # gotówka / przelew
    risk_level: Optional[str] = None  # LOW / MED / HIGH
    status: str = "new"
    historia: List[Dict] = field(default_factory=list)

    def dodaj_historię(self, zdarzenie: str, szczegóły: Optional[Dict] = None) -> None:
        self.historia.append(
            {
                "timestamp": datetime.now().isoformat(),
                "zdarzenie": zdarzenie,
                "szczegóły": szczegóły or {},
            }
        )


@dataclass
class Variant:
    id: int
    oszczędność: Decimal
    dokumenty_do_pomijania: List[Document]
    grupy_do_zbiorczenia: List[Tuple[str, List[Document]]]  # (dostawca, dokumenty)
    dokumenty_do_przesunięcia: List[Tuple[Document, str]]   # (dokument, target_month YYYY-MM)
    risk_level: str
    compatibility_score: float = 0.5
    score: float = 0.0
    impact_message: Optional[str] = None
