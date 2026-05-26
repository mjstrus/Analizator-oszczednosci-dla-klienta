from __future__ import annotations

import hashlib
from typing import Optional, Tuple

import streamlit as st


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_upload_section() -> Tuple[Optional[bytes], Optional[str]]:
    """Renderuje sekcję wgrywania pliku JPK_FA.

    Returns:
        (xml_bytes, file_hash) jeśli plik wgrany, inaczej (None, None).
    """
    st.subheader("1. Wgraj plik JPK_FA (XML)")
    uploaded = st.file_uploader(
        "Wybierz plik JPK_FA",
        type=["xml"],
        key="xml_upload",
        help="Plik JPK_FA w formacie XML (obsługiwane wersje: 1, 3, 4).",
        label_visibility="collapsed",
    )

    if uploaded is None:
        st.info("Prześlij plik JPK_FA XML, aby rozpocząć analizę oszczędności.")
        return None, None

    data = uploaded.read()
    fhash = _file_hash(data)
    st.success(f"Wgrano: **{uploaded.name}** ({len(data):,} B)")
    return data, fhash
