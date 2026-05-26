from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, Optional

from .models import Variant
from .optimizer import Pricing

logger = logging.getLogger(__name__)

_MONTH_NAMES: Dict[str, str] = {
    "01": "Styczeń", "02": "Luty", "03": "Marzec", "04": "Kwiecień",
    "05": "Maj", "06": "Czerwiec", "07": "Lipiec", "08": "Sierpień",
    "09": "Wrzesień", "10": "Październik", "11": "Listopad", "12": "Grudzień",
}


def _month_label(target_month: str) -> str:
    parts = target_month.split("-")
    if len(parts) == 2:
        return _MONTH_NAMES.get(parts[1], target_month)
    return target_month


def prognosticate_impact(
    variant: Variant,
    docs_per_month: Optional[Dict[str, int]] = None,
    pricing: Optional[Pricing] = None,
) -> float:
    """Prognozuje wpływ przesunięć na docelowe miesiące.

    Ustawia variant.impact_message i zwraca impact_score:
      0.0 – brak przesunięć lub brak zmiany taryfy
      >0  – wzrost kosztów w którymś z docelowych miesięcy (max 1.0)

    Args:
        variant: Wariant z dokumenty_do_przesunięcia.
        docs_per_month: Bieżąca liczba dokumentów per miesiąc {"YYYY-MM": count}.
                        Brakujące miesiące przyjmuje jako 0.
        pricing: Cennik (domyślnie Pricing.default()).
    """
    if not variant.dokumenty_do_przesunięcia:
        variant.impact_message = None
        return 0.0

    pricing = pricing or Pricing.default()
    docs_per_month = docs_per_month or {}

    shifts_by_month: Dict[str, int] = defaultdict(int)
    for _doc, target_month in variant.dokumenty_do_przesunięcia:
        shifts_by_month[target_month] += 1

    messages = []
    max_price = pricing.tiers[-1].price
    total_impact = 0.0

    for target_month in sorted(shifts_by_month):
        shift_count = shifts_by_month[target_month]
        current_count = docs_per_month.get(target_month, 0)
        new_count = current_count + shift_count

        current_price = pricing.price_for(current_count)
        new_price = pricing.price_for(new_count)
        label = _month_label(target_month)

        if new_price > current_price:
            tier_diff = int(new_price - current_price)
            messages.append(
                f"{label} będzie miał {new_count} dokumentów "
                f"(+{shift_count}) – zmiana taryfy +{tier_diff} zł"
            )
            total_impact += float(new_price - current_price) / float(max_price)
        else:
            messages.append(
                f"{label} będzie miał {new_count} dokumentów (+{shift_count})"
            )

    variant.impact_message = "; ".join(messages)
    impact_score = min(1.0, total_impact)

    logger.info(
        "Impact prognozer: variant %d, shifts=%d months, score=%.3f",
        variant.id, len(shifts_by_month), impact_score,
    )
    return impact_score
