"""Interrupteur d'arrêt : un fichier sur disque, donc il survit à un redémarrage du programme."""
from datetime import datetime
from pathlib import Path
from typing import Optional


class Interrupteur:
    def __init__(self, chemin: Path):
        self.chemin = Path(chemin)

    @property
    def actif(self) -> bool:
        return self.chemin.exists()

    @property
    def raison(self) -> Optional[str]:
        return self.chemin.read_text(encoding="utf-8").strip() if self.actif else None

    def declencher(self, raison: str, quand: datetime) -> None:
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        with self.chemin.open("a", encoding="utf-8") as f:
            f.write(f"{quand.isoformat()} {raison}\n")

    def lever(self) -> None:
        """Seulement à la main (python -m poste reprise) : jamais automatiquement."""
        if self.actif:
            self.chemin.unlink()
