"""Analizator Oszczędności Dokumentów – Streamlit app (Unit 10)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from analyzer.constraints import classify
from analyzer.impact_prognozer import prognosticate_impact
from analyzer.memory import record_decision
from analyzer.models import Document, Variant
from analyzer.optimizer import generate_variants
from analyzer.parser import parse_jpk_fa
from analyzer.ranker import load_decisions_from_engine, rank_variants
from analyzer.rules import RuleEngine
from analyzer.tax_advisor import assess_all
from ui.downloads import render_download_section
from ui.results import render_no_go_section, render_summary_metrics
from ui.sidebar import render_sidebar
from ui.upload import render_upload_section
from ui.variant_card import render_variant_card

logging.basicConfig(level=logging.WARNING)

_STATE_RESULT = "analysis_result"
_STATE_FILE_HASH = "analysis_file_hash"
_STATE_CONFIG_KEY = "analysis_config_key"
_STATE_SELECTED = "selected_variant_id"


# ---------------------------------------------------------------------------
# Analysis pipeline
# ---------------------------------------------------------------------------

def _config_key(cfg: Dict[str, Any]) -> str:
    return f"{cfg['klient_id']}|{cfg['forma']}|{cfg['period']}|{cfg['top_n']}"


def run_analysis(
    xml_bytes: bytes,
    config: Dict[str, Any],
    data_dir=None,
) -> Tuple[List[Variant], List[Document], RuleEngine]:
    """Uruchamia pełny pipeline analizy i zwraca (variants, no_go, engine)."""
    docs = parse_jpk_fa(xml_bytes)
    if not docs:
        return [], [], RuleEngine(config["klient_id"], data_dir=data_dir)

    docs = assess_all(docs, config["forma"])
    engine = RuleEngine(config["klient_id"], data_dir=data_dir)
    result = classify(docs, config["forma"], engine)

    variants_raw = generate_variants(
        result.remaining,
        no_go_count=len(result.no_go),
        target_period=config["period"],
    )
    decisions = load_decisions_from_engine(engine)
    top = rank_variants(variants_raw, decisions=decisions, top_n=config["top_n"])

    for v in top:
        prognosticate_impact(v)

    return top, result.no_go, engine


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Analizator Oszczędności",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    config = render_sidebar()

    st.title("Analizator Oszczędności Dokumentów")

    # ---- Upload ----
    xml_bytes, file_hash = render_upload_section()

    if xml_bytes is None:
        return

    if not config["valid"]:
        st.error("Uzupełnij poprawnie konfigurację w panelu bocznym (ID klienta, okres).")
        return

    # ---- Run analysis (cached in session_state by file hash + config) ----
    cfg_key = _config_key(config)
    need_rerun = (
        st.session_state.get(_STATE_FILE_HASH) != file_hash
        or st.session_state.get(_STATE_CONFIG_KEY) != cfg_key
    )

    if need_rerun:
        with st.spinner("Analizuję dokumenty..."):
            try:
                variants, no_go, engine = run_analysis(xml_bytes, config)
            except Exception as exc:
                st.error(f"Błąd analizy: {exc}")
                return

        st.session_state[_STATE_RESULT] = {
            "variants": variants,
            "no_go": no_go,
            "engine": engine,
            "klient_id": config["klient_id"],
            "period": config["period"],
        }
        st.session_state[_STATE_FILE_HASH] = file_hash
        st.session_state[_STATE_CONFIG_KEY] = cfg_key
        st.session_state[_STATE_SELECTED] = 0

    cached = st.session_state.get(_STATE_RESULT, {})
    variants: List[Variant] = cached.get("variants", [])
    no_go: List[Document] = cached.get("no_go", [])
    engine: Optional[RuleEngine] = cached.get("engine")
    selected_id: int = st.session_state.get(_STATE_SELECTED, 0)

    # ---- Results ----
    st.subheader("2. Wyniki analizy")

    if not variants and not no_go:
        st.warning("Brak dokumentów do analizy w przesłanym pliku.")
        return

    render_summary_metrics(variants, no_go)
    render_no_go_section(no_go)

    if not variants:
        st.info("Brak wariantów oszczędności – wszystkie dokumenty są wykluczone.")
        return

    st.markdown("---")
    st.markdown("#### Warianty oszczędności (TOP)")

    for idx, variant in enumerate(variants, 1):
        clicked = render_variant_card(variant, idx, selected_id)
        if clicked:
            st.session_state[_STATE_SELECTED] = variant.id
            if engine is not None:
                record_decision(engine, variant)
            st.rerun()

    # ---- Downloads ----
    if selected_id > 0:
        st.markdown("---")
        render_download_section(
            variants=variants,
            klient_id=config["klient_id"],
            no_go=no_go,
            period=config["period"],
        )


if __name__ == "__main__":
    main()
