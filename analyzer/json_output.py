from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Document, Variant

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Document serialization
# ---------------------------------------------------------------------------

def document_to_dict(doc: Document) -> Dict[str, Any]:
    """Serializuje Document do JSON-compatible dict."""
    return {
        "id": doc.id,
        "numer": doc.numer,
        "data": doc.data.isoformat(),
        "nip_dostawcy": doc.nip_dostawcy,
        "wartość": str(doc.wartość),
        "typ": doc.typ,
        "typ_płatności": doc.typ_płatności,
        "risk_level": doc.risk_level,
        "status": doc.status,
    }


# ---------------------------------------------------------------------------
# Variant serialization
# ---------------------------------------------------------------------------

def variant_to_dict(variant: Variant) -> Dict[str, Any]:
    """Serializuje Variant do JSON-compatible dict."""
    return {
        "id": variant.id,
        "oszczędność": str(variant.oszczędność),
        "risk_level": variant.risk_level,
        "compatibility_score": round(variant.compatibility_score, 4),
        "score": round(variant.score, 4),
        "impact_message": variant.impact_message,
        "dokumenty_do_pomijania": [
            document_to_dict(d) for d in variant.dokumenty_do_pomijania
        ],
        "grupy_do_zbiorczenia": [
            {"dostawca": dostawca, "dokumenty": [document_to_dict(d) for d in docs]}
            for dostawca, docs in variant.grupy_do_zbiorczenia
        ],
        "dokumenty_do_przesunięcia": [
            {"dokument": document_to_dict(doc), "target_month": month}
            for doc, month in variant.dokumenty_do_przesunięcia
        ],
    }


# ---------------------------------------------------------------------------
# Analysis serialization
# ---------------------------------------------------------------------------

def serialize_analysis(
    variants: List[Variant],
    klient_id: str,
    no_go: Optional[List[Document]] = None,
    period: str = "",
) -> Dict[str, Any]:
    """Buduje JSON-compatible dict z wynikami analizy.

    Args:
        variants: Posortowana lista wariantów (top-N z rank_variants).
        klient_id: Identyfikator klienta.
        no_go: Dokumenty wykluczone z optymalizacji (opcjonalnie).
        period: Okres analizy, np. "2024-11".
    """
    no_go = no_go or []
    summary: Dict[str, Any] = {"total_variants": len(variants), "no_go_count": len(no_go)}
    if variants:
        best = variants[0]
        summary["best_savings"] = str(best.oszczędność)
        summary["best_risk_level"] = best.risk_level
        summary["best_score"] = round(best.score, 4)

    return {
        "klient_id": klient_id,
        "period": period,
        "generated_at": datetime.now().isoformat(),
        "summary": summary,
        "variants": [variant_to_dict(v) for v in variants],
        "no_go": [document_to_dict(d) for d in no_go],
    }


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def save_analysis(
    variants: List[Variant],
    klient_id: str,
    output_path: Path,
    no_go: Optional[List[Document]] = None,
    period: str = "",
) -> Path:
    """Zapisuje wyniki analizy do pliku JSON.

    Returns:
        Ścieżka do zapisanego pliku.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = serialize_analysis(variants, klient_id, no_go=no_go, period=period)
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Analysis saved to %s (%d variants)", output_path, len(variants))
    return output_path


def load_analysis(path: Path) -> Dict[str, Any]:
    """Wczytuje wcześniej zapisaną analizę z pliku JSON."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    logger.info("Analysis loaded from %s", path)
    return data
