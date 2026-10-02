"""Adaptateur Interactive Brokers (TWS API officielle, via la bibliothèque ib_async).

NON TESTÉ contre un vrai TWS / IB Gateway : ce conteneur n'y a pas accès. À essayer d'abord sur ton
compte de démonstration (paper), port 7497 par défaut pour TWS en mode paper.

Pas d'identifiant dans le code : tu te connectes toi-même à TWS ou IB Gateway (mot de passe et
authentification forte à ta charge) ; l'application ne fait que parler au logiciel déjà connecté,
sur ta machine. La TWS API ne permet ni retrait ni virement. Active « Read-Only API » dans TWS tant que
tu ne veux aucun envoi.
"""
from decimal import Decimal
from typing import Optional

from poste.execution.courtier import Courtier
from poste.execution.limites import LISTE_BLANCHE
from poste.execution.modeles import EtatOrdre, OrdrePropose


class CourtierIBKR(Courtier):
    def __init__(self, hote: str = "127.0.0.1", port: int = 7497, client_id: int = 17, ib=None):
        self.hote, self.port, self.client_id = hote, port, client_id
        self._ib = ib
        self._ordres: dict[str, object] = {}

    @property
    def ib(self):
        if self._ib is None:
            from ib_async import IB
            self._ib = IB()
        if not self._ib.isConnected():
            self._ib.connect(self.hote, self.port, clientId=self.client_id, timeout=10)
        return self._ib

    def est_simulation(self) -> bool:
        # Chez IBKR, les comptes de démonstration commencent par « D » (ex. DU1234567). À vérifier sur le tien.
        comptes = self.ib.managedAccounts()
        return bool(comptes) and all(c.startswith("D") for c in comptes)

    def _contrat(self, o: OrdrePropose):
        from ib_async import Stock
        inst = LISTE_BLANCHE[o.trade_id]
        contrat = Stock(inst.symbole, inst.place, inst.devise)
        details = self.ib.reqContractDetails(contrat)
        if len(details) != 1:
            raise ValueError(f"contrat ambigu ou introuvable ({len(details)} résultats)")
        isins = {t.value for t in (details[0].secIdList or []) if t.tag == "ISIN"}
        if inst.isin not in isins:
            raise ValueError("l'ISIN du contrat IBKR ne correspond pas à la liste blanche")
        return details[0].contract

    def placer_bracket(self, o: OrdrePropose) -> tuple[str, Optional[str]]:
        from ib_async import LimitOrder, StopOrder
        contrat = self._contrat(o)
        achat = LimitOrder("BUY", o.quantite, float(o.prix_limite), tif="DAY", outsideRth=False, transmit=False)
        achat.orderId = self.ib.client.getReqId()
        stop = StopOrder("SELL", o.quantite, float(o.prix_stop), tif="GTC", parentId=achat.orderId,
                         transmit=True)  # transmis avec l'achat : jamais d'achat sans son stop
        t_achat = self.ib.placeOrder(contrat, achat)
        t_stop = self.ib.placeOrder(contrat, stop)
        self.ib.sleep(2)
        self._ordres[str(achat.orderId)] = t_achat
        self._ordres[str(t_stop.order.orderId)] = t_stop
        return str(achat.orderId), str(t_stop.order.orderId)

    def _trade(self, ordre_id: str):
        for t in self.ib.trades():
            if str(t.order.orderId) == ordre_id:
                return t
        return self._ordres.get(ordre_id)

    def etat(self, ordre_id: str) -> EtatOrdre:
        self.ib.sleep(0.5)
        t = self._trade(ordre_id)
        if t is None:
            return EtatOrdre("Introuvable")
        s = t.orderStatus
        prix = Decimal(str(round(s.avgFillPrice, 4))) if s.filled else None
        return EtatOrdre(s.status, int(s.filled), prix)

    def ordres_ouverts(self):
        return [(str(t.order.orderId), t.order.action, t.order.orderType) for t in self.ib.openTrades()]

    def annuler(self, ordre_id: str) -> None:
        t = self._trade(ordre_id)
        if t is not None:
            self.ib.cancelOrder(t.order)

    def modifier_quantite(self, ordre_id: str, quantite: int) -> None:
        t = self._trade(ordre_id)
        if t is None:
            raise ValueError("ordre introuvable chez le courtier")
        t.order.totalQuantity = quantite
        self.ib.placeOrder(t.contract, t.order)
