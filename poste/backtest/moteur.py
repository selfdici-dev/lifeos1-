"""Moteur de backtest jour par jour, sans fuite du futur.

Décision du jour i : on ne lit que les séances 0..i-1 (clôtures, plus hauts, plus bas) et
l'ouverture de la séance i, qui est le prix auquel on achète. Les montants sont en float : c'est
une simulation statistique, pas un calcul d'ordre (la fiche, elle, travaille en Decimal).

Hypothèses prudentes :
- achat à l'ouverture + la moitié de l'écart achat-vente ; vente − la moitié de l'écart ;
- si l'ouverture est déjà sous le stop (gap), la vente se fait à l'ouverture, pas au stop ;
- si le stop et un objectif sont touchés la même séance, on suppose que le stop est passé en premier ;
- quantités fractionnaires (on mesure des pourcentages ; la vraie fiche arrondit à l'entier).
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional


@dataclass(frozen=True)
class Barre:
    jour: date
    o: float
    h: float
    l: float
    c: float


@dataclass(frozen=True)
class Config:
    filtre_mm50: bool
    stop: Literal["pct", "atr", "bas10"]
    sortie: Literal["objectifs", "tenir"]
    stop_pct: float = 10.0
    atr_mult: float = 2.0
    objectifs: tuple[float, ...] = (12.0, 25.0)
    # stop suiveur : il monte avec la clôture, à la même distance que le stop initial, et ne descend jamais
    stop_suiveur: bool = False

    def libelle(self) -> str:
        stop = {"pct": f"stop −{self.stop_pct:g} %", "atr": f"stop {self.atr_mult:g}×ATR14",
                "bas10": "stop sous le plus bas 10 séances"}[self.stop]
        stop += " suiveur" if self.stop_suiveur else ""
        sortie = ("objectifs " + "/".join(f"+{o:g} %" for o in self.objectifs)) if self.sortie == "objectifs" \
            else "tenir sans objectif"
        return f"{'filtre MM50' if self.filtre_mm50 else 'sans filtre'}, {stop}, {sortie}"


@dataclass(frozen=True)
class Couts:
    frais_ordre: float = 1.0   # € par ordre (à vérifier dans ton appli)
    ecart_pct: float = 0.1     # écart achat-vente total, en %


@dataclass
class Sortie:
    jour: date
    prix: float
    fraction: float
    raison: str


@dataclass
class Trade:
    entree_jour: date
    prix_entree: float
    stop_initial: float
    montant: float
    sorties: list[Sortie] = field(default_factory=list)
    frais: float = 0.0
    pnl: float = 0.0


@dataclass
class Resultat:
    config: Config
    trades: list[Trade]
    equity: list[tuple[date, float]]


def mm(closes: list[float], n: int = 50) -> Optional[float]:
    return sum(closes[-n:]) / n if len(closes) >= n else None


def atr(barres: list[Barre], n: int = 14) -> Optional[float]:
    if len(barres) < n + 1:
        return None
    trs = []
    for prec, b in zip(barres[-n - 1:-1], barres[-n:]):
        trs.append(max(b.h - b.l, abs(b.h - prec.c), abs(b.l - prec.c)))
    return sum(trs) / n


def _stop_initial(cfg: Config, passe: list[Barre], entree: float) -> Optional[float]:
    if cfg.stop == "pct":
        s = entree * (1 - cfg.stop_pct / 100)
    elif cfg.stop == "atr":
        a = atr(passe)
        if a is None:
            return None
        s = entree - cfg.atr_mult * a
    else:
        if len(passe) < 10:
            return None
        s = min(b.l for b in passe[-10:])
    return s if 0 < s < entree else None


def simuler(barres: list[Barre], cfg: Config, couts: Couts, montant: float = 625.0,
            premier_jour: int = 50, dernier_jour: Optional[int] = None, capital: float = 2500.0) -> Resultat:
    """Simule la règle de premier_jour à dernier_jour (inclus). Les séances précédentes ne servent
    qu'aux indicateurs. Une position encore ouverte à la fin est vendue à la dernière clôture."""
    fin = len(barres) - 1 if dernier_jour is None else dernier_jour
    demi = couts.ecart_pct / 200
    trades: list[Trade] = []
    equity: list[tuple[date, float]] = []
    realise = 0.0
    pos: Optional[Trade] = None
    qte = 0.0          # quantité restante
    stop = 0.0
    prochain_obj = 0   # indice du prochain objectif

    def vendre(jour, prix_brut, fraction, raison):
        nonlocal qte, realise
        prix = prix_brut * (1 - demi)
        q = pos.montant / pos.prix_entree * fraction
        gain = q * (prix - pos.prix_entree) - couts.frais_ordre
        pos.sorties.append(Sortie(jour, prix_brut, fraction, raison))
        pos.frais += couts.frais_ordre
        pos.pnl += gain
        realise += gain
        qte -= q

    for i in range(max(premier_jour, 1), fin + 1):
        b = barres[i]
        passe = barres[max(0, i - 260):i]  # uniquement le passé

        if pos is None:
            ok = True
            if cfg.filtre_mm50:
                m = mm([x.c for x in passe])
                ok = m is not None and passe[-1].c > m
            if ok:
                entree = b.o * (1 + demi)
                s = _stop_initial(cfg, passe, entree)
                if s is not None:
                    pos = Trade(b.jour, entree, s, montant)
                    pos.frais = couts.frais_ordre
                    pos.pnl = -couts.frais_ordre
                    realise -= couts.frais_ordre
                    qte = montant / entree
                    stop = s
                    prochain_obj = 0
                    # séance d'entrée : achat à l'ouverture, puis le reste de la séance compte
                    if b.l <= stop:
                        vendre(b.jour, stop, 1.0, "stop")
                        trades.append(pos)
                        pos = None
        else:
            if b.o <= stop:
                vendre(b.jour, b.o, qte * pos.prix_entree / pos.montant, "stop (gap)")
            elif b.l <= stop:
                vendre(b.jour, stop, qte * pos.prix_entree / pos.montant, "stop")
            elif cfg.sortie == "objectifs":
                n_obj = len(cfg.objectifs)
                while prochain_obj < n_obj and qte > 1e-12:
                    cible = pos.prix_entree * (1 + cfg.objectifs[prochain_obj] / 100)
                    if b.h < cible:
                        break
                    prix = max(b.o, cible)  # ouverture au-dessus de l'objectif : vendu à l'ouverture
                    dernier = prochain_obj == n_obj - 1
                    frac = qte * pos.prix_entree / pos.montant if dernier else 0.5
                    vendre(b.jour, prix, frac, f"objectif {prochain_obj + 1}")
                    prochain_obj += 1
                    stop = max(stop, pos.prix_entree)  # stop remonté au prix d'achat
            if qte <= 1e-12:
                trades.append(pos)
                pos = None

        if pos is not None and cfg.stop_suiveur:
            # mis à jour avec la clôture de la séance : il ne sert qu'à partir de la séance suivante
            stop = max(stop, b.c - (pos.prix_entree - pos.stop_initial))

        latent = qte * (b.c * (1 - demi) - pos.prix_entree) if pos else 0.0
        equity.append((b.jour, capital + realise + latent))

    if pos is not None:
        vendre(barres[fin].jour, barres[fin].c, qte * pos.prix_entree / pos.montant, "fin de période")
        trades.append(pos)
        if equity:
            equity[-1] = (equity[-1][0], capital + realise)
    return Resultat(cfg, trades, equity)
