"""Réglages personnels (niveau d'agressivité). Fichier local, non versionné."""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from poste.rappels import RAPPELS_DEFAUT, Rappel

CHEMIN_REGLAGES = Path(__file__).resolve().parent.parent / "reglages.json"


class Reglages(BaseModel):
    niveau: Literal[1, 2, 3] = 1
    rappels: list[Rappel] = RAPPELS_DEFAUT


def charger_reglages(chemin: Path = CHEMIN_REGLAGES) -> Reglages:
    chemin = Path(chemin)
    if not chemin.exists():
        return Reglages()
    return Reglages.model_validate(json.loads(chemin.read_text(encoding="utf-8")))


def enregistrer_reglages(reglages: Reglages, chemin: Path = CHEMIN_REGLAGES) -> None:
    Path(chemin).write_text(reglages.model_dump_json(indent=2), encoding="utf-8")
