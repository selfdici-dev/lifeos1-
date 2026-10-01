"""Turbo long simplifié : valeur = (sous-jacent − niveau de financement), barrière = niveau de
financement, qui monte chaque jour du coût de financement. Si le plus bas touche la barrière, le
turbo est désactivé et vaut 0 (cas le plus défavorable, à vérifier dans le prospectus du produit)."""
from dataclasses import dataclass

from poste.backtest.moteur import Barre, mm


def valeur_turbo(s: float, k: float, depart: float) -> float:
    """Valeur relative du turbo (1 = prix d'achat) quand le sous-jacent vaut s."""
    return max(s - k, 0.0) / (depart - k)


@dataclass
class ResultatTurbo:
    distance_pct: float
    nb_fenetres: int
    nb_fenetres_independantes: int
    hausse_necessaire_pct: dict[float, float]
    part_atteinte: dict[float, float]       # objectif touché avant désactivation et avant le stop
    part_knock_out: dict[float, float]     # désactivé avant d'avoir atteint l'objectif
    part_stop: dict[float, float]          # stop touché avant d'avoir atteint l'objectif
    resultat_moyen_pct: dict[float, float]  # stratégie : stop / objectif / fin de fenêtre, coûts compris
    part_gagnante: dict[float, float]


def fenetres_turbo(barres: list[Barre], distance_pct: float, objectifs=(30.0, 60.0), duree: int = 30,
                   financement_annuel_pct: float = 5.0, stop_pct: float = 20.0, filtre_mm50: bool = True,
                   ecart_pct: float = 0.5, frais_pct_aller_retour: float = 0.0, premier: int = 50,
                   dernier: int | None = None) -> ResultatTurbo:
    fin = len(barres) - 1 if dernier is None else dernier
    f_jour = financement_annuel_pct / 100 / 365
    atteint = {o: 0 for o in objectifs}
    gains = {o: [] for o in objectifs}
    ko = {o: 0 for o in objectifs}
    stops = {o: 0 for o in objectifs}
    n = 0
    debuts = []
    for i in range(max(premier, 1), fin - duree + 1):
        passe = barres[max(0, i - 60):i]
        if filtre_mm50:
            m = mm([x.c for x in passe])
            if m is None or passe[-1].c <= m:
                continue
        n += 1
        debuts.append(i)
        s0 = barres[i].o
        k0 = s0 * (1 - distance_pct / 100)
        premier_evt = {o: None for o in objectifs}
        sortie_ko = sortie_stop = None
        for j in range(i, i + duree):
            b = barres[j]
            k = k0 * (1 + f_jour * (b.jour - barres[i].jour).days)
            if b.l <= k:
                sortie_ko = j
                break
            if valeur_turbo(b.l, k, s0) <= 1 - stop_pct / 100:
                # gap : si l'ouverture est déjà sous le stop, on vend à l'ouverture
                sortie_stop = min(1 - stop_pct / 100, valeur_turbo(b.o, k, s0)) - 1
                break
            for o in objectifs:
                if premier_evt[o] is None and valeur_turbo(b.h, k, s0) >= 1 + o / 100:
                    premier_evt[o] = j
        fin_fenetre = barres[i + duree - 1]
        k_fin = k0 * (1 + f_jour * (fin_fenetre.jour - barres[i].jour).days)
        for o in objectifs:
            if premier_evt[o] is not None:
                atteint[o] += 1
                r = o / 100
            elif sortie_ko is not None:
                ko[o] += 1
                r = -1.0
            elif sortie_stop is not None:
                stops[o] += 1
                r = sortie_stop
            else:
                r = valeur_turbo(fin_fenetre.c, k_fin, s0) - 1
            gains[o].append(r - ecart_pct / 100 - frais_pct_aller_retour / 100)
    # fenêtres qui ne se chevauchent pas : le vrai nombre d'expériences indépendantes
    indep, dernier_debut = 0, -duree
    for d in debuts:
        if d - dernier_debut >= duree:
            indep += 1
            dernier_debut = d
    return ResultatTurbo(
        distance_pct=distance_pct,
        nb_fenetres=n,
        nb_fenetres_independantes=indep,
        hausse_necessaire_pct={o: o * distance_pct / 100 for o in objectifs},
        part_atteinte={o: atteint[o] / n if n else 0.0 for o in objectifs},
        part_knock_out={o: ko[o] / n if n else 0.0 for o in objectifs},
        part_stop={o: stops[o] / n if n else 0.0 for o in objectifs},
        resultat_moyen_pct={o: (sum(g) / len(g) * 100 if g else 0.0) for o, g in gains.items()},
        part_gagnante={o: (sum(1 for x in g if x > 0) / len(g) if g else 0.0) for o, g in gains.items()},
    )
