"""Assistant interactif.

  python -m poste                 MENU SIMPLE (recommandé ; sous Windows : double-clic sur LANCER.bat)
  python -m poste fiche           fiche d'ordre, prix saisis à la main
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
  python -m poste execution       état de l'exécution automatisée (mode, arrêt, simulation)
  python -m poste execution mode MANUEL|CONFIRMATION|AUTO
  python -m poste arret           INTERRUPTEUR D'ARRÊT : coupe tout envoi, annule les achats en attente
  python -m poste reprise         lève l'arrêt (à la main seulement)
"""
import os
import sys
import time as _time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from poste.bilan import bilan_hebdo, ecarts_avec_fiche
from poste.donnees.fabrique import charger_env, creer_marche
from poste.console import couleur, preparer_console
from poste.donnees.modeles import FIN_ANSI, ROUGE_ANSI, badge
from poste.exposition import Position as PositionExpo, calculer_exposition, charger_positions
from poste.fiche import RAPPEL, Saisie, Verdict, build_order_sheet
from poste.journal import Achat, FicheJournal, Journal, Vente
from poste.plan import charger_plan
from poste.rappels import envoyer_ntfy, prochains_rappels
from poste.reglages import Reglages, charger_reglages, enregistrer_reglages
from poste.regles import FUSEAU, charger_calendrier, evenements_bloquants
from poste.risque import tableau_risque
from poste.execution.arret import Interrupteur
from poste.execution.executeur import Executeur
from poste.execution.limites import LISTE_BLANCHE
from poste.execution.modeles import Mode, OrdrePropose
from poste.execution.simulation import PHRASE_AUTORISATION, RegistreSimulation, porte_ordres_reels

RACINE = Path(__file__).resolve().parent.parent
CHEMIN_POSITIONS = RACINE / "positions.json"
CHEMIN_CALENDRIER = RACINE / "calendrier.json"
CHEMIN_ARRET = RACINE / ".cache" / "ARRET"
CHEMIN_SIMULATION = RACINE / ".cache" / "simulation.json"
CHEMIN_AUTORISATION = RACINE / "AUTORISATION_ORDRES_REELS.txt"


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
    print(f"Baisse depuis ton point haut (journal) : {journal.perte_cumulee()} €"
          f" / seuil d'arrêt {n.seuil_arret_perte_cumulee_eur} €")
    print(calculer_exposition(_positions(plan, journal), plan.capital_eur).texte())


def _question_prix() -> str:
    if charger_reglages().mode_execution is Mode.MANUEL:
        return "Prix VENDEUR affiché dans Trade Republic (en €)"
    return "Prix VENDEUR affiché chez le courtier qui exécutera l'ordre (TWS / IBKR, en €)"


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
        fiche = build_order_sheet(trade_id, saisie, niveau, plan=plan, positions=_positions(plan, journal),
                                  resultat_realise_eur=journal.resultat_realise(), **kw)
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
    if fiche.verdict is not Verdict.FEU_VERT:
        return
    mode = charger_reglages().mode_execution
    if mode is Mode.MANUEL or trade_id not in LISTE_BLANCHE:
        print(f"\nFiche {trace.id}. Après l'achat : python -m poste journal achat (cite la fiche {trace.id}).")
        return
    trade = plan.trade(trade_id)
    ordre = OrdrePropose(trade_id=trade_id, isin=trade.isin, quantite=fiche.quantite,
                         prix_limite=fiche.prix_limite_eur, prix_stop=fiche.prix_stop_eur, devise="EUR",
                         fiche_id=trace.id, verdict=fiche.verdict.value, perimees=tuple(kw.get("perimees") or ()))
    print(f"\nMode {mode.value} : préparation de l'ordre chez le courtier.")
    print(_executeur(plan, niveau, journal, mode).envoyer(ordre).texte())


def _confirmer(o: OrdrePropose) -> bool:
    print(f"\nORDRE À ENVOYER : ACHAT {o.quantite} × {o.trade_id} à cours limité {o.prix_limite} €,"
          f" stop de vente lié à {o.prix_stop} € (reste chez le courtier). Montant max {o.montant} €.")
    return input("Tape OUI (en majuscules) pour envoyer cet ordre, autre chose pour annuler : ").strip() == "OUI"


def _executeur(plan, niveau, journal, mode) -> Executeur:
    from poste.execution.ibkr import CourtierIBKR
    charger_env()
    courtier = CourtierIBKR(port=int(os.environ.get("IBKR_PORT", "7497")))
    return Executeur(courtier=courtier, journal=journal, plan=plan, niveau=niveau, mode=mode,
                     registre=RegistreSimulation(CHEMIN_SIMULATION), interrupteur=Interrupteur(CHEMIN_ARRET),
                     horloge=_maintenant, confirmer=_confirmer, chemin_autorisation=CHEMIN_AUTORISATION,
                     attente=_time.sleep)


def cmd_execution(argv: list[str]) -> None:
    reglages = charger_reglages()
    if argv[:1] == ["mode"] and len(argv) == 2:
        try:
            mode = Mode(argv[1].upper())
        except ValueError:
            print("Modes : MANUEL, CONFIRMATION, AUTO.")
            return
        if mode is Mode.AUTO and input("Mode AUTO : l'app enverra seule les ordres FEU VERT, dans les limites"
                                       " codées en dur. Tape AUTO pour confirmer : ").strip() != "AUTO":
            print("Inchangé.")
            return
        enregistrer_reglages(reglages.model_copy(update={"mode_execution": mode}))
        print(f"Mode d'exécution : {mode.value}.")
        return
    arret = Interrupteur(CHEMIN_ARRET)
    registre = RegistreSimulation(CHEMIN_SIMULATION)
    ok, manque = porte_ordres_reels(registre, _maintenant(), CHEMIN_AUTORISATION)
    print(f"Mode : {reglages.mode_execution.value}")
    print(f"Arrêt : {'ACTIF : ' + arret.raison if arret.actif else 'non'}")
    print(f"Ordres enregistrés : {len(registre.entrees)} (anomalies : {len(registre.anomalies())})")
    print("Ordres réels : " + ("autorisés" if ok else "INTERDITS"))
    for m in manque:
        print(f"  - {m}")


def cmd_arret() -> None:
    plan = charger_plan()
    try:
        ex = _executeur(plan, charger_reglages().niveau, _journal(plan), Mode.MANUEL)
        annules = ex.arreter("bouton d'arrêt")
    except Exception:  # noqa: BLE001 - le blocage local passe avant tout
        Interrupteur(CHEMIN_ARRET).declencher("bouton d'arrêt", _maintenant())
        annules = None
    if annules is None:
        print("ARRÊT ACTIF : plus aucun envoi. MAIS le courtier n'a pas pu être joint : annule toi-même les"
              " achats en attente dans TWS ou l'appli IBKR (garde les stops).")
    else:
        print(f"ARRÊT ACTIF. Achats en attente annulés : {len(annules)}. Les stops de protection restent en place.")


def cmd_reprise() -> None:
    arret = Interrupteur(CHEMIN_ARRET)
    if not arret.actif:
        print("Aucun arrêt actif.")
        return
    print(f"Arrêt actif :\n{arret.raison}")
    if input("Tu as compris la cause et vérifié tes ordres chez le courtier ? Tape REPRISE : ").strip() == "REPRISE":
        arret.lever()
        print("Arrêt levé.")
    else:
        print("Arrêt maintenu.")


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
        prix_vendeur_eur=_nombre(_question_prix()),
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
        print(couleur(f"\n{ROUGE_ANSI}PÉRIMÉ{FIN_ANSI} : {', '.join(perimees)}. Aucune fiche d'ordre générée."))
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
        prix_vendeur_eur=_nombre(_question_prix()),
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
            if fiche_id:
                fiche = next(f for f in journal.fiches if f.id == fiche_id)
                if fiche.verdict != "FEU VERT":
                    print(f"ATTENTION : la fiche {fiche_id} disait {fiche.verdict}, pas FEU VERT.")
                for ecart in ecarts_avec_fiche(p.achat, fiche):
                    print(f"ATTENTION : {ecart}. Ce sera compté dans le bilan.")
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
        print(f"  {quand:%a %d/%m %H:%M} : {r.texte(quand.date())}")
    while True:
        quand, r = prochains_rappels(_maintenant(), rappels, nombre=1)[0]
        while (reste := (quand - _maintenant()).total_seconds()) > 0:
            _time.sleep(min(reste, 60))
        message = r.texte(quand.date())
        if "bilan" in message.lower():
            plan = charger_plan()
            message = bilan_hebdo(_journal(plan), plan, _maintenant()).texte()
        print(f"{_maintenant():%d/%m %H:%M} envoi : {'OK' if envoyer_ntfy(sujet, message) else 'échec'}")


def main(argv: list[str]) -> None:
    preparer_console()
    commandes = {"auto": cmd_auto, "expo": cmd_expo, "risque": cmd_risque, "bilan": cmd_bilan,
                 "rappels": cmd_rappels, "fiche": cmd_fiche}
    if argv[:1] == ["execution"]:
        cmd_execution(argv[1:])
    elif argv[:1] == ["arret"]:
        cmd_arret()
    elif argv[:1] == ["reprise"]:
        cmd_reprise()
    elif argv[:1] == ["niveau"] and len(argv) == 2:
        cmd_niveau(argv[1])
    elif argv[:1] == ["journal"]:
        cmd_journal(argv[1:])
    elif len(argv) == 1 and argv[0] in commandes:
        commandes[argv[0]]()
    elif not argv:
        from poste.menu import menu
        menu()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
