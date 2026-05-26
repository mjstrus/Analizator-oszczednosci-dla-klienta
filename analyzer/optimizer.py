from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from .models import Document, Variant

logger = logging.getLogger(__name__)

# Porządek do porównań MAX
RISK_ORDER: Dict[Optional[str], int] = {None: 0, "LOW": 0, "MED": 1, "HIGH": 2}


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PriceTier:
    min_docs: int   # inclusive
    max_docs: int   # inclusive
    price: Decimal


@dataclass
class Pricing:
    """Cennik widełkowy księgowania."""

    tiers: List[PriceTier]

    @classmethod
    def default(cls) -> "Pricing":
        """Domyślny cennik (config.json z planu)."""
        return cls(tiers=[
            PriceTier(0, 50, Decimal("100")),
            PriceTier(51, 100, Decimal("180")),
            PriceTier(101, 200, Decimal("280")),
            PriceTier(201, 500, Decimal("450")),
        ])

    def price_for(self, count: int) -> Decimal:
        """Cena dla danej liczby dokumentów (cap na najwyższy próg)."""
        if count < 0:
            return self.tiers[0].price
        for tier in self.tiers:
            if tier.min_docs <= count <= tier.max_docs:
                return tier.price
        return self.tiers[-1].price

    def lower_tier_max(self, count: int) -> Optional[int]:
        """Max_docs progu o jeden niższego cenowo (lub None gdy już najniższy)."""
        current_price = self.price_for(count)
        lower = [t for t in self.tiers if t.price < current_price]
        if not lower:
            return None
        return max(lower, key=lambda t: t.price).max_docs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _risk_max(docs: Iterable[Document]) -> str:
    """MAX po risk_levels dotkniętych dokumentów. Default LOW (gdy brak ocen)."""
    levels = [d.risk_level for d in docs if d.risk_level]
    if not levels:
        return "LOW"
    return max(levels, key=lambda lvl: RISK_ORDER[lvl])


def _group_by_supplier(docs: List[Document]) -> Dict[Tuple[str, str], List[Document]]:
    """Grupuje dokumenty po (nip_dostawcy, typ)."""
    groups: Dict[Tuple[str, str], List[Document]] = {}
    for doc in docs:
        if not doc.nip_dostawcy:
            continue
        key = (doc.nip_dostawcy, doc.typ)
        groups.setdefault(key, []).append(doc)
    return groups


def _docs_removed(
    skip: List[Document],
    consolidate: List[Tuple[str, List[Document]]],
    shift: List[Tuple[Document, str]],
) -> int:
    """Łączna redukcja liczby dokumentów przez wariant.

    Konsolidacja K dokumentów daje redukcję o (K-1) (powstaje 1 faktura zbiorcza).
    """
    return (
        len(skip)
        + sum(len(group) - 1 for _, group in consolidate)
        + len(shift)
    )


VariantSignature = Tuple[FrozenSet[str], FrozenSet[Tuple[str, ...]], FrozenSet[Tuple[str, str]]]


def _signature(
    skip: List[Document],
    consolidate: List[Tuple[str, List[Document]]],
    shift: List[Tuple[Document, str]],
) -> VariantSignature:
    """Sygnatura wariantu do deduplikacji (które dokumenty + jakie akcje)."""
    skip_ids = frozenset(d.id for d in skip)
    consol_sig = frozenset(
        (nip,) + tuple(sorted(d.id for d in group))
        for nip, group in consolidate
    )
    shift_pairs = frozenset((d.id, m) for d, m in shift)
    return (skip_ids, consol_sig, shift_pairs)


def _build_variant(
    skip: List[Document],
    consolidate: List[Tuple[str, List[Document]]],
    shift: List[Tuple[Document, str]],
    no_go_count: int,
    remaining_count: int,
    pricing: Pricing,
) -> Optional[Variant]:
    """Buduje wariant; zwraca None gdy savings ≤ 0 lub dokumenty się nakładają."""
    # Defensywny check overlap (dokument w wielu akcjach jest nielegalny)
    touched_ids: List[str] = [d.id for d in skip]
    for _, group in consolidate:
        touched_ids.extend(d.id for d in group)
    touched_ids.extend(d.id for d, _ in shift)
    if len(touched_ids) != len(set(touched_ids)):
        return None

    removed = _docs_removed(skip, consolidate, shift)
    total_before = no_go_count + remaining_count
    total_after = total_before - removed
    if total_after < 0:
        return None

    savings = pricing.price_for(total_before) - pricing.price_for(total_after)
    if savings <= 0:
        return None

    touched: List[Document] = list(skip)
    for _, group in consolidate:
        touched.extend(group)
    touched.extend(d for d, _ in shift)

    return Variant(
        id=0,  # nadawany później
        oszczędność=savings,
        dokumenty_do_pomijania=skip,
        grupy_do_zbiorczenia=consolidate,
        dokumenty_do_przesunięcia=shift,
        risk_level=_risk_max(touched),
    )


# ---------------------------------------------------------------------------
# Generation strategies
# ---------------------------------------------------------------------------

def _skip_variants(
    remaining: List[Document],
    no_go_count: int,
    pricing: Pricing,
) -> List[Variant]:
    """Warianty pomijania – 2 sortowania × kilka rozmiarów."""
    if not remaining:
        return []
    total = no_go_count + len(remaining)
    target_max = pricing.lower_tier_max(total)
    if target_max is None:
        return []
    min_skip = max(1, total - target_max)
    if min_skip > len(remaining):
        return []

    by_safety = sorted(remaining, key=lambda d: (RISK_ORDER[d.risk_level], d.wartość))
    by_value = sorted(remaining, key=lambda d: d.wartość)

    variants: List[Variant] = []
    max_n = min(min_skip + 5, len(remaining))
    for n in range(min_skip, max_n + 1):
        for ordering in (by_safety, by_value):
            subset = ordering[:n]
            v = _build_variant(subset, [], [], no_go_count, len(remaining), pricing)
            if v is not None:
                variants.append(v)
    return variants


def _consolidate_variants(
    supplier_groups: Dict[Tuple[str, str], List[Document]],
    no_go_count: int,
    remaining_count: int,
    pricing: Pricing,
) -> List[Variant]:
    """Wariant per dostawca z ≥2 dokumentami + wariant 'wszystkie konsolidacje'."""
    eligible: List[Tuple[str, List[Document]]] = [
        (nip, group)
        for (nip, _typ), group in supplier_groups.items()
        if len(group) >= 2
    ]
    variants: List[Variant] = []

    for nip, group in eligible:
        v = _build_variant([], [(nip, group)], [], no_go_count, remaining_count, pricing)
        if v is not None:
            variants.append(v)

    if len(eligible) >= 2:
        v = _build_variant([], eligible, [], no_go_count, remaining_count, pricing)
        if v is not None:
            variants.append(v)

    return variants


def _shift_variants(
    remaining: List[Document],
    no_go_count: int,
    pricing: Pricing,
    target_period: str,
) -> List[Variant]:
    """Warianty przesunięcia – LOW/małe first."""
    if not remaining:
        return []
    total = no_go_count + len(remaining)
    target_max = pricing.lower_tier_max(total)
    if target_max is None:
        return []
    min_shift = max(1, total - target_max)
    if min_shift > len(remaining):
        return []

    by_safety = sorted(remaining, key=lambda d: (RISK_ORDER[d.risk_level], d.wartość))
    variants: List[Variant] = []
    max_n = min(min_shift + 3, len(remaining))
    for n in range(min_shift, max_n + 1):
        shifts = [(d, target_period) for d in by_safety[:n]]
        v = _build_variant([], [], shifts, no_go_count, len(remaining), pricing)
        if v is not None:
            variants.append(v)
    return variants


def _combined_variants(
    remaining: List[Document],
    supplier_groups: Dict[Tuple[str, str], List[Document]],
    no_go_count: int,
    pricing: Pricing,
    target_period: Optional[str],
) -> List[Variant]:
    """Kombinacje akcji: skip+consolidate, skip+shift, consolidate+shift, all-three."""
    eligible_groups = [
        (nip, group)
        for (nip, _typ), group in supplier_groups.items()
        if len(group) >= 2
    ]
    eligible_groups.sort(key=lambda x: -len(x[1]))  # największe grupy first
    top_groups = eligible_groups[:3]

    by_safety = sorted(remaining, key=lambda d: (RISK_ORDER[d.risk_level], d.wartość))
    variants: List[Variant] = []

    # skip + consolidate
    for n_skip in (1, 2, 3, 5):
        if n_skip > len(remaining):
            continue
        skip = by_safety[:n_skip]
        skip_ids: Set[str] = {d.id for d in skip}
        for nip, group in top_groups:
            group_filtered = [d for d in group if d.id not in skip_ids]
            if len(group_filtered) < 2:
                continue
            v = _build_variant(skip, [(nip, group_filtered)], [], no_go_count, len(remaining), pricing)
            if v is not None:
                variants.append(v)

    # skip + shift
    if target_period:
        for n_skip in (1, 2, 3):
            for n_shift in (1, 2, 3):
                if n_skip + n_shift > len(remaining):
                    continue
                skip = by_safety[:n_skip]
                shift_docs = by_safety[n_skip:n_skip + n_shift]
                shifts = [(d, target_period) for d in shift_docs]
                v = _build_variant(skip, [], shifts, no_go_count, len(remaining), pricing)
                if v is not None:
                    variants.append(v)

    # consolidate + shift
    if target_period:
        for nip, group in top_groups:
            group_ids = {d.id for d in group}
            non_group = [d for d in by_safety if d.id not in group_ids]
            for n_shift in (1, 2, 3):
                if n_shift > len(non_group):
                    continue
                shifts = [(d, target_period) for d in non_group[:n_shift]]
                v = _build_variant([], [(nip, group)], shifts, no_go_count, len(remaining), pricing)
                if v is not None:
                    variants.append(v)

    # all-three (skip + consolidate + shift) – jeden ostrożny wariant
    if target_period and top_groups:
        nip, group = top_groups[0]
        group_ids = {d.id for d in group}
        non_group = [d for d in by_safety if d.id not in group_ids]
        if len(non_group) >= 2:
            skip = non_group[:1]
            shifts = [(non_group[1], target_period)]
            v = _build_variant(skip, [(nip, group)], shifts, no_go_count, len(remaining), pricing)
            if v is not None:
                variants.append(v)

    return variants


def _deduplicate(variants: List[Variant]) -> List[Variant]:
    """Usuwa duplikaty po sygnaturze (te same dokumenty w tych samych akcjach)."""
    seen: Set[VariantSignature] = set()
    out: List[Variant] = []
    for v in variants:
        sig = _signature(
            v.dokumenty_do_pomijania,
            v.grupy_do_zbiorczenia,
            v.dokumenty_do_przesunięcia,
        )
        if sig in seen:
            continue
        seen.add(sig)
        out.append(v)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_variants(
    remaining: List[Document],
    no_go_count: int = 0,
    pricing: Optional[Pricing] = None,
    target_period: Optional[str] = None,
    max_variants: int = 100,
) -> List[Variant]:
    """Generuje warianty optymalizacyjne.

    Args:
        remaining: Dokumenty do optymalizacji (po Constraints).
        no_go_count: Liczba dokumentów NO-GO (wlicza się do total).
        pricing: Cennik widełkowy (default Pricing.default()).
        target_period: Miesiąc docelowy dla przesunięć (np. "2025-12"); brak → bez przesunięć.
        max_variants: Limit wyników (sortowane po oszczędności DESC).

    Returns:
        Lista wariantów z `oszczędność > 0`, deduplikowanych, z nadanym `id` (1..N).
    """
    pricing = pricing or Pricing.default()
    total = no_go_count + len(remaining)
    if pricing.lower_tier_max(total) is None:
        logger.info("Total %d na najniższym progu – brak optymalizacji", total)
        return []

    candidates: List[Variant] = []
    candidates.extend(_skip_variants(remaining, no_go_count, pricing))

    supplier_groups = _group_by_supplier(remaining)
    candidates.extend(_consolidate_variants(supplier_groups, no_go_count, len(remaining), pricing))

    if target_period:
        candidates.extend(_shift_variants(remaining, no_go_count, pricing, target_period))

    candidates.extend(_combined_variants(remaining, supplier_groups, no_go_count, pricing, target_period))

    # Defense in depth (build już filtruje, ale na wszelki wypadek)
    candidates = [v for v in candidates if v.oszczędność > 0]
    candidates = _deduplicate(candidates)

    # Sort: największa oszczędność first, przy remisie LOW risk first
    candidates.sort(key=lambda v: (-v.oszczędność, RISK_ORDER[v.risk_level]))
    candidates = candidates[:max_variants]

    for i, v in enumerate(candidates, start=1):
        v.id = i

    logger.info(
        "Wygenerowano %d wariantów (no_go=%d, remaining=%d, target=%s)",
        len(candidates), no_go_count, len(remaining), target_period,
    )
    return candidates
