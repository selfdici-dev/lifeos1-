"""Journal saisi à la main : achats, déplacements de stop, ventes, et fiches d'ordre émises.
Fichier local journal.json (non versionné). Montants en Decimal."""
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Optional

from pydantic import AwareDatetime, BaseModel, Field, model_validator

CHEMIN_JOURNAL = Path(__file__).resolve().parent.parent / "journal.json"


class Achat(BaseModel):
    quand: AwareDatetime
    trade_id: str
    quantite: int = Field(ge=1)
    prix_execution_eur: Decimal = Field(gt=0)
    stop_eur: Decimal = Field(gt=0)
    objectif_eur: Optional[Decimal] = Field(default=None, gt=0)
    raison: str = Field(min_length=1)
    fiche_id: Optional[str] = None

    @model_validator(mode="after")
    def _stop_sous_achat(self):
        if self.stop_eur >= self.prix_execution_eur:
            raise ValueError("le stop doit être sous le prix d'achat")
        return self


class Vente(BaseModel):
    quand: AwareDatetime
    quantite: int = Field(ge=1)
    prix_eur: Decimal = Field(gt=0)
    raison: str = ""


class DeplacementStop(BaseModel):
    quand: AwareDatetime
    stop_eur: Decimal = Field(gt=0)


class FicheJournal(BaseModel):
    """Trace de chaque fiche émise, pour savoir après coup ce qui a été suivi ou ignoré."""
    id: str = ""
    quand: AwareDatetime
    trade_id: str
    verdict: Literal["FEU VERT", "ATTENDRE", "INTERDIT"]
    prix_limite_eur: Optional[Decimal] = None
    prix_stop_eur: Optional[Decimal] = None
    quantite: Optional[int] = None


class Position(BaseModel):
    id: str
    achat: Achat
    stops: list[DeplacementStop] = []
    ventes: list[Vente] = []
    frais_par_ordre: Decimal = Decimal("1")

    @property
    def quantite_restante(self) -> int:
        return self.achat.quantite - sum(v.quantite for v in self.ventes)

    @property
    def fermee(self) -> bool:
        return self.quantite_restante == 0

    @property
    def stop_courant(self) -> Decimal:
        return self.stops[-1].stop_eur if self.stops else self.achat.stop_eur

    @property
    def stop_descendu(self) -> bool:
        niveaux = [self.achat.stop_eur] + [s.stop_eur for s in self.stops]
        return any(b < a for a, b in zip(niveaux, niveaux[1:]))

    @property
    def resultat_realise_eur(self) -> Decimal:
        """Gains et pertes déjà encaissés (ventes faites), frais d'achat et de vente compris."""
        if not self.ventes:
            return Decimal("0")
        pa = self.achat.prix_execution_eur
        brut = sum((v.quantite * (v.prix_eur - pa) for v in self.ventes), Decimal("0"))
        return brut - self.frais_par_ordre * (1 + len(self.ventes))

    @property
    def resultat_eur(self) -> Optional[Decimal]:
        return self.resultat_realise_eur if self.fermee else None


class Journal:
    def __init__(self, chemin: Path = CHEMIN_JOURNAL, frais_par_ordre: Decimal = Decimal("1")):
        self.chemin = Path(chemin)
        self.frais = frais_par_ordre
        self.positions: list[Position] = []
        self.fiches: list[FicheJournal] = []
        if self.chemin.exists():
            d = json.loads(self.chemin.read_text(encoding="utf-8"))
            self.positions = [Position.model_validate({**p, "frais_par_ordre": frais_par_ordre})
                              for p in d.get("positions", [])]
            self.fiches = [FicheJournal.model_validate(f) for f in d.get("fiches", [])]

    def _sauver(self) -> None:
        d = {"positions": [p.model_dump(mode="json", exclude={"frais_par_ordre"}) for p in self.positions],
             "fiches": [f.model_dump(mode="json") for f in self.fiches]}
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.chemin.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.chemin)  # écriture atomique : pas de journal à moitié écrit

    def position(self, pid: str) -> Position:
        for p in self.positions:
            if p.id == pid:
                return p
        raise KeyError(f"position inconnue : {pid}")

    def ouvertes(self) -> list[Position]:
        return [p for p in self.positions if not p.fermee]

    def acheter(self, achat: Achat) -> Position:
        if achat.fiche_id is not None and achat.fiche_id not in {f.id for f in self.fiches}:
            raise KeyError(f"fiche inconnue : {achat.fiche_id}")
        p = Position(id=f"A{len(self.positions) + 1}", achat=achat, frais_par_ordre=self.frais)
        self.positions.append(p)
        self._sauver()
        return p

    def deplacer_stop(self, pid: str, quand: datetime, stop: Decimal) -> Position:
        p = self.position(pid)
        if p.fermee:
            raise ValueError("position déjà fermée")
        p.stops.append(DeplacementStop(quand=quand, stop_eur=stop))
        self._sauver()
        return p

    def vendre(self, pid: str, vente: Vente) -> Position:
        p = self.position(pid)
        if vente.quantite > p.quantite_restante:
            raise ValueError(f"tu ne détiens que {p.quantite_restante} titre(s) sur cette position")
        p.ventes.append(vente)
        self._sauver()
        return p

    def noter_fiche(self, fiche: FicheJournal) -> FicheJournal:
        fiche = fiche.model_copy(update={"id": f"F{len(self.fiches) + 1}"})
        self.fiches.append(fiche)
        self._sauver()
        return fiche

    def perte_cumulee(self) -> Decimal:
        total = sum((p.resultat_realise_eur for p in self.positions), Decimal("0"))
        return max(Decimal("0"), -total)

    def nb_trades_fermes(self) -> int:
        return sum(1 for p in self.positions if p.fermee)
