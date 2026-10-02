"""Verdict du walk-forward. Une règle alternative n'est retenue (comme simple piste) que si, hors
échantillon, l'amélioration est à la fois : mesurée sur assez de trades, nette, régulière, stable
d'une année à l'autre et pas moins protectrice que le plan quand le marché baisse.
Sinon on garde les seuils du plan (règle 8)."""
from dataclasses import dataclass
from math import ceil

from poste.backtest.mesures import ECHANTILLON_MIN
from poste.backtest.walkforward import WalkForward

MARGE_MIN_PCT = 25.0    # l'écart doit valoir au moins 25 % du résultat du plan...
MARGE_MIN_EUR = 100.0   # ...et au moins 100 €
PART_ANNEES_MIN = 2 / 3
PART_STABILITE_MIN = 0.5


@dataclass
class Evaluation:
    retenue: bool
    raisons: list[str]  # pourquoi elle ne l'est pas (vide si retenue)


def evaluer_walk_forward(wf: WalkForward) -> Evaluation:
    n = len(wf.etapes)
    trades = sum(e.trades_test_choisie for e in wf.etapes)
    if trades < ECHANTILLON_MIN:
        return Evaluation(False, [f"échantillon insuffisant ({trades} trades testés, il en faut {ECHANTILLON_MIN})"])
    raisons = []
    ecart = wf.pnl_choisie - wf.pnl_plan
    requis = max(MARGE_MIN_PCT / 100 * abs(wf.pnl_plan), MARGE_MIN_EUR)
    if ecart < requis:
        raisons.append(f"écart trop faible : {ecart:+.0f} € alors qu'il faudrait au moins {requis:.0f} €"
                       f" ({MARGE_MIN_PCT:.0f} % du résultat du plan)")
    minimum = ceil(PART_ANNEES_MIN * n)
    if wf.annees_gagnees < minimum:
        raisons.append(f"pas assez régulier : meilleure que le plan {wf.annees_gagnees} année(s) sur {n},"
                       f" il en faut {minimum}")
    baisse = [e for e in wf.etapes if e.variation_test_pct < 0 and e.pnl_test_choisie < e.pnl_test_plan]
    if baisse:
        annees = ", ".join(str(e.test_annees[0]) for e in baisse)
        raisons.append(f"moins protectrice que le plan lors des années de baisse ({annees})")
    _, freq = wf.regle_la_plus_frequente()
    if freq < PART_STABILITE_MIN * n:
        raisons.append(f"pas de règle stable : la plus choisie ne l'est que {freq} année(s) sur {n}")
    return Evaluation(not raisons, raisons)
