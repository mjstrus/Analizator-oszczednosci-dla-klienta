from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Document

logger = logging.getLogger(__name__)

VALID_ACTIONS = {
    "sugeruj_pomijanie",
    "sugeruj_zbiorczy",
    "sugeruj_przesunięcie",
    "nie_można_ruszać",
}
VALID_RISK_LEVELS = {"LOW", "MED", "HIGH"}

DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass
class ActionRule:
    """Reguła sugerująca akcję dla dokumentu.

    Wszystkie warunki muszą być spełnione (AND). `None` = nie sprawdzane.
    """

    id: str
    nazwa: str
    działanie: str                                  # patrz VALID_ACTIONS
    typ: str = "system"                             # system | client_preference
    priorytet: int = 5

    # Warunki dopasowania
    typ_dokumentu: Optional[str] = None             # KP / NT / KD
    forma: Optional[str] = None                     # KPIR / KSH / Ryczałt VAT
    typ_płatności: Optional[str] = None             # gotówka / przelew
    wartość_min: Optional[Decimal] = None           # inclusive
    wartość_max: Optional[Decimal] = None           # exclusive
    risk_level: Optional[str] = None                # LOW / MED / HIGH (z Tax Advisora)

    # Metadane
    źródło: str = "manual"
    klient_id: Optional[str] = None
    tagi: List[str] = field(default_factory=list)
    data_utworzenia: Optional[str] = None
    liczba_zastosowań: int = 0
    data_ostatniego_użycia: Optional[str] = None

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
        if self.risk_level is not None and doc.risk_level != self.risk_level:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """JSON-compatible serialization (Decimal → str, None skipped)."""
        d = asdict(self)
        for k in ("wartość_min", "wartość_max"):
            if d[k] is not None:
                d[k] = str(d[k])
        return {k: v for k, v in d.items() if v is not None}


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(value))


def _parse_action_rule(entry: dict, default_typ: str = "system") -> ActionRule:
    działanie = entry["działanie"]
    if działanie not in VALID_ACTIONS:
        raise ValueError(f"Invalid działanie: {działanie!r}")
    risk_level = entry.get("risk_level")
    if risk_level is not None and risk_level not in VALID_RISK_LEVELS:
        raise ValueError(f"Invalid risk_level: {risk_level!r}")
    return ActionRule(
        id=entry["id"],
        nazwa=entry.get("nazwa", entry["id"]),
        działanie=działanie,
        typ=entry.get("typ", default_typ),
        priorytet=int(entry.get("priorytet", 5)),
        typ_dokumentu=entry.get("typ_dokumentu"),
        forma=entry.get("forma"),
        typ_płatności=entry.get("typ_płatności"),
        wartość_min=_to_decimal(entry.get("wartość_min")),
        wartość_max=_to_decimal(entry.get("wartość_max")),
        risk_level=risk_level,
        źródło=entry.get("źródło", "manual"),
        klient_id=entry.get("klient_id"),
        tagi=list(entry.get("tagi", [])),
        data_utworzenia=entry.get("data_utworzenia"),
        liczba_zastosowań=int(entry.get("liczba_zastosowań", 0)),
        data_ostatniego_użycia=entry.get("data_ostatniego_użycia"),
    )


class RuleEngine:
    """Zarządza regułami akcji: system (read-only) + client_preference (R/W, persistent).

    Storage:
    - System rules: `data/rules_system.json` → klucz "action_rules"
    - Client rules: `data/rules_klient_{klient_id}.json` → klucz "rules"
      (sekcja "decisions" jest zachowywana przez save dla Unit 9)

    Konflikt: jeśli reguła klienta ma to samo `id` co systemowa, klient nadpisuje.
    Przy tym samym priorytecie klient też wygrywa (preferencja użytkownika).
    """

    def __init__(self, klient_id: str, data_dir: Optional[Path] = None):
        self.klient_id = klient_id
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.system_rules: List[ActionRule] = []
        self.client_rules: List[ActionRule] = []
        self._load_system_rules()
        self._load_client_rules()

    @property
    def system_rules_path(self) -> Path:
        return self.data_dir / "rules_system.json"

    @property
    def client_rules_path(self) -> Path:
        return self.data_dir / f"rules_klient_{self.klient_id}.json"

    def _load_system_rules(self) -> None:
        if not self.system_rules_path.exists():
            logger.warning("System rules file not found at %s", self.system_rules_path)
            return
        try:
            data = json.loads(self.system_rules_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load system rules: %s", exc)
            return
        for entry in data.get("action_rules", []):
            try:
                self.system_rules.append(_parse_action_rule(entry, default_typ="system"))
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping malformed system rule %r: %s", entry.get("id", "?"), exc)

    def _load_client_rules(self) -> None:
        if not self.client_rules_path.exists():
            logger.info("No client rules file for %s yet", self.klient_id)
            return
        try:
            data = json.loads(self.client_rules_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load client rules for %s: %s", self.klient_id, exc)
            return
        for entry in data.get("rules", []):
            try:
                rule = _parse_action_rule(entry, default_typ="client_preference")
                if rule.klient_id is None:
                    rule.klient_id = self.klient_id
                self.client_rules.append(rule)
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping malformed client rule %r: %s", entry.get("id", "?"), exc)

    def all_rules(self) -> List[ActionRule]:
        """Zwraca wszystkie reguły posortowane: priorytet DESC, klient przed system na remisie."""
        merged: Dict[str, ActionRule] = {r.id: r for r in self.system_rules}
        for r in self.client_rules:
            merged[r.id] = r  # client wins on same id
        rules = list(merged.values())
        rules.sort(key=lambda r: (-r.priorytet, 0 if r.typ == "client_preference" else 1))
        return rules

    def query(self, doc: Document, forma: str) -> List[ActionRule]:
        """Zwraca wszystkie reguły dopasowane do dokumentu (DESC po priorytecie)."""
        return [r for r in self.all_rules() if r.matches(doc, forma)]

    def query_one(self, doc: Document, forma: str) -> Optional[ActionRule]:
        """Zwraca regułę o najwyższym priorytecie pasującą do dokumentu."""
        for rule in self.all_rules():
            if rule.matches(doc, forma):
                return rule
        return None

    def add_client_rule(self, rule: ActionRule) -> None:
        """Dodaje (lub zastępuje po `id`) regułę client_preference i persistuje."""
        rule.typ = "client_preference"
        if rule.klient_id is None:
            rule.klient_id = self.klient_id
        if rule.data_utworzenia is None:
            rule.data_utworzenia = datetime.now().isoformat()

        existing_idx = next(
            (i for i, r in enumerate(self.client_rules) if r.id == rule.id), None
        )
        if existing_idx is not None:
            self.client_rules[existing_idx] = rule
        else:
            self.client_rules.append(rule)
        self._save_client_rules()

    def mark_used(self, rule_id: str) -> None:
        """Inkrementuje `liczba_zastosowań` i ustawia `data_ostatniego_użycia`.

        Client rules są persistowane; system rules są tylko in-memory
        (system rules są read-only z punktu widzenia engine).
        """
        now = datetime.now().isoformat()
        for rule in self.client_rules:
            if rule.id == rule_id:
                rule.liczba_zastosowań += 1
                rule.data_ostatniego_użycia = now
                self._save_client_rules()
                return
        for rule in self.system_rules:
            if rule.id == rule_id:
                rule.liczba_zastosowań += 1
                rule.data_ostatniego_użycia = now
                return
        logger.warning("mark_used: rule %r not found", rule_id)

    def _save_client_rules(self) -> None:
        """Zapisuje rules do pliku klienta zachowując sekcję 'decisions' (Unit 9)."""
        payload: Dict[str, Any] = {"klient_id": self.klient_id, "rules": [], "decisions": []}
        if self.client_rules_path.exists():
            try:
                payload = json.loads(self.client_rules_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Cannot read existing client file, overwriting: %s", exc)
                payload = {"klient_id": self.klient_id, "rules": [], "decisions": []}

        payload["klient_id"] = self.klient_id
        payload["rules"] = [r.to_dict() for r in self.client_rules]
        payload.setdefault("decisions", [])

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.client_rules_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def reload(self) -> None:
        """Wymusza przeładowanie z dysku (np. po zmianie z innego procesu)."""
        self.system_rules = []
        self.client_rules = []
        self._load_system_rules()
        self._load_client_rules()
