"""Tableau de risque, calculé depuis le journal."""
from dataclasses import dataclass
from decimal import Decimal

from poste.exposition import Exposition, Position as PositionExpo, calculer_exposition
from poste.journal import Journal
from poste.plan import Plan


@dataclass
class TableauRisque:
    montant_investi_eur: Decimal
    perte_si_stops_eur: Decimal          # négatif = gain verrouillé par des stops remontés
    perte_cumulee_eur: Decimal
    seuil_arret_eur: Decimal
    distance_seuil_eur: Decimal          # ce qu'il reste avant l'arrêt des achats
    distance_seuil_pire_cas_eur: Decimal  # idem si tous les stops sautent maintenant
    exposition: Exposition

    def texte(self) -> str:
        l = ["=== TABLEAU DE RISQUE ===",
             f"Montant investi (prix d'achat) : {self.montant_investi_eur} €",
             f"Perte si tous les stops sautent : {self.perte_si_stops_eur} € (frais compris, hors gap)",
             f"Perte cumulée réalisée : {self.perte_cumulee_eur} € / seuil d'arrêt {self.seuil_arret_eur} €",
             f"Distance au seuil d'arrêt : {self.distance_seuil_eur} €"
             f" ({self.distance_seuil_pire_cas_eur} € si tous les stops sautent)"]
        if self.distance_seuil_eur <= 0:
            l.append("SEUIL ATTEINT : plus aucun achat.")
        elif self.distance_seuil_pire_cas_eur <= 0:
            l.append("ATTENTION : si tous les stops sautent, le seuil d'arrêt sera atteint.")
        l.append(self.exposition.texte())
        l.append("Aide à la décision, pas un conseil financier.")
        return "\n".join(l)


def tableau_risque(journal: Journal, plan: Plan, niveau: int) -> TableauRisque:
    frais = plan.frais_par_ordre_eur
    ouvertes = journal.ouvertes()
    investi = sum((p.quantite_restante * p.achat.prix_execution_eur for p in ouvertes), Decimal("0"))
    perte_stops = sum((p.quantite_restante * (p.achat.prix_execution_eur - p.stop_courant) + frais
                       for p in ouvertes), Decimal("0"))
    perte_cum = journal.perte_cumulee()
    seuil = plan.niveau(niveau).seuil_arret_perte_cumulee_eur
    themes = {t.id: t.theme for t in plan.trades}
    expo = calculer_exposition(
        [PositionExpo(instrument=p.achat.trade_id, theme=themes[p.achat.trade_id],
                      valeur_eur=p.quantite_restante * p.achat.prix_execution_eur)
         for p in ouvertes if p.achat.trade_id in themes],
        plan.capital_eur)
    return TableauRisque(investi, perte_stops, perte_cum, seuil, seuil - perte_cum,
                         seuil - perte_cum - max(perte_stops, Decimal("0")), expo)
