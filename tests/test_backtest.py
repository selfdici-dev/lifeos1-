"""Phase 3 : moteur de backtest, testé sur des séries synthétiques où l'on connaît la bonne réponse."""
import math
from datetime import date, timedelta

import pytest

from poste.backtest.moteur import Barre, Config, Couts, simuler
from poste.backtest.mesures import mesurer, ECHANTILLON_MIN
from poste.backtest.walkforward import decoupages, walk_forward
from poste.backtest.turbo import fenetres_turbo, valeur_turbo

SANS_COUTS = Couts(frais_ordre=0.0, ecart_pct=0.0)


def serie(closes, debut=date(2020, 1, 1), ecart=0.0):
    """Barres où open = close de la veille, high/low = max/min(open, close) ± ecart."""
    barres, prec = [], closes[0]
    for i, c in enumerate(closes):
        o = prec
        barres.append(Barre(debut + timedelta(days=i), o, max(o, c) + ecart, min(o, c) - ecart, c))
        prec = c
    return barres


def montee(n=60, depart=100.0, pas=1.0):
    return [depart + pas * i for i in range(n)]


BASE = Config(filtre_mm50=False, stop="pct", stop_pct=10, sortie="tenir")


# ---------- règles d'entrée et de sortie ----------

def test_stop_pourcentage_execute_au_prix_du_stop():
    closes = montee(55) + [150.0, 140.0, 120.0]  # chute progressive : le stop est touché en séance
    r = simuler(serie(closes), BASE, SANS_COUTS, montant=100, premier_jour=50)
    t = r.trades[0]
    assert t.entree_jour == date(2020, 1, 1) + timedelta(days=50)
    assert t.prix_entree == pytest.approx(closes[49])
    assert t.sorties[0].raison == "stop"
    assert t.sorties[0].prix == pytest.approx(t.prix_entree * 0.9)
    assert t.pnl == pytest.approx(-10.0)  # 100 € investis, -10 %


def test_gap_sous_le_stop_sort_a_l_ouverture():
    b = serie(montee(52))
    entree = b[50].o
    # séance 51 : ouverture directement 30 % plus bas
    b[51] = Barre(b[51].jour, entree * 0.7, entree * 0.72, entree * 0.69, entree * 0.71)
    r = simuler(b, BASE, SANS_COUTS, montant=100, premier_jour=50)
    s = r.trades[0].sorties[0]
    assert s.raison == "stop (gap)" and s.prix == pytest.approx(entree * 0.7)
    assert r.trades[0].pnl < -10  # la perte dépasse le stop théorique


def test_objectifs_puis_stop_remonte_au_prix_d_achat():
    b = serie(montee(51))
    e = b[50].o
    jours = [b[50].jour + timedelta(days=k) for k in range(1, 4)]
    b += [Barre(jours[0], e, e * 1.13, e * 0.99, e * 1.12),   # touche +12 %
          Barre(jours[1], e * 1.12, e * 1.12, e * 0.99, e),    # redescend : stop remonté au prix d'achat
          Barre(jours[2], e, e, e, e)]
    cfg = Config(filtre_mm50=False, stop="pct", stop_pct=10, sortie="objectifs", objectifs=(12, 25))
    r = simuler(b, cfg, SANS_COUTS, montant=100, premier_jour=50)
    t = r.trades[0]
    assert [s.raison for s in t.sorties] == ["objectif 1", "stop"]
    assert t.sorties[0].fraction == pytest.approx(0.5)
    assert t.sorties[1].prix == pytest.approx(e)
    assert t.pnl == pytest.approx(6.0)  # moitié à +12 %, moitié à 0


def test_filtre_mm50_bloque_en_tendance_baissiere():
    b = serie([200.0 - i for i in range(120)])
    sans = simuler(b, BASE, SANS_COUTS, montant=100, premier_jour=50)
    avec = simuler(b, Config(filtre_mm50=True, stop="pct", stop_pct=10, sortie="tenir"), SANS_COUTS,
                   montant=100, premier_jour=50)
    assert len(sans.trades) >= 1
    assert avec.trades == []


def test_couts_frais_et_ecart():
    closes = montee(55) + [150.0, 140.0, 120.0]
    couts = Couts(frais_ordre=1.0, ecart_pct=0.2)
    r = simuler(serie(closes), BASE, couts, montant=100, premier_jour=50)
    t = r.trades[0]
    assert t.prix_entree == pytest.approx(closes[49] * 1.001)  # achat au prix vendeur : +½ écart
    assert t.frais == pytest.approx(2.0)
    brut = simuler(serie(closes), BASE, SANS_COUTS, montant=100, premier_jour=50).trades[0].pnl
    assert t.pnl < brut - 2.0


def test_stop_atr_et_plus_bas_10_seances_calcules_sur_le_passe():
    b = serie(montee(60), ecart=2.0)
    r_atr = simuler(b, Config(filtre_mm50=False, stop="atr", atr_mult=2, sortie="tenir"), SANS_COUTS,
                    montant=100, premier_jour=50)
    # amplitude vraie = 1 (pas) + 2×2 (écart) = 5 sur chaque séance -> ATR 14 = 5 -> stop = entrée - 10
    assert r_atr.trades[0].stop_initial == pytest.approx(r_atr.trades[0].prix_entree - 10)
    r_bas = simuler(b, Config(filtre_mm50=False, stop="bas10", sortie="tenir"), SANS_COUTS,
                    montant=100, premier_jour=50)
    assert r_bas.trades[0].stop_initial == pytest.approx(min(x.l for x in b[40:50]))


def test_position_fermee_en_fin_de_periode():
    r = simuler(serie(montee(80)), BASE, SANS_COUTS, montant=100, premier_jour=50)
    assert r.trades[-1].sorties[-1].raison == "fin de période"


# ---------- aucune fuite du futur ----------

def test_aucune_fuite_du_futur():
    import random
    rnd = random.Random(1)
    closes, x = [], 100.0
    for _ in range(400):
        x *= math.exp(rnd.gauss(0.0005, 0.02))
        closes.append(x)
    b = serie(closes, ecart=0.5)
    T = 250
    futur_modifie = b[:T] + [Barre(z.jour, z.o * 3, z.h * 3, z.l * 3, z.c * 3) for z in b[T:]]
    for cfg in [Config(filtre_mm50=f, stop=s, sortie=so, stop_suiveur=sv)
                for f in (True, False) for s in ("pct", "atr", "bas10") for so in ("tenir", "objectifs")
                for sv in (False, True)]:
        a = simuler(b, cfg, SANS_COUTS, montant=100, premier_jour=50)
        m = simuler(futur_modifie, cfg, SANS_COUTS, montant=100, premier_jour=50)
        avant = lambda r: [(t.entree_jour, t.prix_entree, t.stop_initial) for t in r.trades if t.entree_jour < b[T].jour]
        assert avant(a) == avant(m)
        # les décisions d'entrée du jour T elles-mêmes ne lisent pas la séance T (sauf son ouverture)


# ---------- mesures ----------

def test_mesures_drawdown_et_taux_de_reussite():
    closes = montee(55) + [150.0, 140.0, 120.0]
    r = simuler(serie(closes), BASE, SANS_COUTS, montant=100, premier_jour=50, capital=1000)
    m = mesurer(r, capital=1000)
    assert m.nb_trades == 1 and m.taux_reussite == 0.0
    assert m.rendement_eur == pytest.approx(-10.0)
    assert m.pire_baisse_eur <= -10.0 + 1e-9
    assert m.echantillon_insuffisant  # 1 trade < ECHANTILLON_MIN
    assert ECHANTILLON_MIN >= 30


# ---------- walk-forward ----------

def test_decoupages_sans_melange():
    d = decoupages(2015, 2025, apprentissage=3, test=1)
    assert d[0] == ((2015, 2017), (2018, 2018))
    for (a0, a1), (t0, t1) in d:
        assert a1 < t0  # le test est toujours après l'apprentissage
    assert d[-1][1] == (2025, 2025)


def test_walk_forward_ne_choisit_que_sur_l_apprentissage():
    import random
    rnd = random.Random(2)
    closes, x = [], 100.0
    for _ in range(365 * 8):
        x *= math.exp(rnd.gauss(0.0003, 0.02))
        closes.append(x)
    b = serie(closes, debut=date(2015, 1, 1), ecart=0.5)
    configs = [Config(filtre_mm50=f, stop="pct", sortie="tenir") for f in (True, False)]
    wf = walk_forward(b, configs, configs[0], SANS_COUTS, montant=100, apprentissage=3, test=1)
    for etape in wf.etapes:
        assert etape.choisie in configs
        assert etape.test_annees[0] > etape.apprentissage_annees[1]


# ---------- turbo ----------

def test_valeur_turbo_levier_et_knock_out():
    # barrière à 25 % sous le cours : levier 4 ; +5 % du sous-jacent -> +20 % du turbo
    assert valeur_turbo(105, k=75, depart=100) == pytest.approx(1.20)
    assert valeur_turbo(75, k=75, depart=100) == 0.0
    assert valeur_turbo(60, k=75, depart=100) == 0.0


def test_fenetres_turbo_hausse_necessaire():
    b = serie(montee(200, pas=0.0))  # sous-jacent plat
    res = fenetres_turbo(b, distance_pct=25, objectifs=(30, 60), duree=30, financement_annuel_pct=0, filtre_mm50=False)
    assert res.hausse_necessaire_pct[60] == pytest.approx(15.0)
    assert res.part_atteinte[60] == 0.0 and res.part_atteinte[30] == 0.0
    assert res.nb_fenetres > 0


def test_turbo_issue_comptee_avant_l_objectif():
    # +10 % d'un coup (objectif +30 % atteint avec levier 4), puis chute : le stop d'après ne compte pas
    closes = [100.0] * 60 + [110.0, 80.0] + [80.0] * 40
    b = serie(closes)
    res = fenetres_turbo(b, distance_pct=25, objectifs=(30,), duree=30, financement_annuel_pct=0,
                         filtre_mm50=False, ecart_pct=0, premier=59, dernier=61 + 29)
    assert res.part_atteinte[30] > 0
    assert res.part_atteinte[30] + res.part_stop[30] + res.part_knock_out[30] <= 1.0 + 1e-9


def test_turbo_gap_sous_le_stop_perd_plus_que_le_stop():
    b = serie([100.0] * 100)
    # séance 61 : ouverture directement 10 % plus bas -> levier 4 -> turbo -40 % (stop à -20 % sauté)
    b[61] = Barre(b[61].jour, 90.0, 90.0, 90.0, 90.0)
    b[62:] = [Barre(z.jour, 90.0, 90.0, 90.0, 90.0) for z in b[62:]]
    res = fenetres_turbo(b, distance_pct=25, objectifs=(30,), duree=30, financement_annuel_pct=0,
                         filtre_mm50=False, ecart_pct=0, premier=60, dernier=60 + 30)
    assert res.part_stop[30] == 1.0
    assert res.resultat_moyen_pct[30] == pytest.approx(-40.0)
