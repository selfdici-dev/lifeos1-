"""Exposition par thème. Les trois thèmes du plan sont corrélés (paris sur la tech et le risque) :
leur total est comparé au seuil de 60 % du capital. Les lignes hors plan (ex. Micron) n'entrent pas."""
import json
from dataclasses import dataclass
from pathlib import Path
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from poste.regles import SEUIL_CORRELE_PCT

Theme = Literal["semi-conducteurs", "crypto", "nasdaq_turbo"]
THEMES: tuple[str, ...] = ("semi-conducteurs", "crypto", "nasdaq_turbo")


class Position(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument: str
    theme: Theme
    valeur_eur: Decimal = Field(ge=0)


@dataclass
class Exposition:
    capital_eur: Decimal
    par_theme: dict[str, Decimal]
    total_correle_eur: Decimal
    total_correle_pct: Decimal
    avertissement: Optional[str]

    def texte(self) -> str:
        lignes = ["Exposition par thème :"]
        for th in THEMES:
            v = self.par_theme[th]
            lignes.append(f"  {th} : {v} € ({(v / self.capital_eur * 100).quantize(Decimal('0.1'))} %)")
        lignes.append(f"  Total corrélé : {self.total_correle_eur} € ({self.total_correle_pct} % du capital)")
        if self.avertissement:
            lignes.append(f"  ATTENTION : {self.avertissement}")
        return "\n".join(lignes)


def calculer_exposition(positions: list[Position], capital_eur: Decimal,
                        ajout: Optional[tuple[str, Decimal]] = None) -> Exposition:
    par_theme = {th: Decimal("0") for th in THEMES}
    for p in positions:
        par_theme[p.theme] += p.valeur_eur
    if ajout is not None:
        theme, montant = ajout
        par_theme[theme] += montant
    total = sum(par_theme.values(), Decimal("0"))
    pct = (total / capital_eur * 100).quantize(Decimal("0.01"))
    avert = None
    if pct > SEUIL_CORRELE_PCT:
        avert = (f"total corrélé à {pct} % du capital, au-delà de {SEUIL_CORRELE_PCT} % :"
                 f" une même baisse de la tech toucherait presque tout ton argent.")
    return Exposition(capital_eur, par_theme, total, pct, avert)


def charger_positions(chemin) -> list[Position]:
    chemin = Path(chemin)
    if not chemin.exists():
        return []
    return [Position.model_validate(p) for p in json.loads(chemin.read_text(encoding="utf-8"))]
