"""Mesures d'un backtest, avec le garde-fou « échantillon insuffisant »."""
from dataclasses import dataclass

from poste.backtest.moteur import Resultat

# En dessous, un taux de réussite ou un rendement moyen ne veut statistiquement presque rien.
ECHANTILLON_MIN = 30


@dataclass
class Mesures:
    nb_trades: int
    rendement_eur: float
    rendement_pct: float
    pire_baisse_eur: float
    pire_baisse_pct: float
    taux_reussite: float
    echantillon_insuffisant: bool

    def ligne(self) -> str:
        avert = " · ÉCHANTILLON INSUFFISANT" if self.echantillon_insuffisant else ""
        return (f"{self.nb_trades} trades · rendement {self.rendement_eur:+.0f} € ({self.rendement_pct:+.1f} %)"
                f" · pire baisse {self.pire_baisse_eur:.0f} € ({self.pire_baisse_pct:.1f} %)"
                f" · réussite {self.taux_reussite * 100:.0f} %{avert}")


def mesurer(r: Resultat, capital: float = 2500.0) -> Mesures:
    pnl = sum(t.pnl for t in r.trades)
    pic, pire, pire_pct = capital, 0.0, 0.0
    for _, v in r.equity:
        pic = max(pic, v)
        if v - pic < pire:
            pire = v - pic
            pire_pct = (v - pic) / pic * 100
    n = len(r.trades)
    gagnants = sum(1 for t in r.trades if t.pnl > 0)
    return Mesures(n, pnl, pnl / capital * 100, pire, pire_pct, gagnants / n if n else 0.0, n < ECHANTILLON_MIN)
