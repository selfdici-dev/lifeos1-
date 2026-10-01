"""Walk-forward : on choisit la meilleure règle sur des années d'apprentissage, puis on la juge
sur l'année suivante, jamais vue. Les deux périodes ne se mélangent jamais."""
from dataclasses import dataclass
from typing import Optional

from poste.backtest.mesures import mesurer
from poste.backtest.moteur import Barre, Config, Couts, simuler


def decoupages(premiere: int, derniere: int, apprentissage: int = 3, test: int = 1):
    out = []
    a0 = premiere
    while a0 + apprentissage + test - 1 <= derniere:
        a1 = a0 + apprentissage - 1
        out.append(((a0, a1), (a1 + 1, a1 + test)))
        a0 += test
    return out


def indices_annees(barres: list[Barre], a0: int, a1: int) -> Optional[tuple[int, int]]:
    idx = [i for i, b in enumerate(barres) if a0 <= b.jour.year <= a1]
    return (idx[0], idx[-1]) if idx else None


@dataclass
class Etape:
    apprentissage_annees: tuple[int, int]
    test_annees: tuple[int, int]
    choisie: Config
    pnl_test_choisie: float
    pnl_test_plan: float
    trades_test_choisie: int


@dataclass
class WalkForward:
    etapes: list[Etape]

    @property
    def pnl_choisie(self) -> float:
        return sum(e.pnl_test_choisie for e in self.etapes)

    @property
    def pnl_plan(self) -> float:
        return sum(e.pnl_test_plan for e in self.etapes)

    @property
    def annees_gagnees(self) -> int:
        return sum(1 for e in self.etapes if e.pnl_test_choisie > e.pnl_test_plan)


def _pnl(barres, cfg, couts, montant, i0, i1):
    r = simuler(barres, cfg, couts, montant=montant, premier_jour=max(i0, 50), dernier_jour=i1)
    return r, mesurer(r)


def walk_forward(barres: list[Barre], configs: list[Config], plan: Config, couts: Couts,
                 montant: float = 625.0, apprentissage: int = 3, test: int = 1) -> WalkForward:
    annees = sorted({b.jour.year for b in barres})
    etapes = []
    for (a0, a1), (t0, t1) in decoupages(annees[0], annees[-1], apprentissage, test):
        app = indices_annees(barres, a0, a1)
        tst = indices_annees(barres, t0, t1)
        if app is None or tst is None:
            continue
        # sélection : meilleur rendement sur l'apprentissage, pénalisé par la pire baisse
        def score(cfg):
            _, m = _pnl(barres, cfg, couts, montant, *app)
            return m.rendement_eur + 0.5 * m.pire_baisse_eur
        choisie = max(configs, key=score)
        r_c, m_c = _pnl(barres, choisie, couts, montant, *tst)
        _, m_p = _pnl(barres, plan, couts, montant, *tst)
        etapes.append(Etape((a0, a1), (t0, t1), choisie, m_c.rendement_eur, m_p.rendement_eur, m_c.nb_trades))
    return WalkForward(etapes)
