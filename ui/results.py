from __future__ import annotations

from typing import List

import streamlit as st

from analyzer.models import Document, Variant
from ui.variant_card import format_savings, format_score, format_compatibility, _RISK_LABEL


def render_summary_metrics(variants: List[Variant], no_go: List[Document]) -> None:
    """Renderuje podsumowanie: 4 metryki w górnym wierszu."""
    best_savings = variants[0].oszczędność if variants else None
    best_risk = variants[0].risk_level if variants else None

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "Najlepsza oszczędność",
        format_savings(best_savings) if best_savings is not None else "–",
    )
    col2.metric("Warianty", len(variants))
    col3.metric(
        "Ryzyko (najlepszy)",
        _RISK_LABEL.get(best_risk, best_risk) if best_risk else "–",
    )
    col4.metric("Dokumenty NO-GO", len(no_go))


def render_no_go_section(no_go: List[Document]) -> None:
    """Renderuje sekcję dokumentów wykluczonych z optymalizacji."""
    if not no_go:
        return

    with st.expander(f"Dokumenty wykluczone z optymalizacji ({len(no_go)})", expanded=False):
        rows = []
        for doc in no_go:
            rows.append({
                "Numer": doc.numer,
                "Data": doc.data.strftime("%d.%m.%Y"),
                "NIP dostawcy": doc.nip_dostawcy,
                "Wartość": format_savings(doc.wartość),
                "Typ": doc.typ,
                "Ryzyko": _RISK_LABEL.get(doc.risk_level, doc.risk_level or "–"),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
