"""Corrections de la revue (phase 5) : points 1, 3, 4 (point haut), 7, 8, 11."""
import http.server
import io
import logging
import threading
from datetime import datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from poste.bilan import bilan_hebdo
from poste.donnees.fournisseurs import AlphaVantage, Finnhub, Fred, TwelveData, transport_requests
from poste.exposition import Position
from poste.fiche import Saisie, Verdict, build_order_sheet
from poste.journal import Achat, FicheJournal, Journal, Vente
from poste.plan import charger_plan
from poste.rappels import RAPPELS_DEFAUT, Rappel, ouverture_us_paris, prochains_rappels
from poste.reglages import Reglages

PARIS = ZoneInfo("Europe/Paris")
PLAN = charger_plan()
LUNDI = datetime(2026, 10, 5, 16, 0, tzinfo=PARIS)


def saisie(**kw):
    base = dict(prix_vendeur_eur=D("163.70"), cours_ref=D("180"), mm50_ref=D("170"), eurusd=D("1.10"),
                taux_us10a_pct=D("4.2"), sp500_variation_seance_pct=D("0"), evenement_majeur_24h=False)
    base.update(kw)
    return Saisie(**base)


# ---------- 1. liquidités ----------

def test_liquidites_plafonnent_la_quantite():
    pos = [Position(instrument="x", theme="crypto", valeur_eur=D("1000")),
           Position(instrument="y", theme="semi-conducteurs", valeur_eur=D("1000"))]
    f = build_order_sheet("NVDA-1", saisie(), 3, plan=PLAN, positions=pos)
    assert f.quantite is not None
    assert D("2000") + f.montant_engage_eur <= PLAN.capital_eur
    assert any("liquidités" in r.lower() for r in f.raisons + f.notes)


def test_liquidites_insuffisantes_interdit():
    pos = [Position(instrument="x", theme="crypto", valeur_eur=D("2450"))]
    f = build_order_sheet("NVDA-1", saisie(), 3, plan=PLAN, positions=pos)
    assert f.verdict is Verdict.INTERDIT and f.quantite is None
    assert any("liquidités" in r.lower() for r in f.raisons)


def test_resultat_realise_change_les_liquidites():
    pos = [Position(instrument="x", theme="crypto", valeur_eur=D("2450"))]
    f = build_order_sheet("NVDA-1", saisie(), 3, plan=PLAN, positions=pos, resultat_realise_eur=D("300"))
    assert f.quantite is not None
    assert D("2450") + f.montant_engage_eur <= PLAN.capital_eur + D("300")


# ---------- 3. perte maximale honnête ----------

def test_perte_maximale_est_la_mise_entiere():
    f = build_order_sheet("NVDA-1", saisie(), 1, plan=PLAN)
    assert f.perte_au_stop_eur == D("34.82")
    assert f.perte_max_eur == f.quantite * f.prix_limite_eur + 2 * PLAN.frais_par_ordre_eur
    t = f.texte()
    assert "Perte au stop : 34.82 €" in t
    assert f"PERTE MAXIMALE : {f.perte_max_eur} €" in t
    assert "-30 %" in t  # exemple concret de gap


# ---------- 4. seuil depuis le point haut ----------

def test_baisse_depuis_le_point_haut(tmp_path):
    j = Journal(tmp_path / "j.json", frais_par_ordre=D("1"))
    a = j.acheter(Achat(quand=LUNDI, trade_id="NVDA-1", quantite=10, prix_execution_eur=D("100"),
                        stop_eur=D("90"), raison="x"))
    j.vendre(a.id, Vente(quand=LUNDI + timedelta(hours=1), quantite=10, prix_eur=D("120")))
    b = j.acheter(Achat(quand=LUNDI + timedelta(hours=2), trade_id="NVDA-1", quantite=10,
                        prix_execution_eur=D("100"), stop_eur=D("90"), raison="x"))
    j.vendre(b.id, Vente(quand=LUNDI + timedelta(hours=3), quantite=10, prix_eur=D("60")))
    # sommet +198 (200 − 2 frais), puis −1 (achat) puis −401 : 198 − (−204) = 402
    assert j.perte_cumulee() == D("402")


def test_point_haut_rattrape_remet_a_zero(tmp_path):
    j = Journal(tmp_path / "j.json", frais_par_ordre=D("0"))
    a = j.acheter(Achat(quand=LUNDI, trade_id="NVDA-1", quantite=1, prix_execution_eur=D("100"),
                        stop_eur=D("90"), raison="x"))
    j.vendre(a.id, Vente(quand=LUNDI + timedelta(hours=1), quantite=1, prix_eur=D("80")))
    b = j.acheter(Achat(quand=LUNDI + timedelta(hours=2), trade_id="NVDA-1", quantite=1,
                        prix_execution_eur=D("100"), stop_eur=D("90"), raison="x"))
    j.vendre(b.id, Vente(quand=LUNDI + timedelta(hours=3), quantite=1, prix_eur=D("130")))
    assert j.perte_cumulee() == D("0")  # nouveau point haut à +10


# ---------- 7. aucune clé dans les logs, même en mode DEBUG ----------

@pytest.fixture
def serveur_local():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_aucune_cle_dans_les_logs_urllib3_debug(serveur_local):
    flux = io.StringIO()
    h = logging.StreamHandler(flux)
    racine = logging.getLogger()
    ancien = racine.level
    racine.addHandler(h)
    racine.setLevel(logging.DEBUG)
    try:
        env = {"FINNHUB_API_KEY": "CLE-FH-1", "TWELVEDATA_API_KEY": "CLE-TD-2",
               "ALPHAVANTAGE_API_KEY": "CLE-AV-3", "FRED_API_KEY": "CLE-FRED-4"}
        for cls in (Finnhub, TwelveData, AlphaVantage, Fred):
            f = cls(env=env, transport=transport_requests)
            f._appeler(serveur_local + "/q", {"symbol": "NVDA"}, timedelta(0))
    finally:
        racine.removeHandler(h)
        racine.setLevel(ancien)
    texte = flux.getvalue()
    assert "GET /q" in texte  # urllib3 a bien journalisé les requêtes
    for cle in ("CLE-FH-1", "CLE-TD-2", "CLE-AV-3", "CLE-FRED-4"):
        assert cle not in texte


def test_finnhub_et_twelvedata_cle_en_entete():
    appels = []

    def transport(url, params, headers=None):
        appels.append((params, headers))
        from poste.donnees.fournisseurs import Reponse
        return Reponse(200, "{}")
    Finnhub(env={"FINNHUB_API_KEY": "K1"}, transport=transport)._appeler("u", {}, timedelta(0))
    TwelveData(env={"TWELVEDATA_API_KEY": "K2"}, transport=transport)._appeler("u", {}, timedelta(0))
    assert "K1" not in str(appels[0][0]) and appels[0][1] == {"X-Finnhub-Token": "K1"}
    assert "K2" not in str(appels[1][0]) and appels[1][1] == {"Authorization": "apikey K2"}


# ---------- 8. rappel calé sur l'ouverture américaine ----------

@pytest.mark.parametrize("jour,attendu", [
    (datetime(2026, 10, 23, tzinfo=PARIS), "15:30"),
    (datetime(2026, 10, 27, tzinfo=PARIS), "14:30"),   # Europe à l'heure d'hiver, pas encore les USA
    (datetime(2026, 11, 3, tzinfo=PARIS), "15:30"),
    (datetime(2026, 3, 10, tzinfo=PARIS), "14:30"),    # USA à l'heure d'été (8 mars), pas encore l'Europe
])
def test_ouverture_us_en_heure_de_paris(jour, attendu):
    assert ouverture_us_paris(jour.date()).strftime("%H:%M") == attendu


def test_rappel_avant_ouverture_suit_le_decalage():
    r = Rappel(jours=(1,), avant_ouverture_us_min=15, message="La séance US ouvre à {ouverture_us}.")
    n = prochains_rappels(datetime(2026, 10, 26, 8, 0, tzinfo=PARIS), [r], nombre=2)
    assert n[0][0].strftime("%d/%m %H:%M") == "27/10 14:15"
    assert n[1][0].strftime("%d/%m %H:%M") == "03/11 15:15"
    assert r.texte(n[0][0].date()) == "La séance US ouvre à 14:30."


def test_rappel_exige_une_heure_ou_un_ancrage():
    with pytest.raises(ValueError):
        Rappel(jours=(1,), message="x")


def test_ancien_rappel_15h15_remplace():
    r = Reglages.model_validate({"niveau": 1, "rappels": [
        {"jours": [0, 1, 2, 3, 4], "heure": "15:15",
         "message": "La séance US ouvre à 15:30 (Paris) : test de feu vert avant tout achat."}]})
    assert r.rappels[0].avant_ouverture_us_min == 15 and r.rappels[0].heure is None


def test_rappels_par_defaut_sans_heure_figee_d_ouverture():
    assert not any("15:30" in r.message for r in RAPPELS_DEFAUT)


# ---------- 11. achat comparé à la fiche ----------

def test_bilan_quantite_et_stop_differents_de_la_fiche(tmp_path):
    j = Journal(tmp_path / "j.json", frais_par_ordre=D("1"))
    f = j.noter_fiche(FicheJournal(quand=LUNDI - timedelta(minutes=5), trade_id="NVDA-1", verdict="FEU VERT",
                                   prix_limite_eur=D("164.03"), prix_stop_eur=D("147.62"), quantite=2))
    j.acheter(Achat(quand=LUNDI, trade_id="NVDA-1", quantite=5, prix_execution_eur=D("164"),
                    stop_eur=D("140"), raison="x", fiche_id=f.id))
    b = bilan_hebdo(j, PLAN, datetime(2026, 10, 9, 22, 5, tzinfo=PARIS))
    assert b.erreurs["quantité au-dessus de la fiche"] == 1
    assert b.erreurs["stop plus bas que la fiche"] == 1


def test_ecarts_achat_fiche_disponibles_pour_l_assistant(tmp_path):
    from poste.bilan import ecarts_avec_fiche
    j = Journal(tmp_path / "j.json", frais_par_ordre=D("1"))
    f = j.noter_fiche(FicheJournal(quand=LUNDI, trade_id="NVDA-1", verdict="FEU VERT",
                                   prix_limite_eur=D("164.03"), prix_stop_eur=D("147.62"), quantite=2))
    a = Achat(quand=LUNDI, trade_id="NVDA-1", quantite=2, prix_execution_eur=D("164"), stop_eur=D("147.62"),
              raison="x", fiche_id=f.id)
    assert ecarts_avec_fiche(a, f) == []
    a2 = a.model_copy(update={"trade_id": "BTC-ETP-1"})
    assert any("instrument" in e for e in ecarts_avec_fiche(a2, f))


from hypothesis import given, settings, strategies as st


@settings(max_examples=300, deadline=None)
@given(investi=st.decimals(min_value=D("0"), max_value=D("3000"), places=2),
       realise=st.decimals(min_value=D("-500"), max_value=D("500"), places=2),
       niveau=st.sampled_from([1, 2, 3]),
       prix=st.decimals(min_value=D("1"), max_value=D("400"), places=2))
def test_jamais_plus_investi_que_les_liquidites(investi, realise, niveau, prix):
    s = saisie(prix_vendeur_eur=prix, cours_ref=(prix * D("1.10")).quantize(D("0.01")),
               mm50_ref=(prix * D("1.0")).quantize(D("0.01")))
    pos = [Position(instrument="x", theme="crypto", valeur_eur=investi)] if investi else []
    f = build_order_sheet("NVDA-1", s, niveau, plan=PLAN, positions=pos, resultat_realise_eur=realise)
    if f.quantite is not None:
        assert investi + f.montant_engage_eur <= PLAN.capital_eur + realise
