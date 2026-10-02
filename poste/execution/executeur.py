"""Exécuteur : vérifie les limites, envoie (si le mode le permet), relit l'état réel chez le courtier.

Garde-fous :
- toute réponse inattendue du courtier, des données périmées ou le seuil de perte atteint déclenchent
  l'interrupteur d'arrêt ;
- le journal ne reçoit que ce que le courtier déclare exécuté (jamais le prix limite à la place du prix réel) ;
- un compte réel n'est accepté qu'après la simulation obligatoire et ton autorisation écrite.
"""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

from poste.execution import limites
from poste.execution.arret import Interrupteur
from poste.execution.courtier import STATUTS_CONNUS, Courtier
from poste.execution.modeles import CompteRendu, EtatOrdre, Mode, OrdrePropose
from poste.execution.simulation import RegistreSimulation, porte_ordres_reels
from poste.journal import Achat, Journal
from poste.plan import Plan

ESSAIS_LECTURE = 10


class Executeur:
    def __init__(self, courtier: Courtier, journal: Journal, plan: Plan, niveau: int, mode: Mode,
                 registre: RegistreSimulation, interrupteur: Interrupteur, horloge: Callable[[], datetime],
                 confirmer: Callable[[OrdrePropose], bool], chemin_autorisation: Path,
                 attente: Callable[[float], None]):
        self.courtier = courtier
        self.journal = journal
        self.plan = plan
        self.niveau = niveau
        self.mode = mode
        self.registre = registre
        self.interrupteur = interrupteur
        self.horloge = horloge
        self.confirmer = confirmer
        self.chemin_autorisation = chemin_autorisation
        self.attente = attente

    def arreter(self, raison: str) -> Optional[list[str]]:
        """Interrupteur d'arrêt : bloque tout envoi et annule les achats non exécutés.
        Les stops qui protègent des positions déjà achetées restent chez le courtier.
        Renvoie les ordres annulés, ou None si l'annulation n'a pas pu être confirmée."""
        self.interrupteur.declencher(raison, self.horloge())
        try:
            return self.courtier.annuler_achats_en_attente()
        except Exception as e:  # noqa: BLE001
            self.interrupteur.declencher(f"annulation impossible ({type(e).__name__}) : vérifie chez le courtier",
                                         self.horloge())
            return None

    def envoyer(self, o: OrdrePropose) -> CompteRendu:
        maintenant = self.horloge()
        raisons = []
        if self.interrupteur.actif:  # rien d'autre n'est tenté, pas même une connexion au courtier
            return CompteRendu(False, [f"Arrêt actif : {self.interrupteur.raison}. Reprise : python -m poste reprise."])
        if self.mode is Mode.MANUEL:
            return CompteRendu(False, raisons + ["Mode MANUEL : fiche seulement, aucun envoi."])
        raisons += limites.verifier(o, self.plan, maintenant, self.registre.ordres_du_jour(maintenant))

        # arrêts automatiques
        if o.perimees:
            raisons.append(f"Données périmées ({', '.join(o.perimees)}) : arrêt automatique.")
            self.arreter("données périmées")
        seuil = self.plan.niveau(self.niveau).seuil_arret_perte_cumulee_eur
        baisse = self.journal.perte_cumulee()
        if baisse >= seuil:
            raisons.append(f"Baisse depuis le point haut {baisse} € ≥ seuil {seuil} € : arrêt automatique.")
            self.arreter("seuil de perte atteint")
        try:
            simulation = self.courtier.est_simulation()
        except Exception as e:  # noqa: BLE001
            self.arreter(f"courtier injoignable ({type(e).__name__})")
            return CompteRendu(False, raisons + ["Courtier injoignable : arrêt automatique."])
        if not simulation:
            ok, manque = porte_ordres_reels(self.registre, maintenant, self.chemin_autorisation)
            if not ok:
                raisons.append("Compte RÉEL refusé : la simulation obligatoire n'est pas terminée.")
                raisons += manque
                self.arreter("compte réel sans simulation validée")
        if raisons:
            return CompteRendu(False, raisons)

        if self.mode is Mode.CONFIRMATION and not self.confirmer(o):
            return CompteRendu(False, ["Ordre refusé par toi : rien n'a été envoyé."])

        anomalies: list[str] = []
        try:
            achat_id, stop_id = self.courtier.placer_bracket(o)
        except Exception as e:  # noqa: BLE001
            anomalies.append(f"Erreur du courtier à l'envoi ({type(e).__name__}) : état réel inconnu, vérifie dans TWS.")
            self.registre.noter(maintenant, o, "erreur", anomalies, [], simulation)
            self.arreter("erreur du courtier à l'envoi")
            return CompteRendu(False, anomalies=anomalies, etat="inconnu")

        etat = self._lire(achat_id)
        anomalies += self._rapprocher(o, etat, stop_id)
        ecarts = self._ecarts_fiche(o, etat)
        cr = CompteRendu(True, anomalies=anomalies)
        if etat.quantite_executee > 0 and etat.prix_moyen is not None:
            p = self.journal.acheter(Achat(
                quand=maintenant, trade_id=o.trade_id, quantite=etat.quantite_executee,
                prix_execution_eur=etat.prix_moyen, stop_eur=o.prix_stop,
                raison=f"ordre {'simulé' if simulation else 'RÉEL'} en mode {self.mode.value}",
                fiche_id=o.fiche_id if o.fiche_id in {f.id for f in self.journal.fiches} else None))
            cr.position_id = p.id
            cr.etat = f"exécuté {etat.quantite_executee} × {etat.prix_moyen} € (lu chez le courtier)"
        elif etat.statut in ("PreSubmitted", "Submitted", "PendingSubmit"):
            cr.etat = "en attente d'exécution chez le courtier (rien noté au journal tant que rien n'est exécuté)"
        else:
            cr.etat = etat.statut
        self.registre.noter(maintenant, o, etat.statut, anomalies, ecarts, simulation, etat.prix_moyen,
                            etat.quantite_executee)
        if anomalies:
            self.arreter("réponse inattendue du courtier : " + anomalies[0])
        return cr

    def _lire(self, ordre_id: str) -> EtatOrdre:
        etat = self.courtier.etat(ordre_id)
        for _ in range(ESSAIS_LECTURE):
            if etat.statut != "PendingSubmit":
                break
            self.attente(1.0)
            etat = self.courtier.etat(ordre_id)
        return etat

    def _rapprocher(self, o: OrdrePropose, etat: EtatOrdre, stop_id) -> list[str]:
        a = []
        if etat.statut not in STATUTS_CONNUS:
            a.append(f"Statut inattendu « {etat.statut} » renvoyé par le courtier.")
            return a
        if etat.statut in ("Cancelled", "ApiCancelled", "Inactive"):
            a.append(f"Ordre rejeté ou annulé par le courtier (statut {etat.statut}).")
        if etat.quantite_executee > o.quantite:
            a.append(f"Quantité exécutée {etat.quantite_executee} > quantité demandée {o.quantite}.")
        if etat.prix_moyen is not None and etat.prix_moyen > o.prix_limite:
            a.append(f"Prix d'exécution {etat.prix_moyen} € au-dessus du prix limite {o.prix_limite} €.")
        if etat.quantite_executee > 0:
            if stop_id is None:
                a.append("Stop absent chez le courtier alors que l'achat est exécuté.")
            else:
                s = self.courtier.etat(stop_id)
                if s.statut not in ("Submitted", "PreSubmitted"):
                    a.append(f"Stop non actif chez le courtier (statut {s.statut}).")
                elif 0 < etat.quantite_executee < o.quantite and etat.statut not in ("Submitted", "PreSubmitted"):
                    # exécution partielle terminée : le stop ne doit pas vendre plus que ce qui est détenu
                    self.courtier.modifier_quantite(stop_id, etat.quantite_executee)
        return a

    @staticmethod
    def _ecarts_fiche(o: OrdrePropose, etat: EtatOrdre) -> list[str]:
        """Comparaison avec ce que tu aurais fait à la main en suivant la fiche."""
        e = []
        if etat.quantite_executee and etat.quantite_executee != o.quantite:
            e.append(f"exécuté {etat.quantite_executee} au lieu de {o.quantite}")
        if etat.prix_moyen is not None and etat.prix_moyen != o.prix_limite:
            e.append(f"prix {etat.prix_moyen} € pour une limite à {o.prix_limite} €"
                     f" ({(etat.prix_moyen - o.prix_limite) * etat.quantite_executee:+} € au total)")
        return e
