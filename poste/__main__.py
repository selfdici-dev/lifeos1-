"""Assistant interactif : python -m poste"""
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from poste.fiche import RAPPEL, Saisie, build_order_sheet
from poste.plan import charger_plan


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


def main() -> None:
    plan = charger_plan()
    print(RAPPEL)
    print("Trades du plan :")
    for i, t in enumerate(plan.trades, 1):
        print(f"  {i}. {t.id} : {t.nom}")
    while True:
        try:
            trade = plan.trades[int(input("Numéro du trade : ")) - 1]
            break
        except (ValueError, IndexError):
            pass
    niveau = input("Niveau d'agressivité (1, 2 ou 3) [1] : ").strip() or "1"
    plan.niveau(niveau)

    print(f"\nRéférence : {trade.ref_libelle}")
    valeurs = dict(
        prix_vendeur_eur=_nombre("Prix VENDEUR affiché dans Trade Republic (en €)"),
        cours_ref=_nombre("Cours actuel sur TradingView"),
        mm50_ref=_nombre("Moyenne mobile 50 jours sur TradingView"),
        eurusd=_nombre("EUR/USD (1 € = x $), vide si inutile", optionnel=trade.devise_ref != "USD"),
        taux_us10a_pct=_nombre("Taux US 10 ans en % (TradingView : US10Y)"),
        sp500_variation_seance_pct=_nombre("Variation du S&P 500 sur la séance en % (ex. -0,8)"),
        evenement_majeur_24h=_oui_non("Annonce à impact fort dans les 24 h (Fed, inflation US, résultats) ?"),
        perte_cumulee_eur=_nombre("Perte cumulée depuis le début, en € (0 si aucune)"),
    )
    if trade.type == "turbo_long":
        valeurs["barriere_ref"] = _nombre("Barrière (knock-out) du turbo, en points")
    try:
        fiche = build_order_sheet(trade.id, Saisie(**valeurs), int(niveau), plan=plan)
    except (ValidationError, ValueError) as e:
        print(f"\nSaisie refusée, aucune fiche émise : {e}")
        return
    print()
    print(fiche.texte())


if __name__ == "__main__":
    main()
