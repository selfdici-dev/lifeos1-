"""Bilan hebdomadaire (vendredi 22:05, heure de Paris) : discipline et erreurs récurrentes.
Aucun seuil n'est ajusté automatiquement, et rien n'est même proposé avant 30 trades mesurés."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from poste.journal import Journal
from poste.plan import Plan
from poste.regles import FUSEAU

AJUSTEMENT_MIN_TRADES = 30
ERREURS = ("stop descendu", "achat hors fourchette", "achat un jour interdit", "achat sans fiche FEU VERT")


def periode_bilan(fin: datetime) -> tuple[datetime, datetime]:
    """La semaine qui se termine à `fin` (7 jours glissants, en heure de Paris)."""
    fin = fin.astimezone(FUSEAU)
    debut = (fin - timedelta(days=7)).replace(hour=fin.hour, minute=fin.minute)
    return debut, fin


@dataclass
class Bilan:
    debut: datetime
    fin: datetime
    suivis: int
    ignores: int
    erreurs: dict[str, int]
    resultat_semaine_eur: Decimal
    trades_mesures: int
    details: list[str] = field(default_factory=list)

    def texte(self) -> str:
        l = [f"=== BILAN du {self.debut:%d/%m %H:%M} au {self.fin:%d/%m %H:%M} (Paris) ===",
             f"Fiches FEU VERT suivies : {self.suivis} · ignorées : {self.ignores}",
             f"Résultat encaissé cette semaine : {self.resultat_semaine_eur} €",
             "Erreurs :"]
        l += [f"  - {e} : {n}" for e, n in self.erreurs.items()]
        l += [f"    · {d}" for d in self.details]
        l.append(f"Trades mesurés : {self.trades_mesures}/{AJUSTEMENT_MIN_TRADES}.")
        if self.trades_mesures < AJUSTEMENT_MIN_TRADES:
            l.append("Aucun ajustement des seuils : pas assez de trades pour conclure.")
        else:
            l.append("Assez de trades pour en discuter, mais aucun ajustement n'est automatique.")
        l.append("Aide à la décision, pas un conseil financier.")
        return "\n".join(l)


def bilan_hebdo(journal: Journal, plan: Plan, fin: datetime) -> Bilan:
    debut, fin = periode_bilan(fin)
    dans = lambda t: debut < t <= fin  # noqa: E731
    fiches = {f.id: f for f in journal.fiches}
    erreurs = {e: 0 for e in ERREURS}
    details = []

    achats_semaine = [p for p in journal.positions if dans(p.achat.quand)]
    fiches_suivies = {p.achat.fiche_id for p in journal.positions if p.achat.fiche_id}
    vertes = [f for f in journal.fiches if f.verdict == "FEU VERT" and dans(f.quand)]
    suivis = sum(1 for f in vertes if f.id in fiches_suivies)

    for p in achats_semaine:
        a = p.achat
        fiche = fiches.get(a.fiche_id) if a.fiche_id else None
        if fiche is None or fiche.verdict != "FEU VERT":
            erreurs["achat sans fiche FEU VERT"] += 1
            details.append(f"{p.id} {a.trade_id} : acheté sans fiche FEU VERT")
        elif fiche.prix_limite_eur is not None and a.prix_execution_eur > fiche.prix_limite_eur:
            erreurs["achat hors fourchette"] += 1
            details.append(f"{p.id} {a.trade_id} : payé {a.prix_execution_eur} € > limite {fiche.prix_limite_eur} €")
        # dernière fiche du même instrument dans les 24 h avant l'achat
        avant = [f for f in journal.fiches
                 if f.trade_id == a.trade_id and a.quand - timedelta(hours=24) <= f.quand <= a.quand]
        if avant and max(avant, key=lambda f: f.quand).verdict == "INTERDIT":
            erreurs["achat un jour interdit"] += 1
            details.append(f"{p.id} {a.trade_id} : acheté alors que la fiche disait INTERDIT")

    for p in journal.positions:
        if p.stop_descendu and any(dans(s.quand) for s in p.stops):
            erreurs["stop descendu"] += 1
            details.append(f"{p.id} {p.achat.trade_id} : stop descendu")

    resultat = Decimal("0")
    for p in journal.positions:
        for v in p.ventes:
            if dans(v.quand):
                resultat += v.quantite * (v.prix_eur - p.achat.prix_execution_eur) - journal.frais
    return Bilan(debut, fin, suivis, len(vertes) - suivis, erreurs, resultat, journal.nb_trades_fermes(), details)
