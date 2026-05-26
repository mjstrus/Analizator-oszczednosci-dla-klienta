from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from lxml import etree

from .models import Document

logger = logging.getLogger(__name__)

_JPK_FA_NAMESPACES = (
    "http://crd.gov.pl/wzor/2021/11/29/11089/",    # JPK_FA(3)
    "http://crd.gov.pl/wzor/2022/12/01/11110/",    # JPK_FA(4)
    "http://jpk.mf.gov.pl/wzor/2016/03/09/03095/", # JPK_FA(1)
)

_TYP_FAKTURY_MAP: dict[str, str] = {
    "VAT":     "KP",
    "KOR":     "KD",
    "ZAL":     "KP",
    "ROZ":     "KP",
    "NOTA":    "NT",
    "VAT_RR":  "KP",
    "KOR_ZAL": "KD",
}

_PLATNOSC_GOTÓWKA = {"gotówka", "gotowka", "cash", "1"}
_PLATNOSC_PRZELEW = {"przelew", "transfer", "karta", "kompensata", "2", "3"}


def parse_jpk_fa(xml_content: bytes) -> List[Document]:
    """Parse JPK_FA XML and return extracted Document objects.

    Skips invalid invoices with a warning rather than failing the whole file.
    """
    try:
        root = etree.fromstring(xml_content)
    except etree.XMLSyntaxError as exc:
        logger.error("Malformed JPK_FA XML: %s", exc)
        return []

    ns = _detect_namespace(root)
    documents: List[Document] = []

    faktura_tag = f"{{{ns}}}Faktura" if ns else "Faktura"
    for faktura in root.iter(faktura_tag):
        try:
            doc = _parse_faktura(faktura, ns)
            if doc is not None:
                documents.append(doc)
        except Exception as exc:  # noqa: BLE001
            numer = _find_text(faktura, ns, "NrFaktury") or "?"
            logger.warning("Skipping invoice %s: %s", numer, exc)

    logger.info("Parsed %d documents from JPK_FA", len(documents))
    return documents


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _detect_namespace(root: etree._Element) -> str:
    tag = root.tag
    if tag.startswith("{"):
        return tag[1:].split("}")[0]
    for ns in _JPK_FA_NAMESPACES:
        if any(v == ns for v in (root.nsmap or {}).values()):
            return ns
    return ""


def _find_text(element: etree._Element, ns: str, *path: str) -> Optional[str]:
    """Traverse nested elements by name and return text of the last one."""
    current = element
    for part in path:
        tag = f"{{{ns}}}{part}" if ns else part
        current = current.find(tag)
        if current is None:
            return None
    return current.text.strip() if current is not None and current.text else None


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _parse_decimal(value: Optional[str]) -> Optional[Decimal]:
    if not value:
        return None
    cleaned = value.replace(",", ".").replace("\xa0", "").replace(" ", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _map_typ_faktury(raw: Optional[str]) -> str:
    if not raw:
        return "KP"
    return _TYP_FAKTURY_MAP.get(raw.upper(), "KP")


def _map_typ_platnosci(raw: Optional[str]) -> str:
    if not raw:
        return "przelew"
    normalized = raw.lower().strip()
    if normalized in _PLATNOSC_GOTÓWKA:
        return "gotówka"
    if normalized in _PLATNOSC_PRZELEW:
        return "przelew"
    if "gotów" in normalized or "gotow" in normalized or "cash" in normalized:
        return "gotówka"
    return "przelew"


def _sanitize_nip(raw: Optional[str]) -> str:
    if not raw:
        return ""
    digits = "".join(c for c in raw if c.isdigit())
    return digits if len(digits) >= 9 else raw.strip()


def _document_id(numer: str, data: str, nip: str) -> str:
    payload = f"{numer}|{data}|{nip}"
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def _parse_faktura(faktura: etree._Element, ns: str) -> Optional[Document]:
    numer = _find_text(faktura, ns, "NrFaktury")
    if not numer:
        logger.debug("Invoice element without NrFaktury – skipped")
        return None

    data_str = _find_text(faktura, ns, "DataWystawienia")
    data = _parse_date(data_str)
    if data is None:
        logger.warning("Invoice %s: unparseable date '%s', using sentinel", numer, data_str)
        data = datetime.min

    nip_raw = (
        _find_text(faktura, ns, "Podmiot2", "DaneIdentyfikacyjne", "NIP")
        or _find_text(faktura, ns, "NIPKontrahenta")
        or ""
    )
    nip = _sanitize_nip(nip_raw)

    wartość_raw = (
        _find_text(faktura, ns, "P_15")
        or _find_text(faktura, ns, "WartoscBrutto")
    )
    wartość = _parse_decimal(wartość_raw) or Decimal("0")

    typ = _map_typ_faktury(_find_text(faktura, ns, "TypFaktury"))

    platnosc_raw = (
        _find_text(faktura, ns, "SposobZaplaty")
        or _find_text(faktura, ns, "FormaPlatnosci")
        or _find_text(faktura, ns, "P_18A")
    )
    typ_platnosci = _map_typ_platnosci(platnosc_raw)

    return Document(
        id=_document_id(numer, data_str or "", nip),
        numer=numer,
        data=data,
        nip_dostawcy=nip,
        wartość=wartość,
        typ=typ,
        typ_płatności=typ_platnosci,
    )
