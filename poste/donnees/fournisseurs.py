"""Fournisseurs de données. Clé absente = source désactivée.

Sécurité : les clés ne sont jamais journalisées. Les messages de log ne contiennent que le nom
du fournisseur, le code HTTP et le type d'exception, jamais l'URL, les paramètres, le corps de
la réponse ni le texte d'une exception (qui peut contenir l'URL avec la clé).
"""
import csv
import io
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, Optional
from zoneinfo import ZoneInfo

from poste.donnees.cache import Cache
from poste.donnees.limiteur import CompteurPersistant, Disjoncteur, Horloge, Limiteur, maintenant_paris
from poste.donnees.modeles import Donnee, Historique, Nature
from poste.regles import Evenement

log = logging.getLogger("poste.donnees")
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Reponse:
    statut: int
    texte: str


Transport = Callable[..., Reponse]  # (url, params, headers=None) -> Reponse


def transport_requests(url: str, params: dict, headers: Optional[dict] = None) -> Reponse:
    import requests
    r = requests.get(url, params=params, headers=headers, timeout=10)
    return Reponse(r.status_code, r.text)


# Deuxième barrière : si quelqu'un active les logs détaillés (DEBUG), urllib3 écrit l'URL complète.
# FRED et Alpha Vantage n'acceptent la clé que dans l'URL : on la masque dans tout message de log.
_MOTIF_CLE = re.compile(r"((?:api_?key|token)=)[^&\s\"']+", re.IGNORECASE)


class _MasqueCles(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        masque = _MOTIF_CLE.sub(r"\1***", message)
        if masque != message:
            record.msg, record.args = masque, None
        return True


for _nom in ("urllib3.connectionpool", "urllib3.poolmanager", "urllib3.util.retry", "urllib3.response",
             "requests", "poste.donnees"):
    logging.getLogger(_nom).addFilter(_MasqueCles())


def _dec(x) -> Optional[Decimal]:
    if x is None:
        return None
    try:
        d = Decimal(str(x))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _cloture_ny(jour: date) -> datetime:
    return datetime.combine(jour, time(17, 0), NY)


class Fournisseur:
    nom = ""
    variable_env = ""
    param_cle = ""
    entete_cle: Optional[tuple[str, str]] = None  # (nom d'en-tête, gabarit) : la clé hors de l'URL
    par_minute: Optional[int] = None
    par_jour: Optional[int] = None

    def __init__(self, transport: Optional[Transport] = None, horloge: Horloge = maintenant_paris,
                 env: Optional[Mapping[str, str]] = None, cache: Optional[Cache] = None,
                 compteur: Optional[CompteurPersistant] = None):
        env = os.environ if env is None else env
        self.__cle = env.get(self.variable_env) or None
        self.transport = transport or transport_requests
        self.horloge = horloge
        self.cache = cache or Cache(horloge)
        self.limiteur = Limiteur(self.nom, self.par_minute, self.par_jour, compteur, horloge)
        self.disjoncteur = Disjoncteur(horloge=horloge)
        self.dernier_statut: Optional[str] = None

    def __repr__(self):
        return f"<{self.nom} actif={self.actif}>"

    @property
    def cle_presente(self) -> bool:
        return self.__cle is not None

    @property
    def actif(self) -> bool:
        return self.__cle is not None and not self.disjoncteur.ouvert()

    def _statut_corps(self, texte: str) -> int:
        """Certains fournisseurs signalent une erreur avec un HTTP 200 : on lit le corps."""
        return 200

    def _appeler(self, url: str, params: dict, ttl: timedelta) -> Optional[str]:
        if self.__cle is None:
            self.dernier_statut = "clé absente : source désactivée"
            return None
        if self.disjoncteur.ouvert():
            self.dernier_statut = "disjoncteur ouvert (trop d'erreurs 429/403)"
            return None
        cle_cache = f"{self.nom}|{url}|{json.dumps(params, sort_keys=True)}"
        en_cache = self.cache.lire(cle_cache, ttl)
        if en_cache is not None:
            return en_cache
        if not self.limiteur.autoriser():
            self.dernier_statut = "limite de requêtes atteinte"
            log.warning("%s : limite de requêtes atteinte", self.nom)
            return None
        try:
            if self.entete_cle:
                nom, gabarit = self.entete_cle
                rep = self.transport(url, dict(params), headers={nom: gabarit.format(self.__cle)})
            else:
                rep = self.transport(url, {**params, self.param_cle: self.__cle}, headers=None)
        except Exception as e:  # noqa: BLE001 - on ne journalise que le type
            self.dernier_statut = f"erreur réseau ({type(e).__name__})"
            log.warning("%s : erreur réseau (%s)", self.nom, type(e).__name__)
            return None
        statut = rep.statut if rep.statut != 200 else self._statut_corps(rep.texte)
        if statut != 200:
            self.disjoncteur.echec(statut)
            self.dernier_statut = f"HTTP {statut}"
            log.warning("%s : réponse HTTP %s", self.nom, statut)
            return None
        self.disjoncteur.succes()
        self.dernier_statut = "OK"
        self.cache.mettre(cle_cache, rep.texte)
        return rep.texte

    def _json(self, url: str, params: dict, ttl: timedelta):
        texte = self._appeler(url, params, ttl)
        if texte is None:
            return None
        try:
            return json.loads(texte)
        except ValueError:
            self.dernier_statut = "réponse illisible"
            log.warning("%s : réponse illisible", self.nom)
            return None


class Finnhub(Fournisseur):
    nom = "Finnhub"
    variable_env = "FINNHUB_API_KEY"
    param_cle = "token"
    entete_cle = ("X-Finnhub-Token", "{}")
    par_minute = 60
    URL = "https://finnhub.io/api/v1/quote"

    def _quote(self, symbole):
        d = self._json(self.URL, {"symbol": symbole}, timedelta(seconds=60))
        if not d or not d.get("t") or not d.get("c"):
            return None  # symbole inconnu : Finnhub renvoie des zéros
        return d, datetime.fromtimestamp(d["t"], timezone.utc)

    def cotation(self, symbole: str) -> Optional[Donnee]:
        q = self._quote(symbole)
        if q is None or _dec(q[0]["c"]) is None:
            return None
        return Donnee(f"cours {symbole}", _dec(q[0]["c"]), q[1], self.nom, Nature.TEMPS_REEL)

    def variation_pct(self, symbole: str) -> Optional[Donnee]:
        q = self._quote(symbole)
        if q is None or _dec(q[0].get("dp")) is None:
            return None
        return Donnee(f"variation {symbole}", _dec(q[0]["dp"]), q[1], self.nom, Nature.TEMPS_REEL)


class TwelveData(Fournisseur):
    nom = "Twelve Data"
    variable_env = "TWELVEDATA_API_KEY"
    param_cle = "apikey"
    entete_cle = ("Authorization", "apikey {}")
    par_minute = 8
    par_jour = 800
    BASE = "https://api.twelvedata.com"

    def _statut_corps(self, texte):
        try:
            d = json.loads(texte)
        except ValueError:
            return 200
        if isinstance(d, dict) and d.get("status") == "error":
            return int(d.get("code") or 400)
        return 200

    def _quote(self, symbole):
        d = self._json(f"{self.BASE}/quote", {"symbol": symbole, "interval": "1min"}, timedelta(seconds=60))
        if not d:
            return None
        t = d.get("last_quote_at") or d.get("timestamp")
        if not t:
            return None
        return d, datetime.fromtimestamp(int(t), timezone.utc)

    def cotation(self, symbole: str) -> Optional[Donnee]:
        q = self._quote(symbole)
        if q is None or _dec(q[0].get("close")) is None:
            return None
        return Donnee(f"cours {symbole}", _dec(q[0]["close"]), q[1], self.nom, Nature.TEMPS_REEL)

    def variation_pct(self, symbole: str) -> Optional[Donnee]:
        q = self._quote(symbole)
        if q is None or _dec(q[0].get("percent_change")) is None:
            return None
        return Donnee(f"variation {symbole}", _dec(q[0]["percent_change"]), q[1], self.nom, Nature.TEMPS_REEL)

    def historique(self, symbole: str, n: int = 120) -> Optional[Historique]:
        d = self._json(f"{self.BASE}/time_series", {"symbol": symbole, "interval": "1day", "outputsize": n},
                       timedelta(hours=6))
        if not d or not d.get("values"):
            return None
        barres = []
        for v in d["values"]:
            c = _dec(v.get("close"))
            if c is not None:
                barres.append((date.fromisoformat(v["datetime"][:10]), c))
        return Historique(self.nom, sorted(barres)) if barres else None


class Fred(Fournisseur):
    nom = "FRED"
    variable_env = "FRED_API_KEY"
    param_cle = "api_key"
    par_minute = 100
    URL = "https://api.stlouisfed.org/fred/series/observations"

    def taux_10a(self) -> Optional[Donnee]:
        """Taux US 10 ans (série DGS10), publié une fois par jour avec un jour de décalage."""
        d = self._json(self.URL, {"series_id": "DGS10", "file_type": "json", "sort_order": "desc", "limit": 10},
                       timedelta(hours=6))
        if not d:
            return None
        for o in d.get("observations", []):
            v = _dec(o.get("value"))
            if v is not None:
                return Donnee("taux US 10 ans", v, _cloture_ny(date.fromisoformat(o["date"])), self.nom,
                              Nature.QUOTIDIEN)
        return None


class AlphaVantage(Fournisseur):
    nom = "Alpha Vantage"
    variable_env = "ALPHAVANTAGE_API_KEY"
    param_cle = "apikey"
    par_jour = 25
    URL = "https://www.alphavantage.co/query"

    def _statut_corps(self, texte):
        t = texte.lstrip()
        if t.startswith("{"):
            try:
                d = json.loads(t)
            except ValueError:
                return 200
            if "Information" in d or "Note" in d:
                return 429  # message de limite renvoyé avec un HTTP 200
            if "Error Message" in d:
                return 400
        return 200

    def resultats(self, symbole: str) -> Optional[list[Evenement]]:
        """Dates de publication des résultats. L'heure n'est pas fournie : on bloque toute la journée."""
        texte = self._appeler(self.URL, {"function": "EARNINGS_CALENDAR", "symbol": symbole, "horizon": "3month"},
                              timedelta(hours=24))
        if texte is None:
            return None
        evts = []
        for ligne in csv.DictReader(io.StringIO(texte)):
            try:
                jour = date.fromisoformat(ligne["reportDate"])
            except (KeyError, ValueError):
                continue
            nom = f"Résultats {symbole} (heure inconnue)"
            evts.append(Evenement(nom=nom, debut=datetime.combine(jour, time(0, 0), NY), impact="fort"))
            evts.append(Evenement(nom=nom, debut=datetime.combine(jour, time(23, 59), NY), impact="fort"))
        return evts


class YFinance:
    """Données Yahoo en différé (Europe, crypto, indices) via la bibliothèque yfinance."""

    nom = "yfinance (différé)"

    def __init__(self, horloge: Horloge = maintenant_paris, module="auto"):
        if module == "auto":
            try:
                import yfinance as module  # noqa: PLC0415
            except ImportError:
                module = None
        self.yf = module
        self.horloge = horloge
        self.limiteur = Limiteur(self.nom, par_minute=30, horloge=horloge)
        self.disjoncteur = Disjoncteur(horloge=horloge)
        self._cache: dict = {}
        self.dernier_statut: Optional[str] = None
        self.cle_presente = True  # pas de clé

    @property
    def actif(self) -> bool:
        return self.yf is not None and not self.disjoncteur.ouvert()

    def _history(self, symbole, **kw):
        if not self.actif:
            self.dernier_statut = "bibliothèque absente" if self.yf is None else "disjoncteur ouvert"
            return None
        cle = (symbole, tuple(sorted(kw.items())))
        if cle in self._cache and self.horloge() - self._cache[cle][0] < timedelta(seconds=60):
            return self._cache[cle][1]
        if not self.limiteur.autoriser():
            self.dernier_statut = "limite de requêtes atteinte"
            return None
        try:
            df = self.yf.Ticker(symbole).history(**kw)
        except Exception as e:  # noqa: BLE001
            self.dernier_statut = f"erreur ({type(e).__name__})"
            log.warning("%s : erreur (%s)", self.nom, type(e).__name__)
            if "RateLimit" in type(e).__name__:
                self.disjoncteur.echec(429)
            return None
        if df is None or df.empty:
            self.dernier_statut = "aucune donnée"
            return None
        self.disjoncteur.succes()
        self.dernier_statut = "OK"
        self._cache[cle] = (self.horloge(), df)
        return df

    def cotation(self, symbole: str) -> Optional[Donnee]:
        df = self._history(symbole, period="5d", interval="5m")
        if df is None:
            return None
        t = df.index[-1].to_pydatetime()
        # l'horodatage d'une bougie est son début : on ajoute sa durée
        return Donnee(f"cours {symbole}", _dec(round(float(df["Close"].iloc[-1]), 6)), t + timedelta(minutes=5),
                      self.nom, Nature.TEMPS_REEL)

    def variation_pct(self, symbole: str) -> Optional[Donnee]:
        jour = self._history(symbole, period="5d", interval="1d")
        cours = self.cotation(symbole)
        if jour is None or cours is None or len(jour) < 2:
            return None
        veille = Decimal(str(round(float(jour["Close"].iloc[-2]), 6)))
        var = ((cours.valeur - veille) / veille * 100).quantize(Decimal("0.01"))
        return Donnee(f"variation {symbole}", var, cours.horodatage, self.nom, Nature.TEMPS_REEL)

    def historique(self, symbole: str) -> Optional[Historique]:
        df = self._history(symbole, period="1y", interval="1d")
        if df is None:
            return None
        barres = [(ix.date(), _dec(round(float(c), 6))) for ix, c in zip(df.index, df["Close"])]
        return Historique(self.nom, [(d, c) for d, c in barres if c is not None])
