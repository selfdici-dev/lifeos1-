"""Chargement du plan (plan.json). Tous les seuils sont des points de départ non testés."""
import json
from decimal import Decimal
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

CHEMIN_PLAN = Path(__file__).resolve().parent.parent / "plan.json"

Pct = Decimal


class _Strict(BaseModel):
    # une clé inconnue est refusée : aucune règle bloquante ne peut être assouplie depuis plan.json
    model_config = ConfigDict(extra="forbid")


class Niveau(_Strict):
    nom: str
    risque_max_par_trade_eur: Decimal = Field(gt=0)
    montant_max_par_trade_eur: Decimal = Field(gt=0)
    seuil_arret_perte_cumulee_eur: Decimal = Field(gt=0)


class Trade(_Strict):
    id: str
    nom: str
    type: Literal["action", "etf", "etp", "turbo_long"]
    theme: Literal["semi-conducteurs", "crypto", "nasdaq_turbo"]
    isin: Optional[str] = None
    devise_ref: Literal["USD", "EUR", "points"]
    ref_libelle: str
    meme_cours_que_ref: bool
    filtre_mm50: bool = True
    fourchette_entree_ref: Optional[tuple[Decimal, Decimal]] = None
    stop_pct: Pct = Field(gt=0, lt=100)
    objectifs_pct: list[Pct] = Field(min_length=1, max_length=2)
    barriere_distance_pct: Optional[tuple[Pct, Pct]] = None
    # symbole par fournisseur (finnhub, twelvedata, yfinance, alphavantage) ; vide = pas de données en direct
    symboles: dict[Literal["finnhub", "twelvedata", "yfinance", "alphavantage"], str] = {}

    @model_validator(mode="after")
    def _coherence(self):
        if self.objectifs_pct != sorted(self.objectifs_pct) or self.objectifs_pct[0] <= 0:
            raise ValueError(f"{self.id} : objectifs positifs et croissants attendus")
        if self.type == "turbo_long" and self.barriere_distance_pct is None:
            raise ValueError(f"{self.id} : un turbo doit avoir une plage de barrière")
        if self.fourchette_entree_ref and self.fourchette_entree_ref[0] > self.fourchette_entree_ref[1]:
            raise ValueError(f"{self.id} : fourchette inversée")
        return self


class Plan(_Strict):
    version: str
    avertissement: str = ""
    frais_note: str = ""
    capital_eur: Decimal = Field(gt=0)
    frais_par_ordre_eur: Decimal = Field(ge=0)
    marge_limite_pct: Decimal = Field(ge=0, lt=5)
    ratio_min_gain_risque: Decimal = Field(gt=0)
    tolerance_ecart_prix_pct: Decimal = Field(gt=0)
    niveaux: dict[str, Niveau]
    trades: list[Trade]

    @model_validator(mode="after")
    def _coherence(self):
        if set(self.niveaux) != {"1", "2", "3"}:
            raise ValueError("le plan doit définir exactement les niveaux 1, 2 et 3")
        champs = ("risque_max_par_trade_eur", "montant_max_par_trade_eur", "seuil_arret_perte_cumulee_eur")
        for champ in champs:
            valeurs = [getattr(self.niveaux[k], champ) for k in ("1", "2", "3")]
            if valeurs != sorted(valeurs):
                raise ValueError(f"{champ} doit croître du niveau 1 au niveau 3")
        for n in self.niveaux.values():
            if n.montant_max_par_trade_eur > self.capital_eur:
                raise ValueError("montant maximal par trade supérieur au capital")
        ids = [t.id for t in self.trades]
        if len(ids) != len(set(ids)):
            raise ValueError("identifiants de trades en double")
        return self

    def trade(self, trade_id: str) -> Trade:
        for t in self.trades:
            if t.id == trade_id:
                return t
        raise KeyError(f"trade inconnu : {trade_id}")

    def niveau(self, niveau: int | str) -> Niveau:
        cle = str(niveau)
        if cle not in self.niveaux:
            raise KeyError(f"niveau inconnu : {niveau}")
        return self.niveaux[cle]


def charger_plan(chemin: Path = CHEMIN_PLAN) -> Plan:
    # parse_float=Decimal : aucun nombre ne passe par un float binaire
    donnees = json.loads(Path(chemin).read_text(encoding="utf-8"), parse_float=Decimal)
    return Plan.model_validate(donnees)
