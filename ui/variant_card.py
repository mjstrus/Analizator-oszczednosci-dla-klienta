from __future__ import annotations

from decimal import Decimal
from typing import List

import streamlit as st

from analyzer.models import Document, Variant

_RISK_LABEL = {"LOW": "Niskie", "MED": "Średnie", "HIGH": "Wysokie"}
_RISK_COLOR = {"LOW": "green", "MED": "orange", "HIGH": "red"}


def format_risk(level: str) -> str:
    """Zwraca Markdown z kolorowym etykietą ryzyka."""
    label = _RISK_LABEL.get(level, level)
    color = _RISK_COLOR.get(level, "gray")
    return f":{color}[**{label}**]"


def format_savings(amount: Decimal) -> str:
    """Formatuje kwotę oszczędności jako string PLN."""
    return f"{float(amount):,.2f} zł".replace(",", " ")


def format_score(score: float) -> str:
    return f"{score:.3f}"


def format_compatibility(score: float) -> str:
    return f"{score * 100:.0f}%"


def _action_lines(variant: Variant) -> List[str]:
    lines = []
    if variant.dokumenty_do_pomijania:
        n = len(variant.dokumenty_do_pomijania)
        lines.append(f"- Pomiń {n} dokument{'y' if n > 1 else ''}")
    for dostawca, docs in variant.grupy_do_zbiorczenia:
        lines.append(f"- Zbiorczy {len(docs)} faktur (NIP {dostawca})")
    for doc, month in variant.dokumenty_do_przesunięcia:
        lines.append(f"- Przesuń {doc.numer} → {month}")
    return lines


def render_variant_card(variant: Variant, index: int, selected_id: int) -> bool:
    """Renderuje kartę wariantu. Zwraca True jeśli kliknięto 'Wybierz'.

    Args:
        variant: Wariant do wyświetlenia.
        index: Numer karty (1-based, do wyświetlenia).
        selected_id: ID aktualnie wybranego wariantu (0 = brak wyboru).
    """
    is_selected = variant.id == selected_id
    border_color = "#27ae60" if is_selected else "#dde"
    bg_color = "#f0fff4" if is_selected else "#fafafa"

    with st.container(border=True):
        col_title, col_badge = st.columns([4, 1])
        with col_title:
            st.markdown(
                f"### Wariant {variant.id} &nbsp;·&nbsp; "
                f"Oszczędność: **{format_savings(variant.oszczędność)}**"
            )
        with col_badge:
            if is_selected:
                st.success("Wybrany")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Ryzyko", _RISK_LABEL.get(variant.risk_level, variant.risk_level))
        col2.metric("Zgodność", format_compatibility(variant.compatibility_score))
        col3.metric("Score", format_score(variant.score))
        col4.metric("Akcje", _count_actions(variant))

        action_lines = _action_lines(variant)
        if action_lines:
            with st.expander("Szczegóły akcji", expanded=is_selected):
                st.markdown("\n".join(action_lines))

        if variant.impact_message:
            st.warning(f"Prognoza: {variant.impact_message}")

        clicked = st.button(
            "Wybierz ten wariant" if not is_selected else "Wybrany",
            key=f"select_variant_{variant.id}",
            type="primary" if not is_selected else "secondary",
            disabled=is_selected,
        )
    return clicked


def _count_actions(variant: Variant) -> str:
    total = (
        len(variant.dokumenty_do_pomijania)
        + sum(len(d) for _, d in variant.grupy_do_zbiorczenia)
        + len(variant.dokumenty_do_przesunięcia)
    )
    return str(total) if total else "–"
