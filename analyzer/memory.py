from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .models import Variant
from .ranker import load_decisions_from_engine
from .rules import RuleEngine

logger = logging.getLogger(__name__)


def variant_to_decision(variant: Variant) -> Dict[str, Any]:
    """Konwertuje Variant na rekord decyzji zgodny ze schematem ranker.py.

    Schema:
      {"risk_level": "LOW", "akcje": {"pomijanie": bool, "zbiorczy": bool, "przesunięcie": bool}}
    """
    return {
        "risk_level": variant.risk_level,
        "akcje": {
            "pomijanie": bool(variant.dokumenty_do_pomijania),
            "zbiorczy": bool(variant.grupy_do_zbiorczenia),
            "przesunięcie": bool(variant.dokumenty_do_przesunięcia),
        },
    }


def record_decision(engine: RuleEngine, variant: Variant) -> None:
    """Zapisuje decyzję do pliku klienta (sekcja 'decisions').

    Nie nadpisuje ani reguł, ani wcześniejszych decyzji — dopisuje nową.
    """
    decision = variant_to_decision(variant)
    decision["timestamp"] = datetime.now().isoformat()
    decision["variant_id"] = variant.id

    path: Path = engine.client_rules_path
    payload: Dict[str, Any] = {
        "klient_id": engine.klient_id,
        "rules": [],
        "decisions": [],
    }
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cannot read client file %s, starting fresh: %s", path, exc)
            payload = {"klient_id": engine.klient_id, "rules": [], "decisions": []}

    payload.setdefault("decisions", [])
    payload["decisions"].append(decision)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "Decision recorded for client %s (variant %d, risk %s)",
        engine.klient_id, variant.id, variant.risk_level,
    )


def load_decisions(engine: RuleEngine) -> List[Dict[str, Any]]:
    """Zwraca listę decyzji klienta (deleguje do ranker.load_decisions_from_engine)."""
    return load_decisions_from_engine(engine)


def clear_decisions(engine: RuleEngine) -> None:
    """Czyści historię decyzji klienta (zachowuje reguły)."""
    path: Path = engine.client_rules_path
    if not path.exists():
        return

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Cannot read client file %s: %s", path, exc)
        return

    payload["decisions"] = []
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Decisions cleared for client %s", engine.klient_id)
