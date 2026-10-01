"""Assistant interactif.

  python -m poste             fiche d'ordre (niveau lu dans reglages.json)
  python -m poste niveau 2    change le niveau d'agressivité
  python -m poste expo        affiche l'exposition par thème
  python -m poste auto        fiche avec données en direct (diagnostic : python -m poste.diagnostic)
"""
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from poste.donnees.fabrique import charger_env, creer_marche
from poste.donnees.modeles import ROUGE_ANSI, FIN_ANSI, badge
from poste.exposition import calculer_exposition, charger_positions
from poste.fiche import RAPPEL, Saisie, build_order_sheet
from poste.plan import charger_plan
from poste.reglages import Reglages, charger_reglages, enregistrer_reglages
from poste.regles import FUSEAU, charger_calendrier, evenements_bloquants

RACINE = Path(__file__).resolve().parent.parent
CHEMIN_POSITIONS = RACINE / "positions.json"
CHEMIN_CALENDRIER = RACINE / "calendrier.json"


def _nombre(question: str, optionnel: bool = False) -> Decimal | None:
    while True:
        rep = input(f"{question} : ").strip().replace(",", ".").replace(" ", "")
        if not rep and optionnel:
            return None
        try:
            return Decimal(rep)
        except InvalidOperation:
            print("  -> tape un nombre, par exemple 163,70")


def _oui_non(question: str) -> bool:
    while True:
        rep = input(f"{question} (o/n) : ").strip().lower()
        if rep in ("o", "oui"):
            return True
        if rep in ("n", "non"):
            return False


def _evenement_24h() -> bool:
    calendrier = charger_calendrier(CHEMIN_CALENDRIER)
    if calendrier is None:
        return _oui_non("Annonce à impact fort dans les 24 h (Fed, inflation US, emploi US, résultats) ?")
    bloquants = evenements_bloquants(datetime.now(FUSEAU), calendrier)
    for e in bloquants:
        print(f"  Événement d'impact fort : {e.nom} le {e.debut.astimezone(FUSEAU):%d/%m à %H:%M} (Paris)")
    if not bloquants:
        print("  Aucun événement d'impact fort dans les 24 h selon calendrier.json.")
        # le calendrier peut être incomplet : on te demande quand même
        return _oui_non("Tu connais une autre annonce à impact fort dans les 24 h ?")
    return True


def cmd_niveau(arg: str) -> None:
    plan = charger_plan()
    try:
        r = Reglages(niveau=int(arg))
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
    print(calculer_exposition(charger_positions(CHEMIN_POSITIONS), plan.capital_eur).texte())


def cmd_fiche() -> None:
    plan = charger_plan()
    niveau = charger_reglages().niveau
    positions = charger_positions(CHEMIN_POSITIONS)
    n = plan.niveau(niveau)
    print(RAPPEL)
    print(f"Niveau {niveau} ({n.nom}). Pour changer : python -m poste niveau 1, 2 ou 3")
    print(calculer_exposition(positions, plan.capital_eur).texte())
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
        perte_cumulee_eur=_nombre("Perte cumulée depuis le début, en € (0 si aucune)"),
    )
    if trade.type == "turbo_long":
        valeurs["barriere_ref"] = _nombre("Barrière (knock-out) du turbo, en points")
    try:
        fiche = build_order_sheet(trade.id, Saisie(**valeurs), niveau, plan=plan, positions=positions)
    except (ValidationError, ValueError) as e:
        print(f"\nSaisie refusée, aucune fiche émise : {e}")
        return
    print()
    print(fiche.texte())


def _choisir_trade(plan):
    print("\nTrades du plan :")
    for i, t in enumerate(plan.trades, 1):
        print(f"  {i}. {t.id} : {t.nom}")
    while True:
        try:
            return plan.trades[int(input("Numéro du trade : ")) - 1]
        except (ValueError, IndexError):
            pass


def cmd_auto() -> None:
    charger_env()
    plan = charger_plan()
    niveau = charger_reglages().niveau
    positions = charger_positions(CHEMIN_POSITIONS)
    print(RAPPEL)
    print(f"Niveau {niveau}.")
    print(calculer_exposition(positions, plan.capital_eur).texte())
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
        perte_cumulee_eur=_nombre("Perte cumulée depuis le début, en € (0 si aucune)"),
    )
    if trade.type == "turbo_long":
        valeurs["barriere_ref"] = _nombre("Barrière (knock-out) du turbo, en points")
    try:
        fiche = build_order_sheet(trade.id, Saisie(**valeurs), niveau, plan=plan, positions=positions,
                                  perimees=releve.perimees(marche.horloge()))
    except (ValidationError, ValueError) as e:
        print(f"\nSaisie refusée, aucune fiche émise : {e}")
        return
    print()
    print(fiche.texte())


def main(argv: list[str]) -> None:
    if argv[:1] == ["niveau"] and len(argv) == 2:
        cmd_niveau(argv[1])
    elif argv[:1] == ["auto"]:
        cmd_auto()
    elif argv[:1] == ["expo"]:
        cmd_expo()
    elif not argv:
        cmd_fiche()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
