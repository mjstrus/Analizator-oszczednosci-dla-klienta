from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import streamlit as st

_FORMY = ["KPIR", "KSH", "Ryczałt VAT"]


def _default_period() -> str:
    return datetime.now().strftime("%Y-%m")


def validate_period(period: str) -> bool:
    """Zwraca True jeśli period ma format YYYY-MM."""
    parts = period.strip().split("-")
    if len(parts) != 2:
        return False
    try:
        year, month = int(parts[0]), int(parts[1])
        return 2000 <= year <= 2100 and 1 <= month <= 12
    except ValueError:
        return False


def render_sidebar() -> Dict[str, Any]:
    """Renderuje panel konfiguracji w sidebarze.

    Returns:
        dict z kluczami: klient_id, forma, period, top_n, valid (bool)
    """
    with st.sidebar:
        st.header("Konfiguracja analizy")
        st.divider()

        klient_id = st.text_input(
            "ID Klienta",
            value=st.session_state.get("cfg_klient_id", "KLIENT_001"),
            key="cfg_klient_id",
            help="Unikalny identyfikator klienta (zapisywany z decyzjami).",
        )

        forma = st.selectbox(
            "Forma księgowości",
            _FORMY,
            index=_FORMY.index(st.session_state.get("cfg_forma", "KPIR")),
            key="cfg_forma",
        )

        period = st.text_input(
            "Okres analizy (YYYY-MM)",
            value=st.session_state.get("cfg_period", _default_period()),
            key="cfg_period",
            help="Miesiąc, z którego pochodzi plik JPK_FA.",
        )

        top_n = st.slider(
            "Liczba wariantów TOP",
            min_value=1,
            max_value=10,
            value=st.session_state.get("cfg_top_n", 5),
            key="cfg_top_n",
        )

        st.divider()
        st.caption("Abacus Centrum Księgowe")

    period_ok = validate_period(period)
    klient_ok = bool(klient_id.strip())

    if not period_ok and period.strip():
        st.sidebar.warning("Nieprawidłowy format okresu. Użyj YYYY-MM.")
    if not klient_ok:
        st.sidebar.warning("Podaj ID klienta.")

    return {
        "klient_id": klient_id.strip(),
        "forma": forma,
        "period": period.strip(),
        "top_n": top_n,
        "valid": period_ok and klient_ok,
    }
