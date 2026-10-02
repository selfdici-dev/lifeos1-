"""Une donnée de marché porte toujours sa source et son heure. Les prix sont indicatifs :
le prix d'exécution se lit chez le courtier."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional

from poste.regles import FUSEAU

ROUGE_ANSI, ORANGE_ANSI, VERT_ANSI, FIN_ANSI = "\x1b[31m", "\x1b[33m", "\x1b[32m", "\x1b[0m"


class Nature(str, Enum):
    TEMPS_REEL = "temps_reel"   # cours, variation de séance
    QUOTIDIEN = "quotidien"     # clôtures, taux publiés une fois par jour
    CALENDRIER = "calendrier"   # dates d'annonces


class Fraicheur(str, Enum):
    VERT = "VERT"
    ORANGE = "ORANGE"
    ROUGE = "ROUGE"


# (âge maximal pour vert, âge maximal pour orange) ; au-delà : rouge = périmé
SEUILS = {
    Nature.TEMPS_REEL: (timedelta(minutes=5), timedelta(minutes=30)),
    Nature.QUOTIDIEN: (timedelta(days=4), timedelta(days=6)),  # couvre week-end et jour férié
    Nature.CALENDRIER: (timedelta(hours=24), timedelta(hours=72)),
}


@dataclass(frozen=True)
class Donnee:
    nom: str
    valeur: Decimal
    horodatage: datetime
    source: str
    nature: Nature

    def __post_init__(self):
        if self.horodatage.tzinfo is None or self.horodatage.utcoffset() is None:
            raise ValueError("horodatage sans fuseau horaire")


@dataclass(frozen=True)
class Historique:
    source: str
    barres: list[tuple[date, Decimal]]  # du plus ancien au plus récent


def fraicheur(d: Optional[Donnee], maintenant: datetime) -> Fraicheur:
    if d is None:
        return Fraicheur.ROUGE
    vert, orange = SEUILS[d.nature]
    age = maintenant - d.horodatage
    if age <= vert:
        return Fraicheur.VERT
    if age <= orange:
        return Fraicheur.ORANGE
    return Fraicheur.ROUGE


def badge(nom: str, d: Optional[Donnee], maintenant: datetime) -> str:
    f = fraicheur(d, maintenant)
    if d is None:
        return f"{ROUGE_ANSI}PÉRIMÉ{FIN_ANSI} {nom} : aucune source disponible"
    heure = d.horodatage.astimezone(FUSEAU).strftime("%d/%m %H:%M")
    couleur = {Fraicheur.VERT: VERT_ANSI, Fraicheur.ORANGE: ORANGE_ANSI, Fraicheur.ROUGE: ROUGE_ANSI}[f]
    etat = "PÉRIMÉ" if f is Fraicheur.ROUGE else f.value
    return f"{couleur}{etat}{FIN_ANSI} {nom} = {d.valeur} · {d.source} · {heure} (Paris)"
