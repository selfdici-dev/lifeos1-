"""Réglages personnels (niveau d'agressivité). Fichier local, non versionné."""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator

from poste.rappels import RAPPELS_DEFAUT, Rappel

CHEMIN_REGLAGES = Path(__file__).resolve().parent.parent / "reglages.json"


class Reglages(BaseModel):
    niveau: Literal[1, 2, 3] = 1
    rappels: list[Rappel] = RAPPELS_DEFAUT

    @field_validator("rappels", mode="before")
    @classmethod
    def _migrer(cls, valeur):
        # l'ancien rappel figeait « 15:15 / ouvre à 15:30 », faux pendant les semaines de décalage horaire
        out = []
        for r in valeur or []:
            msg = r.get("message", "") if isinstance(r, dict) else r.message
            if msg.startswith("La séance US ouvre à 15:30"):
                r = RAPPELS_DEFAUT[0]
            out.append(r)
        return out


def charger_reglages(chemin: Path = CHEMIN_REGLAGES) -> Reglages:
    chemin = Path(chemin)
    if not chemin.exists():
        return Reglages()
    return Reglages.model_validate(json.loads(chemin.read_text(encoding="utf-8")))


def enregistrer_reglages(reglages: Reglages, chemin: Path = CHEMIN_REGLAGES) -> None:
    # les valeurs par défaut ne sont pas figées dans le fichier : une correction future s'applique
    Path(chemin).write_text(reglages.model_dump_json(indent=2, exclude_defaults=True), encoding="utf-8")
