"""Interface courtier, et un faux courtier en mémoire pour les tests."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from itertools import count
from typing import Optional

from poste.execution.modeles import EtatOrdre, OrdrePropose

STATUTS_ACTIFS = ("PendingSubmit", "PreSubmitted", "Submitted")
STATUTS_CONNUS = STATUTS_ACTIFS + ("Filled", "Cancelled", "ApiCancelled", "Inactive", "PendingCancel")


class Courtier(ABC):
    @abstractmethod
    def est_simulation(self) -> bool:
        """Vrai seulement si le compte connecté est un compte de démonstration."""

    @abstractmethod
    def placer_bracket(self, o: OrdrePropose) -> tuple[str, Optional[str]]:
        """Achat à cours limité + stop de vente lié, transmis ensemble. Renvoie (id achat, id stop)."""

    @abstractmethod
    def etat(self, ordre_id: str) -> EtatOrdre: ...

    @abstractmethod
    def ordres_ouverts(self) -> list[tuple[str, str, str]]:
        """(id, sens BUY/SELL, type LMT/STP) des ordres encore actifs."""

    @abstractmethod
    def annuler(self, ordre_id: str) -> None: ...

    @abstractmethod
    def modifier_quantite(self, ordre_id: str, quantite: int) -> None: ...

    def annuler_achats_en_attente(self) -> list[str]:
        """Annule les achats non exécutés. Les stops qui protègent des positions restent en place."""
        annules = []
        for oid, sens, _ in self.ordres_ouverts():
            if sens == "BUY":
                self.annuler(oid)
                annules.append(oid)
        return annules


@dataclass
class OrdreCourtier:
    id: str
    sens: str
    type: str
    quantite: int
    prix: Decimal
    duree: str
    parent_id: Optional[str]
    statut: str
    quantite_executee: int = 0
    prix_moyen: Optional[Decimal] = None


class CourtierFactice(Courtier):
    """Faux courtier : `comportement` règle la réponse au prochain ordre (exécution, rejet, panne...)."""

    def __init__(self, compte: str = "DU0000000"):
        self.compte = compte
        self.ordres: list[OrdreCourtier] = []
        self.comportement: dict = {}
        self._ids = count(1)

    def est_simulation(self) -> bool:
        return self.compte.startswith("D")

    def _get(self, oid: str) -> OrdreCourtier:
        return next(o for o in self.ordres if o.id == oid)

    def placer_bracket(self, o: OrdrePropose):
        c = self.comportement
        if c.get("exception"):
            raise ConnectionError("connexion perdue")
        statut = c.get("statut", "Filled")
        q_exec = c.get("quantite_executee", o.quantite if statut == "Filled" else 0)
        prix = c.get("prix_execution", o.prix_limite) if q_exec else None
        parent = OrdreCourtier(str(next(self._ids)), "BUY", "LMT", o.quantite, o.prix_limite, "DAY", None,
                               statut, q_exec, prix)
        self.ordres.append(parent)
        stop_id = None
        if not c.get("sans_stop"):
            stop = OrdreCourtier(str(next(self._ids)), "SELL", "STP", o.quantite, o.prix_stop, "GTC", parent.id,
                                 "Submitted" if q_exec else "PreSubmitted")
            self.ordres.append(stop)
            stop_id = stop.id
        return parent.id, stop_id

    def etat(self, ordre_id):
        o = self._get(ordre_id)
        return EtatOrdre(o.statut, o.quantite_executee, o.prix_moyen)

    def ordres_ouverts(self):
        return [(o.id, o.sens, o.type) for o in self.ordres if o.statut in STATUTS_ACTIFS]

    def annuler(self, ordre_id):
        o = self._get(ordre_id)
        o.statut = "Cancelled"
        for enfant in self.ordres:  # comme chez IBKR : annuler l'achat annule son stop lié
            if enfant.parent_id == ordre_id and o.quantite_executee == 0:
                enfant.statut = "Cancelled"

    def modifier_quantite(self, ordre_id, quantite):
        self._get(ordre_id).quantite = quantite
