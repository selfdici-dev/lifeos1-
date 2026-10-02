"""Limiteur de requêtes par fournisseur, compteur journalier persistant, disjoncteur."""
import json
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from poste.regles import FUSEAU

Horloge = Callable[[], datetime]


def maintenant_paris() -> datetime:
    return datetime.now(FUSEAU)


class CompteurPersistant:
    """Requêtes par fournisseur et par jour (date de Paris), conservées sur disque."""

    def __init__(self, chemin: Path):
        self.chemin = Path(chemin)

    def _lire(self) -> dict:
        if not self.chemin.exists():
            return {}
        try:
            return json.loads(self.chemin.read_text(encoding="utf-8"))
        except ValueError:
            return {}

    def valeur(self, nom: str, jour: str) -> int:
        return self._lire().get(nom, {}).get(jour, 0)

    def incrementer(self, nom: str, jour: str) -> None:
        d = self._lire()
        d[nom] = {jour: d.get(nom, {}).get(jour, 0) + 1}  # on ne garde que le jour courant
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.chemin.write_text(json.dumps(d), encoding="utf-8")


class Limiteur:
    def __init__(self, nom: str, par_minute: Optional[int] = None, par_jour: Optional[int] = None,
                 compteur: Optional[CompteurPersistant] = None, horloge: Horloge = maintenant_paris):
        self.nom = nom
        self.par_minute = par_minute
        self.par_jour = par_jour
        self.compteur = compteur
        self.horloge = horloge
        self._minute: deque[datetime] = deque()
        self._jour_memoire: dict[str, int] = {}

    def _jour(self) -> str:
        return self.horloge().astimezone(FUSEAU).date().isoformat()

    def _compte_jour(self) -> int:
        if self.compteur:
            return self.compteur.valeur(self.nom, self._jour())
        return self._jour_memoire.get(self._jour(), 0)

    def restant_aujourdhui(self) -> Optional[int]:
        return None if self.par_jour is None else max(self.par_jour - self._compte_jour(), 0)

    def autoriser(self) -> bool:
        t = self.horloge()
        while self._minute and t - self._minute[0] >= timedelta(minutes=1):
            self._minute.popleft()
        if self.par_minute is not None and len(self._minute) >= self.par_minute:
            return False
        if self.par_jour is not None and self._compte_jour() >= self.par_jour:
            return False
        self._minute.append(t)
        if self.compteur:
            self.compteur.incrementer(self.nom, self._jour())
        else:
            self._jour_memoire[self._jour()] = self._jour_memoire.get(self._jour(), 0) + 1
        return True


class Disjoncteur:
    """S'ouvre après `seuil` erreurs 429/403 consécutives ; se referme après `pause`."""

    CODES = (403, 429)

    def __init__(self, seuil: int = 3, pause: timedelta = timedelta(minutes=30),
                 horloge: Horloge = maintenant_paris):
        self.seuil = seuil
        self.pause = pause
        self.horloge = horloge
        self._erreurs = 0
        self._ouvert_jusqua: Optional[datetime] = None

    def ouvert(self) -> bool:
        if self._ouvert_jusqua is None:
            return False
        if self.horloge() >= self._ouvert_jusqua:
            self._ouvert_jusqua = None
            self._erreurs = 0
            return False
        return True

    def echec(self, statut: int) -> None:
        if statut not in self.CODES:
            return
        self._erreurs += 1
        if self._erreurs >= self.seuil:
            self._ouvert_jusqua = self.horloge() + self.pause

    def succes(self) -> None:
        self._erreurs = 0
