"""Phase 3 : chargement de l'historique et rapport (sans réseau)."""
import math
import random
from datetime import date, timedelta

import pytest

from poste.backtest.donnees import charger_csv, ecrire_csv
from poste.backtest.moteur import Barre
from poste.backtest.rapport import INSTRUMENTS, generer_rapport


def marche_aleatoire(n, graine, debut=date(2015, 1, 2), derive=0.0004):
    rnd = random.Random(graine)
    barres, x, j = [], 100.0, debut
    while len(barres) < n:
        if j.weekday() < 5:
            o = x
            x *= math.exp(rnd.gauss(derive, 0.02))
            barres.append(Barre(j, o, max(o, x) * 1.005, min(o, x) * 0.995, x))
        j += timedelta(days=1)
    return barres


def test_csv_aller_retour(tmp_path):
    b = marche_aleatoire(30, 1)
    f = tmp_path / "X.csv"
    ecrire_csv(b, f)
    assert charger_csv(f) == [Barre(z.jour, round(z.o, 6), round(z.h, 6), round(z.l, 6), round(z.c, 6)) for z in b]


@pytest.mark.parametrize("ligne", [
    "2020-01-03,10,9,8,9.5",      # plus haut sous l'ouverture
    "2020-01-03,10,12,8,nan",     # valeur manquante
    "2020-01-03,-1,12,-2,5",      # prix négatif
    "2020-01-01,10,12,8,11",      # date dans le désordre
])
def test_csv_invalide_refuse(tmp_path, ligne):
    f = tmp_path / "X.csv"
    f.write_text("Date,Open,High,Low,Close\n2020-01-02,10,12,8,11\n" + ligne + "\n")
    with pytest.raises(ValueError):
        charger_csv(f)


def test_rapport_sans_donnees_n_invente_rien(tmp_path):
    texte = generer_rapport(tmp_path)
    assert "données absentes" in texte.lower()
    for inst in INSTRUMENTS:
        assert inst.nom in texte


def test_rapport_complet_sur_donnees_synthetiques(tmp_path):
    for k, inst in enumerate(INSTRUMENTS):
        ecrire_csv(marche_aleatoire(2900, k + 10), tmp_path / f"{inst.fichier}.csv")
    texte = generer_rapport(tmp_path)
    for titre in ("a) Filtre", "b) Stop", "c) Objectifs", "d) Turbo", "Walk-forward", "Régimes", "Verdict"):
        assert titre in texte
    assert "2018" in texte and "2020" in texte and "2022" in texte
    assert "juillet 2026" in texte.lower()
    assert "échantillon insuffisant" in texte.lower()  # au moins un régime court
    assert "pas un conseil financier" in texte.lower()
    assert "données synthétiques" not in texte  # le rapport ne sait pas d'où viennent les données : il cite les fichiers
    assert "fenêtres de 6 semaines" in texte
