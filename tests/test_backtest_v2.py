"""Corrections du rapport de backtest : stop suiveur, verdict plus sévère, avertissements."""
from datetime import date, timedelta

import pytest

from poste.backtest.donnees import ecrire_csv
from poste.backtest.moteur import Barre, Config, simuler
from poste.backtest.rapport import INSTRUMENTS, generer_rapport
from poste.backtest.verdict import MARGE_MIN_EUR, evaluer_walk_forward
from poste.backtest.walkforward import Etape, WalkForward, walk_forward
from tests.test_backtest import SANS_COUTS, montee, serie
from tests.test_backtest_rapport import marche_aleatoire

# ---------- stop suiveur ----------

HAUSSE_PUIS_CHUTE = montee(60) + list(range(160, 201)) + [192 - 8 * k for k in range(10)]  # 100 -> 200 -> 120


def _trade(suiveur: bool):
    cfg = Config(filtre_mm50=False, stop="pct", stop_pct=10, sortie="tenir", stop_suiveur=suiveur)
    return simuler(serie(HAUSSE_PUIS_CHUTE), cfg, SANS_COUTS, montant=100, premier_jour=50).trades[0]


def test_stop_suiveur_verrouille_le_gain():
    t = _trade(suiveur=True)
    # entrée 149, distance du stop 14,9 : le stop suit la clôture maximale 200 -> 185,1
    assert t.sorties[-1].raison == "stop"
    assert t.sorties[-1].prix == pytest.approx(200 - 14.9)
    assert t.pnl == pytest.approx(100 / 149 * (185.1 - 149))
    assert t.pnl > 0


def test_stop_fixe_rend_le_gain():
    t = _trade(suiveur=False)
    assert t.sorties[-1].prix == pytest.approx(149 * 0.9)
    assert t.pnl < 0  # le même trade, sans stop suiveur, finit en perte


def test_stop_suiveur_dans_le_libelle():
    assert "suiveur" in Config(filtre_mm50=True, stop="atr", sortie="tenir", stop_suiveur=True).libelle()
    assert "suiveur" not in Config(filtre_mm50=True, stop="atr", sortie="tenir").libelle()


def test_stop_suiveur_n_utilise_pas_la_seance_en_cours():
    # séance 51 : plus haut à 300 (!) mais clôture à 150 : seule la clôture fait monter le stop
    b = serie(montee(52))
    b[51] = Barre(b[51].jour, 150.0, 300.0, 140.0, 150.0)
    b.append(Barre(b[51].jour + timedelta(days=1), 150.0, 150.0, 125.0, 126.0))
    cfg = Config(filtre_mm50=False, stop="pct", stop_pct=10, sortie="tenir", stop_suiveur=True)
    t = simuler(b, cfg, SANS_COUTS, montant=100, premier_jour=50).trades[0]
    # stop = 150 - 14,9 = 135,1 ; s'il avait utilisé le plus haut de 300 il serait à 285,1 (vente à 150)
    assert t.sorties[-1].prix == pytest.approx(150 - 14.9)


# ---------- verdict du walk-forward ----------

CFG = Config(filtre_mm50=True, stop="pct", sortie="objectifs")


def _etapes(n=9, choisi=100.0, plan=50.0, trades=5, variation=10.0, cfg=None):
    return [Etape((2015 + k, 2017 + k), (2018 + k, 2018 + k), cfg or CFG, choisi, plan, trades, variation)
            for k in range(n)]


def test_verdict_retenu_si_net_regulier_stable_et_protecteur():
    ev = evaluer_walk_forward(WalkForward(_etapes()))
    assert ev.retenue and ev.raisons == []


def test_verdict_echantillon_insuffisant():
    ev = evaluer_walk_forward(WalkForward(_etapes(trades=2)))
    assert not ev.retenue and "échantillon insuffisant" in ev.raisons[0]


def test_verdict_ecart_trop_faible():
    ev = evaluer_walk_forward(WalkForward(_etapes(choisi=55.0, plan=50.0)))  # +45 € au total
    assert not ev.retenue
    assert any("écart trop faible" in r for r in ev.raisons)
    assert MARGE_MIN_EUR >= 100


def test_verdict_pas_assez_regulier():
    etapes = _etapes()
    for e in etapes[:4]:
        e.pnl_test_choisie = 600.0   # quelques très grosses années...
    for e in etapes[4:]:
        e.pnl_test_choisie = 45.0    # ...et le reste un peu en dessous du plan
    ev = evaluer_walk_forward(WalkForward(etapes))
    assert not ev.retenue and any("régulier" in r for r in ev.raisons)


def test_verdict_refuse_une_regle_moins_protectrice_en_annee_de_baisse():
    etapes = _etapes()
    for k in (0, 4):  # deux années de baisse où la règle choisie perd beaucoup plus que le plan
        etapes[k].variation_test_pct = -30.0
        etapes[k].pnl_test_choisie = -300.0
        etapes[k].pnl_test_plan = -10.0
    ev = evaluer_walk_forward(WalkForward(etapes))
    assert not ev.retenue
    protection = next(r for r in ev.raisons if "protectrice" in r)
    assert "2018" in protection and "2022" in protection


def test_verdict_regle_instable():
    cfgs = [Config(filtre_mm50=True, stop="pct", sortie="objectifs", stop_pct=5.0 + k) for k in range(9)]
    etapes = [Etape((2015 + k, 2017 + k), (2018 + k, 2018 + k), cfgs[k], 100.0, 50.0, 5, 10.0) for k in range(9)]
    ev = evaluer_walk_forward(WalkForward(etapes))
    assert not ev.retenue and any("stable" in r for r in ev.raisons)


def test_regle_la_plus_frequente():
    a = Config(filtre_mm50=True, stop="pct", sortie="objectifs")
    b = Config(filtre_mm50=False, stop="atr", sortie="tenir", stop_suiveur=True)
    wf = WalkForward([Etape((2015, 2017), (2018, 2018), c, 0.0, 0.0, 1, 0.0) for c in (a, b, b, b, a)])
    assert wf.regle_la_plus_frequente() == (b, 3)


def test_walk_forward_donne_la_variation_de_l_annee_de_test():
    barres = serie(montee(365 * 6, pas=0.5), debut=date(2015, 1, 1))
    wf = walk_forward(barres, [CFG], CFG, SANS_COUTS, montant=100, apprentissage=3, test=1)
    e = wf.etapes[0]
    assert e.test_annees == (2018, 2018)
    idx = [i for i, x in enumerate(barres) if x.jour.year == 2018]
    attendu = (barres[idx[-1]].c / barres[idx[0]].o - 1) * 100
    assert e.variation_test_pct == pytest.approx(attendu)


# ---------- rapport : avertissements ----------

@pytest.fixture
def rapport(tmp_path):
    for k, inst in enumerate(INSTRUMENTS):
        ecrire_csv(marche_aleatoire(2900, k + 20), tmp_path / f"{inst.fichier}.csv")
    return generer_rapport(tmp_path)


def test_rapport_avertit_du_biais_du_survivant(rapport):
    assert "biais du survivant" in rapport.lower()


def test_rapport_avertit_des_jours_calendaires_du_bitcoin(rapport):
    bitcoin = rapport[rapport.index("## Bitcoin"):rapport.index("## Nasdaq-100")]
    assert "jours calendaires" in bitcoin and "week-end" in bitcoin


def test_rapport_avertit_de_l_hypothese_de_stop_du_turbo(rapport):
    turbo = rapport[rapport.index("### d) Turbo"):]
    assert "suppose que ton stop" in turbo


def test_rapport_compare_stop_fixe_et_stop_suiveur(rapport):
    assert "tenir sans objectif, stop fixe" in rapport
    assert "tenir sans objectif, stop suiveur" in rapport
    assert "Règle choisie le plus souvent" in rapport


def test_rapport_ne_conclut_plus_sur_un_petit_ecart(rapport):
    # le vieux verdict « choisir la règle sur le passé a fait mieux » est remplacé par des critères explicites
    assert "choisir la règle sur le passé a fait mieux" not in rapport
