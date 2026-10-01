"""Cache de réponses brutes (texte), en mémoire et éventuellement sur disque."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from poste.donnees.limiteur import Horloge, maintenant_paris


class Cache:
    def __init__(self, horloge: Horloge = maintenant_paris, chemin: Optional[Path] = None):
        self.horloge = horloge
        self.chemin = Path(chemin) if chemin else None
        self._d: dict[str, tuple[str, str]] = {}
        if self.chemin and self.chemin.exists():
            try:
                self._d = {k: tuple(v) for k, v in json.loads(self.chemin.read_text(encoding="utf-8")).items()}
            except ValueError:
                self._d = {}

    def lire(self, cle: str, ttl: timedelta) -> Optional[str]:
        if cle not in self._d:
            return None
        quand, valeur = self._d[cle]
        if self.horloge() - datetime.fromisoformat(quand) > ttl:
            return None
        return valeur

    def mettre(self, cle: str, valeur: str) -> None:
        self._d[cle] = (self.horloge().isoformat(), valeur)
        if self.chemin:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            self.chemin.write_text(json.dumps(self._d), encoding="utf-8")
