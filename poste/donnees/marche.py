"""Agrégateur : essaie les sources dans l'ordre et garde la première donnée à jour."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from poste.donnees.fournisseurs import NY, AlphaVantage, Finnhub, Fred, TwelveData, YFinance, _cloture_ny
from poste.donnees.indicateurs import moyenne_mobile
from poste.donnees.limiteur import Horloge, maintenant_paris
from poste.donnees.modeles import Donnee, Fraicheur, Historique, Nature, fraicheur
from poste.plan import Trade
from poste.regles import Evenement


@dataclass
class Releve:
    donnees: dict[str, Optional[Donnee]]
    obligatoires: list[str]
    evenements: Optional[list[Evenement]] = None  # None = inconnu
    sources_essayees: dict[str, list[str]] = field(default_factory=dict)

    def perimees(self, maintenant: datetime) -> list[str]:
        return [n for n in self.obligatoires if fraicheur(self.donnees.get(n), maintenant) is Fraicheur.ROUGE]


class Marche:
    def __init__(self, finnhub: Finnhub, twelvedata: TwelveData, fred: Fred, alphavantage: AlphaVantage,
                 yfinance: YFinance, horloge: Horloge = maintenant_paris):
        self.finnhub = finnhub
        self.twelvedata = twelvedata
        self.fred = fred
        self.alphavantage = alphavantage
        self.yfinance = yfinance
        self.horloge = horloge

    def _premier(self, essais: list[Callable[[], Optional[Donnee]]]) -> Optional[Donnee]:
        """Première donnée non périmée ; sinon la plus récente trouvée (elle sera affichée en rouge)."""
        maintenant = self.horloge()
        meilleure = None
        for essai in essais:
            d = essai()
            if d is None:
                continue
            if fraicheur(d, maintenant) is not Fraicheur.ROUGE:
                return d
            if meilleure is None or d.horodatage > meilleure.horodatage:
                meilleure = d
        return meilleure

    def cours(self, trade: Trade) -> Optional[Donnee]:
        s = trade.symboles
        essais = []
        if "finnhub" in s:
            essais.append(lambda: self.finnhub.cotation(s["finnhub"]))
        if "twelvedata" in s:
            essais.append(lambda: self.twelvedata.cotation(s["twelvedata"]))
        if "yfinance" in s:
            essais.append(lambda: self.yfinance.cotation(s["yfinance"]))
        return self._premier(essais)

    def historique(self, trade: Trade) -> Optional[Historique]:
        s = trade.symboles
        if "twelvedata" in s:
            h = self.twelvedata.historique(s["twelvedata"])
            if h:
                return h
        if "yfinance" in s:
            return self.yfinance.historique(s["yfinance"])
        return None

    def mm50(self, trade: Trade) -> Optional[Donnee]:
        h = self.historique(trade)
        if h is None:
            return None
        aujourdhui = self.horloge().astimezone(NY).date()
        mm = moyenne_mobile(h.barres, avant=aujourdhui, n=50)
        if mm is None:
            return None
        derniere = max(d for d, _ in h.barres if d < aujourdhui)
        return Donnee("moyenne mobile 50 jours", mm.quantize(mm.__class__("0.01")), _cloture_ny(derniere),
                      h.source, Nature.QUOTIDIEN)

    def eurusd(self) -> Optional[Donnee]:
        return self._premier([lambda: self.twelvedata.cotation("EUR/USD"),
                              lambda: self.yfinance.cotation("EURUSD=X")])

    def taux_10a(self) -> Optional[Donnee]:
        return self._premier([self.fred.taux_10a])

    def sp500_variation(self) -> Optional[Donnee]:
        # SPY (ETF qui réplique le S&P 500) sert d'approximation de l'indice sur Finnhub et Twelve Data
        return self._premier([lambda: self.finnhub.variation_pct("SPY"),
                              lambda: self.twelvedata.variation_pct("SPY"),
                              lambda: self.yfinance.variation_pct("^GSPC")])

    def evenements(self, trade: Trade) -> Optional[list[Evenement]]:
        if "alphavantage" not in trade.symboles:
            return []
        return self.alphavantage.resultats(trade.symboles["alphavantage"])

    def releve(self, trade: Trade) -> Releve:
        donnees = {
            "cours": self.cours(trade),
            "mm50": self.mm50(trade),
            "taux_us10a": self.taux_10a(),
            "sp500_variation": self.sp500_variation(),
        }
        obligatoires = list(donnees)
        if trade.devise_ref == "USD":
            donnees["eurusd"] = self.eurusd()
            obligatoires.append("eurusd")
        return Releve(donnees, obligatoires, self.evenements(trade))
