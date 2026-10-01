"""Assistant interactif.

  python -m poste                 fiche d'ordre, prix saisis à la main
  python -m poste auto            fiche avec données en direct (diagnostic : python -m poste.diagnostic)
  python -m poste niveau 2        change le niveau d'agressivité
  python -m poste expo            exposition par thème
  python -m poste journal achat   note un achat exécuté
  python -m poste journal stop    note un déplacement de stop
  python -m poste journal vente   note une vente
  python -m poste journal         liste les positions
  python -m poste risque          tableau de risque
  python -m poste bilan           bilan de la semaine
  python -m poste rappels         envoie les rappels ntfy (laisser tourner)
"""
import os
import sys
import time as _time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from poste.bilan import bilan_hebdo
from poste.donnees.fabrique import charger_env, creer_marche
from poste.donnees.modeles import FIN_ANSI, ROUGE_ANSI, badge
from poste.exposition import Position as PositionExpo, calculer_exposition, charger_positions
from poste.fiche import RAPPEL, Saisie, Verdict, build_order_sheet
from poste.journal import Achat, FicheJournal, Journal, Vente
from poste.plan import charger_plan
from poste.rappels import envoyer_ntfy, prochains_rappels
from poste.reglages import Reglages, charger_reglages, enregistrer_reglages
from poste.regles import FUSEAU, charger_calendrier, evenements_bloquants
from poste.risque import tableau_risque

RACINE = Path(__file__).resolve().parent.parent
CHEMIN_POSITIONS = RACINE / "positions.json"
CHEMIN_CALENDRIER = RACINE / "calendrier.json"


def _maintenant() -> datetime:
    return datetime.now(FUSEAU)


def _nombre(question: str, optionnel: bool = False) -> Decimal | None:
    while True:
        rep = input(f"{question} : ").strip().replace(",", ".").replace(" ", "")
        if not rep and optionnel:
            return None
        try:
            return Decimal(rep)
        except InvalidOperation:
            print("  -> tape un nombre, par exemple 163,70")


def _entier(question: str) -> int:
    while True:
        try:
            return int(input(f"{question} : ").strip())
        except ValueError:
            print("  -> tape un nombre entier")


def _oui_non(question: str) -> bool:
    while True:
        rep = input(f"{question} (o/n) : ").strip().lower()
        if rep in ("o", "oui"):
            return True
        if rep in ("n", "non"):
            return False


def _journal(plan) -> Journal:
    return Journal(frais_par_ordre=plan.frais_par_ordre_eur)


def _positions(plan, journal: Journal) -> list[PositionExpo]:
    """Positions ouvertes du journal ; à défaut, positions.json saisi à la main."""
    if journal.positions:
        themes = {t.id: t.theme for t in plan.trades}
        return [PositionExpo(instrument=p.achat.trade_id, theme=themes[p.achat.trade_id],
                             valeur_eur=p.quantite_restante * p.achat.prix_execution_eur)
                for p in journal.ouvertes() if p.achat.trade_id in themes]
    return charger_positions(CHEMIN_POSITIONS)


def _entete(plan, niveau, journal):
    n = plan.niveau(niveau)
    print(RAPPEL)
    print(f"Niveau {niveau} ({n.nom}). Pour changer : python -m poste niveau 1, 2 ou 3")
    print(f"Perte cumulée (journal) : {journal.perte_cumulee()} € / seuil {n.seuil_arret_perte_cumulee_eur} €")
    print(calculer_exposition(_positions(plan, journal), plan.capital_eur).texte())


def _choisir_trade(plan):
    print("\nTrades du plan :")
    for i, t in enumerate(plan.trades, 1):
        print(f"  {i}. {t.id} : {t.nom}")
    while True:
        try:
            return plan.trades[int(input("Numéro du trade : ")) - 1]
        except (ValueError, IndexError):
            pass


def _evenement_24h() -> bool:
    calendrier = charger_calendrier(CHEMIN_CALENDRIER)
    if calendrier is None:
        return _oui_non("Annonce à impact fort dans les 24 h (Fed, inflation US, emploi US, résultats) ?")
    bloquants = evenements_bloquants(_maintenant(), calendrier)
    for e in bloquants:
        print(f"  Événement d'impact fort : {e.nom} le {e.debut.astimezone(FUSEAU):%d/%m à %H:%M} (Paris)")
    if not bloquants:
        print("  Aucun événement d'impact fort dans les 24 h selon calendrier.json.")
        # le calendrier peut être incomplet : on te demande quand même
        return _oui_non("Tu connais une autre annonce à impact fort dans les 24 h ?")
    return True


def _emettre(journal: Journal, trade_id: str, saisie: Saisie, niveau: int, plan, **kw) -> None:
    try:
        fiche = build_order_sheet(trade_id, saisie, niveau, plan=plan, positions=_positions(plan, journal), **kw)
    except (ValidationError, ValueError) as e:
        print(f"\nSaisie refusée, aucune fiche émise : {e}")
        return
    trace = journal.noter_fiche(FicheJournal(
        quand=_maintenant(), trade_id=trade_id, verdict=fiche.verdict.value,
        prix_limite_eur=fiche.prix_limite_eur if fiche.verdict is Verdict.FEU_VERT else None,
        prix_stop_eur=fiche.prix_stop_eur if fiche.verdict is Verdict.FEU_VERT else None,
        quantite=fiche.quantite if fiche.verdict is Verdict.FEU_VERT else None))
    print()
    print(fiche.texte())
    if fiche.verdict is Verdict.FEU_VERT:
        print(f"\nFiche {trace.id}. Après l'achat : python -m poste journal achat (cite la fiche {trace.id}).")


def cmd_niveau(arg: str) -> None:
    plan = charger_plan()
    try:
        r = charger_reglages().model_copy(update={"niveau": Reglages(niveau=int(arg)).niveau})
    except (ValueError, ValidationError):
        print("Niveau invalide : 1, 2 ou 3.")
        return
    enregistrer_reglages(r)
    n = plan.niveau(r.niveau)
    print(f"Niveau {r.niveau} ({n.nom}) : perte max {n.risque_max_par_trade_eur} € par trade,"
          f" montant max {n.montant_max_par_trade_eur} €, arrêt des achats à {n.seuil_arret_perte_cumulee_eur} €"
          " de perte cumulée.")


def cmd_expo() -> None:
    plan = charger_plan()
    print(calculer_exposition(_positions(plan, _journal(plan)), plan.capital_eur).texte())


def cmd_fiche() -> None:
    plan = charger_plan()
    niveau = charger_reglages().niveau
    journal = _journal(plan)
    _entete(plan, niveau, journal)
    trade = _choisir_trade(plan)

    print(f"\nRéférence : {trade.ref_libelle}")
    valeurs = dict(
        prix_vendeur_eur=_nombre("Prix VENDEUR affiché dans Trade Republic (en €)"),
        cours_ref=_nombre("Cours actuel sur TradingView"),
        mm50_ref=_nombre("Moyenne mobile 50 jours sur TradingView"),
        eurusd=_nombre("EUR/USD (1 € = x $), vide si inutile", optionnel=trade.devise_ref != "USD"),
        taux_us10a_pct=_nombre("Taux US 10 ans en % (TradingView : US10Y)"),
        sp500_variation_seance_pct=_nombre("Variation du S&P 500 sur la séance en % (ex. -0,8)"),
        evenement_majeur_24h=_evenement_24h(),
        perte_cumulee_eur=journal.perte_cumulee(),
    )
    if trade.type == "turbo_long":
        valeurs["barriere_ref"] = _nombre("Barrière (knock-out) du turbo, en points")
    try:
        saisie = Saisie(**valeurs)
    except ValidationError as e:
        print(f"\nSaisie refusée, aucune fiche émise : {e}")
        return
    _emettre(journal, trade.id, saisie, niveau, plan)


def cmd_auto() -> None:
    charger_env()
    plan = charger_plan()
    niveau = charger_reglages().niveau
    journal = _journal(plan)
    _entete(plan, niveau, journal)
    trade = _choisir_trade(plan)

    marche = creer_marche()
    releve = marche.releve(trade)
    maintenant = marche.horloge()
    print("\nDonnées (indicatives : le prix d'exécution se lit dans Trade Republic) :")
    for nom, d in releve.donnees.items():
        print("  " + badge(nom, d, maintenant))
    perimees = releve.perimees(maintenant)
    if perimees:
        print(f"\n{ROUGE_ANSI}PÉRIMÉ{FIN_ANSI} : {', '.join(perimees)}. Aucune fiche d'ordre générée.")
        print("Hors séance US, c'est normal. Sinon : python -m poste.diagnostic")
        return

    # Événements : calendrier saisi à la main + dates de résultats (Alpha Vantage).
    calendrier = charger_calendrier(CHEMIN_CALENDRIER)
    connus = (calendrier or []) + (releve.evenements or [])
    bloquants = evenements_bloquants(maintenant, connus)
    for e in bloquants:
        print(f"  Événement d'impact fort : {e.nom} le {e.debut.astimezone(FUSEAU):%d/%m à %H:%M} (Paris)")
    if bloquants:
        evenement = True
    else:
        if calendrier is None or releve.evenements is None:
            print("  Calendrier incomplet (calendrier.json absent ou Alpha Vantage indisponible).")
        evenement = _oui_non("Annonce à impact fort dans les 24 h que l'appli ne connaît pas"
                             " (Fed, inflation US, emploi US) ?")

    d = releve.donnees
    valeurs = dict(
        prix_vendeur_eur=_nombre("Prix VENDEUR affiché dans Trade Republic (en €)"),
        cours_ref=d["cours"].valeur,
        mm50_ref=d["mm50"].valeur,
        eurusd=d["eurusd"].valeur if "eurusd" in d else None,
        taux_us10a_pct=d["taux_us10a"].valeur,
        sp500_variation_seance_pct=d["sp500_variation"].valeur,
        evenement_majeur_24h=evenement,
        perte_cumulee_eur=journal.perte_cumulee(),
    )
    if trade.type == "turbo_long":
        valeurs["barriere_ref"] = _nombre("Barrière (knock-out) du turbo, en points")
    try:
        saisie = Saisie(**valeurs)
    except ValidationError as e:
        print(f"\nSaisie refusée, aucune fiche émise : {e}")
        return
    # les données sont relues juste avant l'émission : périmées entre-temps -> pas de fiche
    _emettre(journal, trade.id, saisie, niveau, plan, perimees=releve.perimees(marche.horloge()))


def cmd_journal(argv: list[str]) -> None:
    plan = charger_plan()
    journal = _journal(plan)
    action = argv[0] if argv else "liste"
    try:
        if action == "achat":
            trade = _choisir_trade(plan)
            fiche_id = input("Numéro de la fiche suivie (ex. F3), vide si aucune : ").strip().upper() or None
            p = journal.acheter(Achat(
                quand=_maintenant(), trade_id=trade.id,
                quantite=_entier("Quantité achetée"),
                prix_execution_eur=_nombre("Prix d'exécution réel (lu dans Trade Republic, en €)"),
                stop_eur=_nombre("Prix du stop posé chez le courtier (en €)"),
                objectif_eur=_nombre("Premier objectif (en €), vide si aucun", optionnel=True),
                raison=input("Raison du trade, en une phrase : ").strip(),
                fiche_id=fiche_id))
            print(f"Position {p.id} notée.")
        elif action == "stop":
            pid = input("Position (ex. A1) : ").strip().upper()
            p = journal.deplacer_stop(pid, _maintenant(), _nombre("Nouveau prix du stop (en €)"))
            if p.stop_descendu:
                print("ATTENTION : tu as descendu ton stop. Ce sera compté comme une erreur dans le bilan.")
            print(f"Stop de {p.id} : {p.stop_courant} €.")
        elif action == "vente":
            pid = input("Position (ex. A1) : ").strip().upper()
            p = journal.vendre(pid, Vente(quand=_maintenant(), quantite=_entier("Quantité vendue"),
                                          prix_eur=_nombre("Prix d'exécution réel (en €)"),
                                          raison=input("Raison (stop, objectif, autre) : ").strip()))
            print(f"{p.id} : reste {p.quantite_restante} titre(s)."
                  + (f" Résultat : {p.resultat_eur} € frais compris." if p.fermee else ""))
        else:
            for p in journal.positions:
                etat = f"fermée, résultat {p.resultat_eur} €" if p.fermee else \
                    f"ouverte, {p.quantite_restante} titre(s), stop {p.stop_courant} €"
                print(f"{p.id} {p.achat.quand:%d/%m %H:%M} {p.achat.trade_id} ×{p.achat.quantite}"
                      f" à {p.achat.prix_execution_eur} € : {etat}")
            if not journal.positions:
                print("Journal vide.")
    except (ValidationError, ValueError, KeyError) as e:
        print(f"Refusé : {e}")


def cmd_risque() -> None:
    plan = charger_plan()
    print(tableau_risque(_journal(plan), plan, charger_reglages().niveau).texte())


def cmd_bilan() -> None:
    plan = charger_plan()
    print(bilan_hebdo(_journal(plan), plan, _maintenant()).texte())


def cmd_rappels() -> None:
    charger_env()
    sujet = os.environ.get("NTFY_TOPIC")
    if not sujet:
        print("NTFY_TOPIC absent de .env : rappels désactivés.")
        return
    rappels = charger_reglages().rappels
    print("Rappels actifs (Ctrl+C pour arrêter). Prochains :")
    for quand, r in prochains_rappels(_maintenant(), rappels):
        print(f"  {quand:%a %d/%m %H:%M} : {r.message}")
    while True:
        quand, r = prochains_rappels(_maintenant(), rappels, nombre=1)[0]
        while (reste := (quand - _maintenant()).total_seconds()) > 0:
            _time.sleep(min(reste, 60))
        message = r.message
        if "bilan" in message.lower():
            plan = charger_plan()
            message = bilan_hebdo(_journal(plan), plan, _maintenant()).texte()
        print(f"{_maintenant():%d/%m %H:%M} envoi : {'OK' if envoyer_ntfy(sujet, message) else 'échec'}")


def main(argv: list[str]) -> None:
    commandes = {"auto": cmd_auto, "expo": cmd_expo, "risque": cmd_risque, "bilan": cmd_bilan,
                 "rappels": cmd_rappels}
    if argv[:1] == ["niveau"] and len(argv) == 2:
        cmd_niveau(argv[1])
    elif argv[:1] == ["journal"]:
        cmd_journal(argv[1:])
    elif len(argv) == 1 and argv[0] in commandes:
        commandes[argv[0]]()
    elif not argv:
        cmd_fiche()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
