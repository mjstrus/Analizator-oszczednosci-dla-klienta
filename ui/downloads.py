from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import List, Optional

import streamlit as st

from analyzer.models import Document, Variant
from analyzer.json_output import serialize_analysis
from analyzer.pdf_generator import generate_report


def _generate_pdf_bytes(
    variants: List[Variant],
    klient_id: str,
    no_go: List[Document],
    period: str,
) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "raport.pdf"
        generate_report(variants, klient_id=klient_id, output_path=out, period=period)
        return out.read_bytes()


def _generate_json_bytes(
    variants: List[Variant],
    klient_id: str,
    no_go: List[Document],
    period: str,
) -> bytes:
    data = serialize_analysis(variants, klient_id=klient_id, no_go=no_go, period=period)
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def render_download_section(
    variants: List[Variant],
    klient_id: str,
    no_go: Optional[List[Document]] = None,
    period: str = "",
) -> None:
    """Renderuje przyciski pobierania raportu PDF i JSON."""
    no_go = no_go or []
    st.subheader("3. Pobierz raport")

    col_pdf, col_json = st.columns(2)

    with col_pdf:
        try:
            pdf_bytes = _generate_pdf_bytes(variants, klient_id, no_go, period)
            fname = f"raport_{klient_id}_{period or 'analiza'}.pdf"
            st.download_button(
                label="Pobierz raport PDF",
                data=pdf_bytes,
                file_name=fname,
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as exc:
            st.error(f"Błąd generowania PDF: {exc}")

    with col_json:
        try:
            json_bytes = _generate_json_bytes(variants, klient_id, no_go, period)
            fname = f"analiza_{klient_id}_{period or 'analiza'}.json"
            st.download_button(
                label="Pobierz dane JSON",
                data=json_bytes,
                file_name=fname,
                mime="application/json",
                use_container_width=True,
            )
        except Exception as exc:
            st.error(f"Błąd generowania JSON: {exc}")
