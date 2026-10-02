"""Historique quotidien : fichiers CSV (Date,Open,High,Low,Close), ajustés des divisions d'actions.

Le téléchargement passe par yfinance, à lancer sur ton ordinateur :
  python -m poste.backtest telecharger
"""
import csv
import math
from datetime import date
from pathlib import Path

from poste.backtest.moteur import Barre

DEBUT = "2015-01-01"


def ecrire_csv(barres: list[Barre], chemin: Path) -> None:
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Open", "High", "Low", "Close"])
        for b in barres:
            w.writerow([b.jour.isoformat(), round(b.o, 6), round(b.h, 6), round(b.l, 6), round(b.c, 6)])


def charger_csv(chemin: Path) -> list[Barre]:
    """Refuse un fichier douteux plutôt que de backtester sur des données fausses."""
    barres: list[Barre] = []
    with Path(chemin).open(encoding="utf-8") as f:
        for n, ligne in enumerate(csv.DictReader(f), start=2):
            try:
                j = date.fromisoformat(ligne["Date"][:10])
                o, h, l, c = (float(ligne[k]) for k in ("Open", "High", "Low", "Close"))
            except (KeyError, ValueError) as e:
                raise ValueError(f"{chemin} ligne {n} illisible") from e
            if not all(math.isfinite(x) and x > 0 for x in (o, h, l, c)):
                raise ValueError(f"{chemin} ligne {n} : prix manquant ou négatif")
            if h < max(o, c) - 1e-9 or l > min(o, c) + 1e-9:
                raise ValueError(f"{chemin} ligne {n} : plus haut / plus bas incohérents")
            if barres and j <= barres[-1].jour:
                raise ValueError(f"{chemin} ligne {n} : dates dans le désordre ou en double")
            barres.append(Barre(j, o, h, l, c))
    return barres


def telecharger(symbole: str, chemin: Path) -> int:
    import yfinance as yf
    df = yf.Ticker(symbole).history(start=DEBUT, interval="1d", auto_adjust=True)
    if df is None or df.empty:
        raise RuntimeError(f"aucune donnée pour {symbole}")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    barres = []
    for ix, r in df.iterrows():
        o, h, l, c = float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"])
        # yfinance arrondit parfois le plus haut/bas sous l'ouverture ajustée : on corrige au plus juste
        barres.append(Barre(ix.date(), o, max(h, o, c), min(l, o, c), c))
    ecrire_csv(barres, chemin)
    return len(barres)
