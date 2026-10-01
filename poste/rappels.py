"""Rappels push gratuits et optionnels via ntfy.sh.

Active-les en mettant NTFY_TOPIC dans .env (un nom long et imprévisible : n'importe qui connaissant
le nom peut lire les messages). Installe l'appli ntfy sur ton téléphone et abonne-toi à ce nom.
Les horaires par défaut sont provisoires (l'annexe B n'était pas fournie) : modifie-les dans
reglages.json, clé « rappels ».
"""
import logging
from datetime import date, datetime, time, timedelta
from typing import Callable, Optional

from pydantic import BaseModel, Field

from poste.regles import FUSEAU

log = logging.getLogger("poste.rappels")


class Rappel(BaseModel):
    jours: tuple[int, ...] = Field(description="0 = lundi … 6 = dimanche")
    heure: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    message: str


RAPPELS_DEFAUT = [
    Rappel(jours=(0, 1, 2, 3, 4), heure="15:15",
           message="La séance US ouvre à 15:30 (Paris) : test de feu vert avant tout achat."),
    Rappel(jours=(0, 1, 2, 3, 4), heure="21:45",
           message="Vérifie que chaque position a son stop posé chez le courtier."),
    Rappel(jours=(4,), heure="22:05", message="Bilan hebdomadaire : python -m poste bilan"),
]


def prochains_rappels(maintenant: datetime, rappels: list[Rappel], nombre: int = 5) -> list[tuple[datetime, Rappel]]:
    """Prochaines échéances, en heure de Paris (changements d'heure compris)."""
    maintenant = maintenant.astimezone(FUSEAU)
    out = []
    for k in range(0, 15):
        jour: date = maintenant.date() + timedelta(days=k)
        for r in rappels:
            if jour.weekday() in r.jours:
                h, m = map(int, r.heure.split(":"))
                quand = datetime.combine(jour, time(h, m), FUSEAU)
                if quand > maintenant:
                    out.append((quand, r))
    out.sort(key=lambda x: x[0])
    return out[:nombre]


def _post(url: str, donnees: bytes) -> int:
    import requests
    return requests.post(url, data=donnees, timeout=10).status_code


def envoyer_ntfy(sujet: Optional[str], message: str, transport: Callable = _post) -> bool:
    if not sujet:
        return False
    try:
        statut = transport(f"https://ntfy.sh/{sujet}", message.encode())
    except Exception as e:  # noqa: BLE001 - jamais le sujet ni l'URL dans les logs
        log.warning("ntfy : erreur réseau (%s)", type(e).__name__)
        return False
    return statut in (200, None)
