"""Rapport du backtest, en phrases simples. Ne lit que les fichiers CSV présents : si un fichier
manque, le rapport le dit et ne montre aucun chiffre pour cet instrument."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from poste.backtest.donnees import charger_csv
from poste.backtest.mesures import ECHANTILLON_MIN, mesurer
from poste.backtest.moteur import Barre, Config, Couts, simuler
from poste.backtest.turbo import fenetres_turbo
from poste.backtest.walkforward import walk_forward

MONTANT = 625.0     # montant par trade du niveau 1
CAPITAL = 2500.0
DOSSIER = Path(__file__).resolve().parent.parent.parent / "historique"


@dataclass(frozen=True)
class Instrument:
    nom: str
    symbole: str
    fichier: str
    stop_pct: float
    objectifs: tuple[float, ...]
    ecart_pct: float
    turbo: bool = False
    note: str = ""


INSTRUMENTS = [
    Instrument("Nvidia", "NVDA", "NVDA", 10, (12, 25), 0.1),
    Instrument("ETF semi-conducteurs", "SOXX", "SOXX", 10, (12, 25), 0.2,
               note="SOXX (version américaine) sert d'approximation : les ETF UCITS ont un historique plus court."),
    Instrument("Bitcoin", "BTC-USD", "BTC-USD", 15, (20, 40), 0.5,
               note="Le cours du bitcoin sert d'approximation de l'ETP ; les frais annuels de l'ETP ne sont pas comptés."),
    Instrument("Nasdaq-100", "^NDX", "NDX", 10, (12, 25), 0.1, turbo=True),
]

REGIMES = [
    ("2018", date(2018, 1, 1), date(2018, 12, 31)),
    ("2020", date(2020, 1, 1), date(2020, 12, 31)),
    ("2022", date(2022, 1, 1), date(2022, 12, 31)),
    ("juillet 2026", date(2026, 7, 1), date(2026, 7, 31)),
]


def _cfg_plan(inst: Instrument, **kw) -> Config:
    base = dict(filtre_mm50=True, stop="pct", sortie="objectifs", stop_pct=inst.stop_pct, objectifs=inst.objectifs)
    base.update(kw)
    return Config(**base)


def _grille(inst: Instrument) -> list[Config]:
    return [_cfg_plan(inst, filtre_mm50=f, stop=s, sortie=so)
            for f in (True, False) for s in ("pct", "atr", "bas10") for so in ("objectifs", "tenir")]


def _indices(barres: list[Barre], d0: date, d1: date) -> Optional[tuple[int, int]]:
    idx = [i for i, b in enumerate(barres) if d0 <= b.jour <= d1]
    return (idx[0], idx[-1]) if idx else None


def _mesure(barres, cfg, couts, i0=50, i1=None):
    return mesurer(simuler(barres, cfg, couts, montant=MONTANT, premier_jour=max(i0, 50), dernier_jour=i1,
                           capital=CAPITAL), capital=CAPITAL)


def _section_instrument(inst: Instrument, barres: list[Barre]) -> tuple[list[str], str]:
    couts = Couts(frais_ordre=1.0, ecart_pct=inst.ecart_pct)
    plan = _cfg_plan(inst)
    L = [f"## {inst.nom} ({inst.fichier}.csv : {barres[0].jour} → {barres[-1].jour}, {len(barres)} séances)", ""]
    if inst.note:
        L += [f"_{inst.note}_", ""]
    variation = (barres[-1].c / barres[50].o - 1) * 100
    L += [f"Repère « acheter et garder » {MONTANT:.0f} € : {MONTANT * variation / 100:+.0f} € ({variation:+.0f} %),"
          " sans stop : la pire baisse subie en chemin peut être énorme.", ""]

    def bloc(titre, cas):
        L.append(f"### {titre}")
        for lib, cfg in cas:
            L.append(f"- {lib} : {_mesure(barres, cfg, couts).ligne()}")
        L.append("")

    bloc("a) Filtre MM50 (stop et objectifs du plan)",
         [("au-dessus de la MM50 seulement", plan), ("sans filtre", _cfg_plan(inst, filtre_mm50=False))])
    bloc("b) Stop (filtre MM50, objectifs du plan)",
         [(f"−{inst.stop_pct:g} %", plan), ("2 × ATR 14", _cfg_plan(inst, stop="atr")),
          ("sous le plus bas des 10 séances", _cfg_plan(inst, stop="bas10"))])
    objs = "/".join(f"+{o:g} %" for o in inst.objectifs)
    bloc("c) Objectifs (filtre MM50, stop du plan)",
         [(f"objectifs {objs} puis stop remonté au prix d'achat", plan),
          ("tenir sans objectif (sortie au stop seulement)", _cfg_plan(inst, sortie="tenir"))])

    wf = walk_forward(barres, _grille(inst), plan, couts, montant=MONTANT)
    L.append("### Walk-forward (3 ans d'apprentissage, puis 1 an de test jamais vu)")
    if not wf.etapes:
        L += ["Historique trop court pour un walk-forward.", ""]
        verdict = f"{inst.nom} : historique trop court, on garde le plan tel quel (non testé)."
        return L, verdict
    for e in wf.etapes:
        L.append(f"- apprend {e.apprentissage_annees[0]}–{e.apprentissage_annees[1]}, teste {e.test_annees[0]} :"
                 f" règle choisie « {e.choisie.libelle()} » → {e.pnl_test_choisie:+.0f} € ;"
                 f" plan → {e.pnl_test_plan:+.0f} €")
    trades_hors = sum(e.trades_test_choisie for e in wf.etapes)
    L += [f"- Total hors échantillon : règle choisie {wf.pnl_choisie:+.0f} €, plan {wf.pnl_plan:+.0f} €,"
          f" la règle choisie fait mieux {wf.annees_gagnees} année(s) sur {len(wf.etapes)}"
          f" ({trades_hors} trades testés).", ""]

    L.append("### Régimes de marché")
    for nom, d0, d1 in REGIMES:
        ix = _indices(barres, d0, d1)
        if ix is None or ix[0] < 50:
            L.append(f"- {nom} : pas de données pour cette période.")
            continue
        var = (barres[ix[1]].c / barres[ix[0]].o - 1) * 100
        m_p = _mesure(barres, plan, couts, *ix)
        m_s = _mesure(barres, _cfg_plan(inst, filtre_mm50=False), couts, *ix)
        L.append(f"- {nom} (l'instrument a fait {var:+.0f} %) : plan {m_p.ligne()} ; sans filtre {m_s.ligne()}")
    L.append("")

    # Verdict : on ne change un seuil que si l'amélioration tient HORS échantillon, de façon régulière.
    m_plan = _mesure(barres, plan, couts)
    regulier = wf.annees_gagnees > len(wf.etapes) / 2
    if trades_hors < ECHANTILLON_MIN:
        verdict = (f"{inst.nom} : échantillon insuffisant hors échantillon ({trades_hors} trades) :"
                   " on garde les seuils du plan, sans preuve qu'ils marchent.")
    elif wf.pnl_choisie > wf.pnl_plan and regulier:
        verdict = (f"{inst.nom} : choisir la règle sur le passé a fait mieux que le plan hors échantillon"
                   f" ({wf.pnl_choisie:+.0f} € contre {wf.pnl_plan:+.0f} €, {wf.annees_gagnees}/{len(wf.etapes)} années)."
                   " Regarde quelle règle revient le plus souvent ci-dessus ; on n'en change qu'avec ton accord.")
    else:
        verdict = (f"{inst.nom} : aucune alternative ne fait mieux de façon régulière hors échantillon :"
                   " on garde les seuils du plan.")
    if m_plan.rendement_eur < 0:
        verdict += f" Attention : le plan lui-même perd de l'argent sur la période ({m_plan.rendement_eur:+.0f} €)."
    L += ["### Verdict", verdict, ""]
    return L, verdict


def _section_turbo(barres: list[Barre]) -> tuple[list[str], str]:
    L = ["### d) Turbo long Nasdaq-100 (fenêtres de 6 semaines = 30 séances)",
         "Hypothèses : barrière = niveau de financement, financement 5 %/an, écart 0,5 %, 2 € de frais sur"
         " ~70 € de mise (≈ 2,8 %), stop à −20 % sur le turbo, filtre MM50. Désactivation = mise perdue."
         " Tout cela est à vérifier dans la fiche du produit.", ""]
    resultats = []
    for dist in (25, 33):
        r = fenetres_turbo(barres, distance_pct=dist, objectifs=(30, 60), duree=30, financement_annuel_pct=5,
                           stop_pct=20, filtre_mm50=True, ecart_pct=0.5, frais_pct_aller_retour=2.8)
        resultats.append(r)
        insuff = " · ÉCHANTILLON INSUFFISANT" if r.nb_fenetres_independantes < ECHANTILLON_MIN else ""
        L.append(f"- Barrière à {dist} % sous le cours : {r.nb_fenetres} fenêtres"
                 f" ({r.nb_fenetres_independantes} sans chevauchement){insuff}")
        for o in (30, 60):
            L.append(f"  - objectif +{o} % : il faut environ +{r.hausse_necessaire_pct[o]:.1f} % du Nasdaq."
                     f" Atteint dans {r.part_atteinte[o] * 100:.0f} % des fenêtres ;"
                     f" résultat moyen de la stratégie {r.resultat_moyen_pct[o]:+.1f} % par turbo,"
                     f" gagnante {r.part_gagnante[o] * 100:.0f} % du temps ; avant l'objectif :"
                     f" stop −20 % dans {r.part_stop[o] * 100:.0f} %, désactivé (mise perdue)"
                     f" dans {r.part_knock_out[o] * 100:.0f} %")
    L.append("")
    meilleur = max(((r, o) for r in resultats for o in (30, 60)), key=lambda x: x[0].resultat_moyen_pct[x[1]])
    r60 = resultats[0]
    verdict = (f"Turbo : l'objectif +60 % (≈ +{r60.hausse_necessaire_pct[60]:.0f} % du Nasdaq avec une barrière à 25 %)"
               f" n'est atteint que dans {r60.part_atteinte[60] * 100:.0f} % des fenêtres de 6 semaines. "
               f"Meilleure combinaison mesurée : barrière {meilleur[0].distance_pct:g} %, objectif +{meilleur[1]} %"
               f" ({meilleur[0].resultat_moyen_pct[meilleur[1]]:+.1f} % en moyenne, coûts compris).")
    if min(r.nb_fenetres_independantes for r in resultats) < ECHANTILLON_MIN:
        verdict += " Échantillon insuffisant pour conclure."
    return L + ["### Verdict turbo", verdict, ""], verdict


def generer_rapport(dossier: Path = DOSSIER) -> str:
    dossier = Path(dossier)
    L = ["# Backtest honnête des règles du plan", "",
         "Aide à la décision, pas un conseil financier. Les résultats passés ne disent pas ce qui arrivera.",
         f"Mise de {MONTANT:.0f} € par trade (niveau 1), capital {CAPITAL:.0f} €, 1 € par ordre, écart achat-vente"
         " compté. Décisions prises uniquement avec les séances passées ; achat à l'ouverture suivante ;"
         " un gap sous le stop vend à l'ouverture. En dessous de"
         f" {ECHANTILLON_MIN} trades, un résultat est marqué « échantillon insuffisant ».", ""]
    verdicts = []
    for inst in INSTRUMENTS:
        f = dossier / f"{inst.fichier}.csv"
        if not f.exists():
            L += [f"## {inst.nom}", f"Données absentes ({f.name}) : lance `python -m poste.backtest telecharger`.", ""]
            verdicts.append(f"{inst.nom} : données absentes, rien n'est conclu.")
            continue
        barres = charger_csv(f)
        if len(barres) < 300:
            L += [f"## {inst.nom}", f"Échantillon insuffisant : {len(barres)} séances seulement.", ""]
            verdicts.append(f"{inst.nom} : échantillon insuffisant.")
            continue
        sec, v = _section_instrument(inst, barres)
        L += sec
        verdicts.append(v)
        if inst.turbo:
            sec_t, v_t = _section_turbo(barres)
            L += sec_t
            verdicts.append(v_t)
    L += ["# Verdict", ""] + [f"- {v}" for v in verdicts] + [
        "", "Aucun seuil n'est modifié automatiquement : un changement demande une amélioration hors échantillon"
        " ET ton accord écrit."]
    return "\n".join(L)
