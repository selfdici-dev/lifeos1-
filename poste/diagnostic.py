"""Diagnostic des clés gratuites : python -m poste.diagnostic

Fait un seul appel par fournisseur et dit ce qui marche vraiment. N'affiche jamais une clé.
Alpha Vantage : l'appel compte dans les 25 requêtes du jour (puis il est mis en cache 24 h).
"""
from poste.donnees.fabrique import charger_env, creer_marche
from poste.donnees.marche import Marche
from poste.donnees.modeles import badge


def _ligne(nom, fournisseur, resultat, maintenant, extra=""):
    if not fournisseur.cle_presente:
        return f"✗ {nom} : clé absente : source désactivée"
    if resultat is None:
        return f"✗ {nom} : échec ({fournisseur.dernier_statut or 'aucune donnée'}){extra}"
    detail = badge(nom, resultat, maintenant) if hasattr(resultat, "valeur") else resultat
    return f"✓ {nom} : OK · {detail}{extra}"


def diagnostiquer(m: Marche) -> list[str]:
    t = m.horloge()
    lignes = [
        _ligne("Finnhub", m.finnhub, m.finnhub.cotation("NVDA"), t),
        _ligne("Twelve Data", m.twelvedata, m.twelvedata.cotation("EUR/USD"), t),
        _ligne("FRED", m.fred, m.fred.taux_10a(), t),
    ]
    evts = m.alphavantage.resultats("NVDA")
    restant = m.alphavantage.limiteur.restant_aujourdhui()
    lignes.append(_ligne("Alpha Vantage", m.alphavantage,
                         None if evts is None else f"{len(evts) // 2} date(s) de résultats NVDA trouvée(s)", t,
                         f" · requêtes restantes aujourd'hui : {restant}"))
    yf = m.yfinance.cotation("BTC-USD")
    if m.yfinance.yf is None:
        lignes.append("✗ yfinance : bibliothèque non installée")
    else:
        lignes.append(_ligne("yfinance", m.yfinance, yf, t))
    lignes.append("Les prix sont indicatifs : le prix d'exécution se lit dans Trade Republic.")
    return lignes


def main() -> None:
    charger_env()
    for ligne in diagnostiquer(creer_marche()):
        print(ligne)


if __name__ == "__main__":
    main()
