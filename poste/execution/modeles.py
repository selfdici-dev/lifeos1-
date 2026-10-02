from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class Mode(str, Enum):
    MANUEL = "MANUEL"              # fiche d'ordre seulement (défaut)
    CONFIRMATION = "CONFIRMATION"  # l'app prépare l'ordre, tu l'approuves, un ordre à la fois
    AUTO = "AUTO"                  # l'app envoie seule, dans les limites codées en dur


@dataclass(frozen=True)
class OrdrePropose:
    """Ordre d'achat tiré d'une fiche FEU VERT : achat à cours limité + stop de protection."""
    trade_id: str
    isin: Optional[str]
    quantite: int
    prix_limite: Decimal
    prix_stop: Decimal
    devise: str
    fiche_id: Optional[str]
    verdict: str
    perimees: tuple[str, ...] = ()

    @property
    def montant(self) -> Decimal:
        return self.quantite * self.prix_limite


@dataclass(frozen=True)
class EtatOrdre:
    statut: str
    quantite_executee: int = 0
    prix_moyen: Optional[Decimal] = None


@dataclass
class CompteRendu:
    envoye: bool
    raisons: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    etat: str = ""
    position_id: Optional[str] = None

    def texte(self) -> str:
        l = [("ORDRE ENVOYÉ" if self.envoye else "AUCUN ORDRE ENVOYÉ") + (f" : {self.etat}" if self.etat else "")]
        l += [f"  - {r}" for r in self.raisons]
        l += [f"  ANOMALIE : {a}" for a in self.anomalies]
        return "\n".join(l)
