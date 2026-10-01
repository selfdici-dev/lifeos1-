"""Assemble les fournisseurs avec leurs caches et le compteur persistant."""
import os
from pathlib import Path
from typing import Mapping, Optional

from poste.donnees.cache import Cache
from poste.donnees.fournisseurs import AlphaVantage, Finnhub, Fred, Transport, TwelveData, YFinance
from poste.donnees.limiteur import CompteurPersistant, Horloge, maintenant_paris
from poste.donnees.marche import Marche

RACINE = Path(__file__).resolve().parent.parent.parent
DOSSIER_CACHE = RACINE / ".cache"


def charger_env() -> None:
    """Charge .env dans les variables d'environnement du programme. Rien n'est affiché ni journalisé."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(RACINE / ".env", override=False)


def creer_marche(env: Optional[Mapping[str, str]] = None, transport: Optional[Transport] = None,
                 horloge: Horloge = maintenant_paris, dossier_cache: Path = DOSSIER_CACHE,
                 yfinance_module="auto") -> Marche:
    env = os.environ if env is None else env
    compteur = CompteurPersistant(Path(dossier_cache) / "compteurs.json")
    commun = dict(transport=transport, horloge=horloge, env=env)
    return Marche(
        finnhub=Finnhub(**commun),
        twelvedata=TwelveData(**commun),
        fred=Fred(**commun),
        # cache disque : les 25 requêtes par jour sont précieuses
        alphavantage=AlphaVantage(**commun, compteur=compteur,
                                  cache=Cache(horloge, Path(dossier_cache) / "alphavantage.json")),
        yfinance=YFinance(horloge=horloge, module=yfinance_module),
        horloge=horloge,
    )
