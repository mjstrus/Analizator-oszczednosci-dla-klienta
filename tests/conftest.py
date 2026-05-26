"""Shared pytest fixtures for all test modules."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List

import pytest

from analyzer.models import Document, Variant

_FIXTURES = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Raw file bytes
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sample_xml_bytes() -> bytes:
    return (_FIXTURES / "sample_jpk_fa.xml").read_bytes()


# ---------------------------------------------------------------------------
# Document factories
# ---------------------------------------------------------------------------

def make_doc(
    id_: str,
    wartość: float = 30.0,
    typ: str = "KP",
    typ_płatności: str = "gotówka",
    nip: str = "1234567890",
    risk: str = "LOW",
) -> Document:
    return Document(
        id=id_,
        numer=f"FV/{id_}",
        data=datetime(2024, 11, 15),
        nip_dostawcy=nip,
        wartość=Decimal(str(wartość)),
        typ=typ,
        typ_płatności=typ_płatności,
        risk_level=risk,
    )


@pytest.fixture
def doc_factory():
    """Returns the make_doc helper for use in tests."""
    return make_doc


# ---------------------------------------------------------------------------
# Document sets that cross the 50→51 tier boundary
# (52 LOW-risk docs → skip 2 → 50 docs → savings = 180-100 = 80 PLN)
# ---------------------------------------------------------------------------

@pytest.fixture
def docs_crossing_tier() -> List[Document]:
    """52 LOW-risk KP docs (gotówka, 30 PLN each) – crosses the 50/51 boundary."""
    return [
        make_doc(f"ct{i:03d}", wartość=30.0, typ="KP", typ_płatności="gotówka")
        for i in range(52)
    ]


@pytest.fixture
def docs_with_consolidation() -> List[Document]:
    """10 docs for 2 suppliers (5 each, same NIP), useful for consolidation variants."""
    docs = []
    for i in range(5):
        docs.append(make_doc(f"nip_a_{i}", nip="NIP_AAA", typ="KP"))
        docs.append(make_doc(f"nip_b_{i}", nip="NIP_BBB", typ="KP"))
    return docs


# ---------------------------------------------------------------------------
# Variant factory
# ---------------------------------------------------------------------------

def make_variant(
    id_: int = 1,
    savings: float = 80.0,
    risk: str = "LOW",
    pomijanie: List[Document] | None = None,
    zbiorczenie=None,
    przesunięcia=None,
    impact: str | None = None,
) -> Variant:
    v = Variant(
        id=id_,
        oszczędność=Decimal(str(savings)),
        dokumenty_do_pomijania=pomijanie or [],
        grupy_do_zbiorczenia=zbiorczenie or [],
        dokumenty_do_przesunięcia=przesunięcia or [],
        risk_level=risk,
        compatibility_score=0.5,
        score=0.7,
        impact_message=impact,
    )
    return v


@pytest.fixture
def variant_factory():
    return make_variant


@pytest.fixture
def ranked_variants(docs_crossing_tier) -> List[Variant]:
    """Pre-ranked variants generated from docs_crossing_tier (KPIR, no history)."""
    from analyzer.optimizer import generate_variants
    from analyzer.ranker import rank_variants

    raw = generate_variants(docs_crossing_tier, no_go_count=0)
    return rank_variants(raw, decisions=[], top_n=5)
