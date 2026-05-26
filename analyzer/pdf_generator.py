from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from .models import Variant

logger = logging.getLogger(__name__)

_FONT_SEARCH = [
    Path(__file__).parent.parent / "data" / "fonts",
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/dejavu"),
]
_FONT_NAME = "DejaVuSans"
_FONT_BOLD = "DejaVuSans-Bold"

_BLUE = colors.HexColor("#2c3e50")
_LIGHT_GRAY = colors.HexColor("#f2f3f4")
_MID_GRAY = colors.HexColor("#bdc3c7")
_RISK_COLOR = {
    "LOW": colors.HexColor("#27ae60"),
    "MED": colors.HexColor("#e67e22"),
    "HIGH": colors.HexColor("#e74c3c"),
}
_RISK_LABEL = {"LOW": "Niskie", "MED": "Średnie", "HIGH": "Wysokie"}


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

def _find_font(filename: str) -> Optional[Path]:
    for d in _FONT_SEARCH:
        p = d / filename
        if p.exists():
            return p
    return None


def _register_fonts() -> Tuple[str, str]:
    """Returns (regular, bold) font names after attempting TTF registration."""
    reg_path = _find_font("DejaVuSans.ttf")
    bold_path = _find_font("DejaVuSans-Bold.ttf")
    if reg_path and bold_path:
        try:
            pdfmetrics.registerFont(TTFont(_FONT_NAME, str(reg_path)))
            pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(bold_path)))
            return _FONT_NAME, _FONT_BOLD
        except Exception as exc:  # pragma: no cover
            logger.warning("Cannot register DejaVuSans: %s", exc)
    logger.warning("DejaVuSans not found – falling back to Helvetica (no Polish diacritics)")
    return "Helvetica", "Helvetica-Bold"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_pln(amount: Decimal) -> str:
    return f"{float(amount):,.2f} zł".replace(",", " ")


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y")


def _action_summary(v: Variant) -> str:
    parts = []
    if v.dokumenty_do_pomijania:
        parts.append(f"Pomiń {len(v.dokumenty_do_pomijania)}")
    if v.grupy_do_zbiorczenia:
        n = sum(len(docs) for _, docs in v.grupy_do_zbiorczenia)
        parts.append(f"Zbiorczy {n}")
    if v.dokumenty_do_przesunięcia:
        parts.append(f"Przesuń {len(v.dokumenty_do_przesunięcia)}")
    return ", ".join(parts) if parts else "–"


# ---------------------------------------------------------------------------
# Style factory
# ---------------------------------------------------------------------------

def _build_styles(font: str, bold: str) -> Dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "title", fontName=bold, fontSize=18, textColor=_BLUE, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontName=font, fontSize=10, textColor=colors.gray, spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "h2", fontName=bold, fontSize=13, textColor=_BLUE, spaceBefore=16, spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "h3", fontName=bold, fontSize=11, textColor=_BLUE, spaceBefore=10, spaceAfter=4,
        ),
        "body": ParagraphStyle("body", fontName=font, fontSize=9, spaceAfter=3),
        "bold": ParagraphStyle("bold_body", fontName=bold, fontSize=9, spaceAfter=3),
        "small": ParagraphStyle(
            "small", fontName=font, fontSize=8, textColor=colors.gray, spaceAfter=2,
        ),
        "impact": ParagraphStyle(
            "impact", fontName=font, fontSize=9,
            textColor=colors.HexColor("#c0392b"), spaceAfter=4,
        ),
    }


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _summary_table(variants: List[Variant], st: Dict[str, ParagraphStyle]) -> Table:
    header = ["#", "Oszczędność", "Ryzyko", "Zgodność", "Score", "Akcje"]
    rows = [header]
    for v in variants:
        risk_label = _RISK_LABEL.get(v.risk_level, v.risk_level)
        rows.append([
            str(v.id),
            _fmt_pln(v.oszczędność),
            risk_label,
            f"{v.compatibility_score * 100:.0f}%",
            f"{v.score:.3f}",
            _action_summary(v),
        ])

    col_widths = [1 * cm, 3.2 * cm, 2 * cm, 2 * cm, 1.8 * cm, None]
    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), st["bold"].fontName),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 1), (-1, -1), st["body"].fontName),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT_GRAY]),
        ("GRID", (0, 0), (-1, -1), 0.5, _MID_GRAY),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("ALIGN", (5, 1), (5, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ])
    # Color-code risk column
    for row_idx, v in enumerate(variants, 1):
        risk_color = _RISK_COLOR.get(v.risk_level, colors.gray)
        style.add("TEXTCOLOR", (2, row_idx), (2, row_idx), risk_color)
        style.add("FONTNAME", (2, row_idx), (2, row_idx), st["bold"].fontName)
    tbl.setStyle(style)
    return tbl


def _variant_detail(v: Variant, st: Dict[str, ParagraphStyle]) -> List:
    risk_label = _RISK_LABEL.get(v.risk_level, v.risk_level)
    risk_col = _RISK_COLOR.get(v.risk_level, colors.gray)
    risk_hex = risk_col.hexval() if hasattr(risk_col, "hexval") else "#888888"

    story = [
        HRFlowable(width="100%", thickness=1, color=_MID_GRAY),
        Paragraph(
            f"Wariant {v.id} &nbsp;·&nbsp; Oszczędność: <b>{_fmt_pln(v.oszczędność)}</b>"
            f" &nbsp;·&nbsp; Ryzyko: <font color='{risk_hex}'><b>{risk_label}</b></font>"
            f" &nbsp;·&nbsp; Score: {v.score:.3f}",
            st["h3"],
        ),
    ]

    if v.dokumenty_do_pomijania:
        story.append(Paragraph(f"<b>Dokumenty do pominięcia ({len(v.dokumenty_do_pomijania)}):</b>", st["bold"]))
        for doc in v.dokumenty_do_pomijania:
            story.append(Paragraph(
                f"&nbsp;&nbsp;{doc.numer} | NIP: {doc.nip_dostawcy}"
                f" | {_fmt_pln(doc.wartość)} | {doc.typ}",
                st["small"],
            ))

    if v.grupy_do_zbiorczenia:
        story.append(Paragraph(f"<b>Grupy do zbiorczenia ({len(v.grupy_do_zbiorczenia)}):</b>", st["bold"]))
        for dostawca, docs in v.grupy_do_zbiorczenia:
            total = sum(d.wartość for d in docs)
            story.append(Paragraph(
                f"&nbsp;&nbsp;NIP {dostawca}: {len(docs)} faktur"
                f" → 1 zbiorczy (łącznie {_fmt_pln(total)})",
                st["small"],
            ))

    if v.dokumenty_do_przesunięcia:
        story.append(Paragraph(f"<b>Przesunięcia ({len(v.dokumenty_do_przesunięcia)}):</b>", st["bold"]))
        for doc, target_month in v.dokumenty_do_przesunięcia:
            story.append(Paragraph(
                f"&nbsp;&nbsp;{doc.numer} → {target_month} | {_fmt_pln(doc.wartość)}",
                st["small"],
            ))

    if v.impact_message:
        story.append(Paragraph(f"⚠ Prognoza: {v.impact_message}", st["impact"]))

    story.append(Spacer(1, 0.3 * cm))
    return story


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_report(
    variants: List[Variant],
    klient_id: str,
    output_path: Path,
    period: str = "",
    title: str = "Analiza Oszczędności Dokumentów",
) -> Path:
    """Generuje PDF raport z TOP wariantami oszczędności.

    Args:
        variants: Lista wariantów (już posortowana, typowo top-5 z rank_variants).
        klient_id: Identyfikator klienta (wyświetlany w nagłówku).
        output_path: Ścieżka do zapisu pliku PDF.
        period: Okres analizy, np. "2024-11" (opcjonalnie).
        title: Tytuł raportu.

    Returns:
        Ścieżka do wygenerowanego pliku.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    font, bold = _register_fonts()
    st = _build_styles(font, bold)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=title,
        author="Abacus Centrum Księgowe",
    )

    generated_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    period_label = f" | Okres: {period}" if period else ""
    story = [
        Paragraph(title, st["title"]),
        Paragraph(
            f"Klient: {klient_id}{period_label} | Wygenerowano: {generated_at}",
            st["subtitle"],
        ),
    ]

    if not variants:
        story.append(Paragraph("Brak wariantów oszczędności do wyświetlenia.", st["body"]))
        doc.build(story)
        logger.info("PDF report (empty) written to %s", output_path)
        return output_path

    best = variants[0]
    story += [
        Paragraph("Podsumowanie", st["h2"]),
        Paragraph(
            f"Najlepsza oszczędność: <b>{_fmt_pln(best.oszczędność)}</b>"
            f" (wariant {best.id}, ryzyko: {_RISK_LABEL.get(best.risk_level, best.risk_level)})",
            st["body"],
        ),
        Paragraph(f"Liczba analizowanych wariantów: {len(variants)}", st["body"]),
        Spacer(1, 0.4 * cm),
        Paragraph("Zestawienie wariantów", st["h2"]),
        _summary_table(variants, st),
        Paragraph("Szczegóły wariantów", st["h2"]),
    ]

    for v in variants:
        story.extend(_variant_detail(v, st))

    doc.build(story)
    logger.info("PDF report written to %s (%d variants)", output_path, len(variants))
    return output_path
