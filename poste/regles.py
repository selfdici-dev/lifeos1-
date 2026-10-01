"""Règles bloquantes codées en dur : elles ne se règlent ni dans plan.json ni dans l'interface."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel

FUSEAU = ZoneInfo("Europe/Paris")

# Test de feu vert, à passer avant chaque tranche d'achat.
TAUX_US10A_MAX_PCT = Decimal("5.40")
SP500_BAISSE_MAX_PCT = Decimal("1.5")

# Pas d'achat dans les 24 h qui précèdent un événement d'impact fort.
FENETRE_EVENEMENT = timedelta(hours=24)

# Avertissement quand l'exposition corrélée dépasse ce pourcentage du capital.
SEUIL_CORRELE_PCT = Decimal("60")


class Evenement(BaseModel):
    nom: str
    debut: AwareDatetime  # une date sans fuseau est refusée
    impact: Literal["fort", "moyen", "faible"]


def raisons_feu_vert(taux_us10a_pct: Decimal, sp500_variation_seance_pct: Decimal) -> list[str]:
    raisons = []
    if taux_us10a_pct > TAUX_US10A_MAX_PCT:
        raisons.append(f"Test de feu vert rouge : taux US 10 ans {taux_us10a_pct} % > {TAUX_US10A_MAX_PCT} %.")
    if sp500_variation_seance_pct < -SP500_BAISSE_MAX_PCT:
        raisons.append(f"Test de feu vert rouge : S&P 500 à {sp500_variation_seance_pct} % sur la séance"
                       f" (baisse de plus de {SP500_BAISSE_MAX_PCT} %).")
    return raisons


def evenements_bloquants(maintenant: datetime, evenements: list[Evenement]) -> list[Evenement]:
    """Événements d'impact fort qui commencent dans les 24 h à venir (comparaison en temps absolu)."""
    if maintenant.tzinfo is None or maintenant.utcoffset() is None:
        raise ValueError("« maintenant » doit avoir un fuseau horaire")
    # Tout en UTC : avec un même fuseau, Python calcule en heure murale et oublie l'heure
    # gagnée ou perdue lors d'un changement d'heure.
    debut = maintenant.astimezone(timezone.utc)
    fin = debut + FENETRE_EVENEMENT
    return [e for e in evenements
            if e.impact == "fort" and debut <= e.debut.astimezone(timezone.utc) <= fin]


def charger_calendrier(chemin) -> list[Evenement] | None:
    """None si le fichier n'existe pas : on ne sait pas, ce qui n'est pas la même chose que « aucun événement »."""
    chemin = Path(chemin)
    if not chemin.exists():
        return None
    return [Evenement.model_validate(e) for e in json.loads(chemin.read_text(encoding="utf-8"))]
