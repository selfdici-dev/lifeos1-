"""Phase 2 : données en direct (tests hors ligne, avec un faux réseau)."""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from poste.donnees.cache import Cache
from poste.donnees.fournisseurs import (AlphaVantage, Finnhub, Fred, Reponse, TwelveData, YFinance)
from poste.donnees.indicateurs import moyenne_mobile
from poste.donnees.limiteur import CompteurPersistant, Disjoncteur, Limiteur
from poste.donnees.marche import Marche
from poste.donnees.modeles import Donnee, Fraicheur, Nature, badge, fraicheur
from poste.plan import charger_plan

PARIS = ZoneInfo("Europe/Paris")
NY = ZoneInfo("America/New_York")
MAINTENANT = datetime(2026, 10, 1, 17, 0, tzinfo=PARIS)  # jeudi, séance US ouverte
CLES = {"FINNHUB_API_KEY": "cle-finnhub-SECRETE", "TWELVEDATA_API_KEY": "cle-td-SECRETE",
        "ALPHAVANTAGE_API_KEY": "cle-av-SECRETE", "FRED_API_KEY": "cle-fred-SECRETE"}


class Horloge:
    def __init__(self, t=MAINTENANT):
        self.t = t

    def __call__(self):
        return self.t

    def avancer(self, **kw):
        self.t += timedelta(**kw)


class FauxReseau:
    """Répond selon l'hôte ; enregistre chaque appel."""

    def __init__(self, reponses):
        self.reponses = reponses  # hôte -> Reponse ou liste de Reponse ou exception
        self.appels = []

    def __call__(self, url, params, headers=None):
        self.appels.append((url, dict(params)))
        for hote, rep in self.reponses.items():
            if hote in url:
                if isinstance(rep, list):
                    rep = rep.pop(0) if len(rep) > 1 else rep[0]
                if isinstance(rep, Exception):
                    raise rep
                return rep
        return Reponse(404, "")


def ts(dt):
    return int(dt.timestamp())


def rep_finnhub(prix="180.5", dp="-0.4", t=None):
    return Reponse(200, json.dumps({"c": float(prix), "dp": float(dp), "pc": 181, "t": ts(t or MAINTENANT)}))


# ---------- fraîcheur ----------

@pytest.mark.parametrize("age,nature,attendu", [
    (timedelta(minutes=2), Nature.TEMPS_REEL, Fraicheur.VERT),
    (timedelta(minutes=20), Nature.TEMPS_REEL, Fraicheur.ORANGE),
    (timedelta(minutes=31), Nature.TEMPS_REEL, Fraicheur.ROUGE),
    (timedelta(days=3), Nature.QUOTIDIEN, Fraicheur.VERT),
    (timedelta(days=5), Nature.QUOTIDIEN, Fraicheur.ORANGE),
    (timedelta(days=7), Nature.QUOTIDIEN, Fraicheur.ROUGE),
])
def test_fraicheur(age, nature, attendu):
    d = Donnee("x", D("1"), MAINTENANT - age, "Test", nature)
    assert fraicheur(d, MAINTENANT) is attendu


def test_donnee_absente_est_rouge_et_badge_perime():
    assert fraicheur(None, MAINTENANT) is Fraicheur.ROUGE
    b = badge("cours NVDA", None, MAINTENANT)
    assert "PÉRIMÉ" in b and "\x1b[31m" in b


def test_badge_indique_source_et_heure_de_paris():
    d = Donnee("cours", D("180"), datetime(2026, 10, 1, 14, 58, tzinfo=timezone.utc), "Finnhub", Nature.TEMPS_REEL)
    b = badge("cours NVDA", d, MAINTENANT)
    assert "Finnhub" in b and "16:58" in b and "VERT" in b


def test_date_sans_fuseau_refusee():
    with pytest.raises(ValueError):
        Donnee("x", D("1"), datetime(2026, 10, 1, 12, 0), "T", Nature.TEMPS_REEL)


# ---------- limiteur, disjoncteur, compteur ----------

def test_limiteur_par_minute():
    h = Horloge()
    lim = Limiteur("t", par_minute=2, horloge=h)
    assert lim.autoriser() and lim.autoriser()
    assert not lim.autoriser()
    h.avancer(seconds=61)
    assert lim.autoriser()


def test_compteur_persistant_25_par_jour(tmp_path):
    h = Horloge()
    chemin = tmp_path / "compteurs.json"
    lim = Limiteur("alphavantage", par_jour=25, compteur=CompteurPersistant(chemin), horloge=h)
    for _ in range(25):
        assert lim.autoriser()
    assert not lim.autoriser()
    # redémarrage du programme : le compteur survit
    lim2 = Limiteur("alphavantage", par_jour=25, compteur=CompteurPersistant(chemin), horloge=h)
    assert not lim2.autoriser()
    h.avancer(days=1)
    assert lim2.autoriser()


def test_disjoncteur_apres_3_erreurs_429_403():
    h = Horloge()
    dj = Disjoncteur(horloge=h)
    dj.echec(429)
    dj.echec(500)  # une erreur serveur ne compte pas
    dj.echec(403)
    assert not dj.ouvert()
    dj.echec(429)
    assert dj.ouvert()
    h.avancer(minutes=31)
    assert not dj.ouvert()


def test_disjoncteur_remis_a_zero_par_un_succes():
    dj = Disjoncteur(horloge=Horloge())
    dj.echec(429); dj.echec(429); dj.succes(); dj.echec(429); dj.echec(429)
    assert not dj.ouvert()


def test_cache_ttl(tmp_path):
    h = Horloge()
    c = Cache(h, chemin=tmp_path / "cache.json")
    c.mettre("k", "v")
    assert c.lire("k", timedelta(minutes=1)) == "v"
    assert Cache(h, chemin=tmp_path / "cache.json").lire("k", timedelta(minutes=1)) == "v"  # persistant
    h.avancer(minutes=2)
    assert c.lire("k", timedelta(minutes=1)) is None


# ---------- fournisseurs ----------

def _fournisseur(cls, reseau, env=CLES, h=None, **kw):
    return cls(transport=reseau, horloge=h or Horloge(), env=env, **kw)


def test_cle_manquante_desactive_la_source():
    reseau = FauxReseau({"finnhub": rep_finnhub()})
    f = _fournisseur(Finnhub, reseau, env={})
    assert not f.actif
    assert f.cotation("NVDA") is None
    assert reseau.appels == []


def test_finnhub_cotation_et_variation():
    f = _fournisseur(Finnhub, FauxReseau({"finnhub": rep_finnhub()}))
    d = f.cotation("NVDA")
    assert d.valeur == D("180.5") and d.source == "Finnhub" and d.nature is Nature.TEMPS_REEL
    assert f.variation_pct("SPY").valeur == D("-0.4")


def test_finnhub_symbole_inconnu_renvoie_none():
    f = _fournisseur(Finnhub, FauxReseau({"finnhub": Reponse(200, json.dumps({"c": 0, "dp": None, "t": 0}))}))
    assert f.cotation("ZZZZ") is None


def test_twelvedata_erreur_dans_le_corps_compte_comme_429():
    corps = json.dumps({"code": 429, "message": "limit", "status": "error"})
    reseau = FauxReseau({"twelvedata": Reponse(200, corps)})
    f = _fournisseur(TwelveData, reseau)
    for _ in range(3):
        assert f.cotation("NVDA") is None
    assert f.disjoncteur.ouvert()
    n = len(reseau.appels)
    assert f.cotation("NVDA") is None
    assert len(reseau.appels) == n  # disjoncteur ouvert : plus aucun appel


def test_twelvedata_historique():
    valeurs = [{"datetime": (date(2026, 10, 1) - timedelta(days=i)).isoformat(), "close": str(100 + i)}
               for i in range(60)]
    f = _fournisseur(TwelveData, FauxReseau({"twelvedata": Reponse(200, json.dumps({"status": "ok", "values": valeurs}))}))
    h = f.historique("NVDA")
    assert h.source == "Twelve Data"
    assert h.barres[0][0] < h.barres[-1][0]  # trié du plus ancien au plus récent
    assert h.barres[-1] == (date(2026, 10, 1), D("100"))


def test_fred_ignore_les_valeurs_manquantes():
    obs = {"observations": [{"date": "2026-09-30", "value": "."}, {"date": "2026-09-29", "value": "4.21"}]}
    f = _fournisseur(Fred, FauxReseau({"stlouisfed": Reponse(200, json.dumps(obs))}))
    d = f.taux_10a()
    assert d.valeur == D("4.21") and d.nature is Nature.QUOTIDIEN
    assert d.horodatage.astimezone(NY).date() == date(2026, 9, 29)


def test_alphavantage_limite_dans_le_corps_et_compteur(tmp_path):
    corps = json.dumps({"Information": "Our standard API rate limit is 25 requests per day."})
    reseau = FauxReseau({"alphavantage": Reponse(200, corps)})
    f = _fournisseur(AlphaVantage, reseau, compteur=CompteurPersistant(tmp_path / "c.json"))
    assert f.resultats("NVDA") is None
    assert json.loads((tmp_path / "c.json").read_text())  # l'appel a été compté


def test_alphavantage_resultats_bloquent_toute_la_journee(tmp_path):
    csv = "symbol,name,reportDate,fiscalDateEnding,estimate,currency\nNVDA,NVIDIA,2026-11-18,2026-10-31,1.2,USD\n"
    f = _fournisseur(AlphaVantage, FauxReseau({"alphavantage": Reponse(200, csv)}),
                     compteur=CompteurPersistant(tmp_path / "c.json"))
    evts = f.resultats("NVDA")
    debuts = sorted(e.debut.astimezone(NY) for e in evts)
    # heure de publication inconnue : on bloque du début à la fin du jour (heure de New York)
    assert debuts[0] == datetime(2026, 11, 18, 0, 0, tzinfo=NY)
    assert debuts[-1].date() == date(2026, 11, 18) and debuts[-1].hour == 23
    assert all(e.impact == "fort" for e in evts)


def test_erreur_reseau_ne_plante_pas():
    f = _fournisseur(Finnhub, FauxReseau({"finnhub": ConnectionError("boum")}))
    assert f.cotation("NVDA") is None


def test_aucune_cle_dans_les_logs(caplog):
    caplog.set_level(logging.DEBUG)
    exc = ConnectionError("https://finnhub.io/api/v1/quote?symbol=NVDA&token=cle-finnhub-SECRETE")
    for cls, hote in [(Finnhub, "finnhub"), (TwelveData, "twelvedata"), (Fred, "stlouisfed")]:
        _fournisseur(cls, FauxReseau({hote: exc}))._appeler("https://" + hote, {"a": "b"}, timedelta(0))
        _fournisseur(cls, FauxReseau({hote: Reponse(429, "token=cle-finnhub-SECRETE")}))._appeler(
            "https://" + hote, {}, timedelta(0))
    assert caplog.records
    for cle in CLES.values():
        assert cle not in caplog.text


def test_cache_evite_un_second_appel():
    reseau = FauxReseau({"finnhub": rep_finnhub()})
    f = _fournisseur(Finnhub, reseau)
    f.cotation("NVDA"); f.cotation("NVDA")
    assert len(reseau.appels) == 1


def test_yfinance_desactive_si_absent():
    f = YFinance(horloge=Horloge(), module=None)
    assert not f.actif and f.cotation("NVDA") is None


# ---------- indicateurs : aucune fuite du futur ----------

def _barres(n, debut=date(2026, 6, 1)):
    return [(debut + timedelta(days=i), D(100 + i)) for i in range(n)]


def test_moyenne_mobile_n_utilise_que_le_passe():
    barres = _barres(80)
    t = barres[60][0]
    mm = moyenne_mobile(barres, avant=t, n=50)
    assert mm == sum(c for _, c in barres[10:60]) / 50
    # changer le futur (y compris le jour T) ne change pas le signal à T
    futur_modifie = barres[:60] + [(d, c * 10) for d, c in barres[60:]]
    assert moyenne_mobile(futur_modifie, avant=t, n=50) == mm


def test_moyenne_mobile_historique_insuffisant():
    assert moyenne_mobile(_barres(30), avant=date(2026, 12, 1), n=50) is None


# ---------- agrégateur ----------

def _marche(reponses, env=CLES, yf=None, tmp_path=None):
    h = Horloge()
    reseau = FauxReseau(reponses)
    return Marche(
        finnhub=Finnhub(transport=reseau, horloge=h, env=env),
        twelvedata=TwelveData(transport=reseau, horloge=h, env=env),
        fred=Fred(transport=reseau, horloge=h, env=env),
        alphavantage=AlphaVantage(transport=reseau, horloge=h, env=env,
                                  compteur=CompteurPersistant(tmp_path / "c.json") if tmp_path else None),
        yfinance=yf or YFinance(horloge=h, module=None),
        horloge=h,
    ), reseau


PLAN = charger_plan()


def test_bascule_sur_la_source_suivante():
    td = Reponse(200, json.dumps({"close": "181", "percent_change": "0.1", "timestamp": ts(MAINTENANT)}))
    m, _ = _marche({"finnhub": Reponse(500, ""), "twelvedata": td})
    d = m.cours(PLAN.trade("NVDA-1"))
    assert d.source == "Twelve Data" and d.valeur == D("181")


def test_source_perimee_ignoree_si_une_autre_est_fraiche():
    vieux = rep_finnhub(t=MAINTENANT - timedelta(hours=3))
    td = Reponse(200, json.dumps({"close": "181", "percent_change": "0.1", "timestamp": ts(MAINTENANT)}))
    m, _ = _marche({"finnhub": vieux, "twelvedata": td})
    assert m.cours(PLAN.trade("NVDA-1")).source == "Twelve Data"


def test_toutes_sources_en_echec_donne_rouge():
    m, _ = _marche({}, env={})
    assert m.cours(PLAN.trade("NVDA-1")) is None
    assert m.taux_10a() is None


def test_etf_sans_symbole_est_perime():
    m, reseau = _marche({"finnhub": rep_finnhub()})
    assert m.cours(PLAN.trade("SEMI-ETF-1")) is None


def test_releve_complet_et_liste_des_perimes():
    m, _ = _marche({}, env={})
    r = m.releve(PLAN.trade("NVDA-1"))
    assert set(r.perimees(MAINTENANT)) >= {"cours", "mm50", "eurusd", "taux_us10a", "sp500_variation"}


# ---------- la fiche refuse les données périmées ----------

def test_fiche_interdite_si_donnees_perimees():
    from poste.fiche import Saisie, Verdict, build_order_sheet
    s = Saisie(prix_vendeur_eur=D("163.70"), cours_ref=D("180"), mm50_ref=D("170"), eurusd=D("1.10"),
               taux_us10a_pct=D("4.2"), sp500_variation_seance_pct=D("0"), evenement_majeur_24h=False)
    f = build_order_sheet("NVDA-1", s, 1, plan=PLAN, perimees=["cours"])
    assert f.verdict is Verdict.INTERDIT and f.quantite is None and f.etapes == []
    assert "PÉRIMÉ" in f.texte()
