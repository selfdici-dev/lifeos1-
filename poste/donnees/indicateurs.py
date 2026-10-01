"""Indicateurs calculés sans fuite du futur : un signal à la date T ne lit que les clôtures
strictement antérieures à T (la séance T n'est pas terminée quand on décide)."""
from datetime import date
from decimal import Decimal
from typing import Optional


def moyenne_mobile(barres: list[tuple[date, Decimal]], avant: date, n: int = 50) -> Optional[Decimal]:
    passe = [c for d, c in sorted(barres) if d < avant]
    if len(passe) < n:
        return None
    return sum(passe[-n:], Decimal("0")) / n
