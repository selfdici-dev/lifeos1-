"""Phase 6 : exécution automatisée, désactivée par défaut. Tests avec un faux courtier en mémoire."""
from datetime import datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from poste.execution import limites
from poste.execution.arret import Interrupteur
from poste.execution.courtier import CourtierFactice
from poste.execution.executeur import Executeur
from poste.execution.modeles import Mode, OrdrePropose
from poste.execution.simulation import PHRASE_AUTORISATION, RegistreSimulation, porte_ordres_reels
from poste.journal import Achat, Journal, Vente
from poste.plan import charger_plan
from poste.reglages import Reglages

PARIS = ZoneInfo("Europe/Paris")
PLAN = charger_plan()
SEANCE = datetime(2026, 10, 6, 17, 0, tzinfo=PARIS)  # mardi, 11:00 à New York


def ordre(**kw):
    base = dict(trade_id="NVDA-1", isin="US67066G1040", quantite=2, prix_limite=D("164.03"),
                prix_stop=D("147.62"), devise="EUR", fiche_id="F1", verdict="FEU VERT", perimees=())
    base.update(kw)
    return OrdrePropose(**base)


@pytest.fixture
def env(tmp_path):
    journal = Journal(tmp_path / "journal.json", frais_par_ordre=D("1"))
    courtier = CourtierFactice(compte="DU1234567")  # compte de simulation (paper)
    registre = RegistreSimulation(tmp_path / "simulation.json")
    arret = Interrupteur(tmp_path / "ARRET")
    horloge = {"t": SEANCE}

    def fabrique(mode=Mode.AUTO, confirmer=lambda o: True, autorisation=tmp_path / "AUTORISATION.txt"):
        return Executeur(courtier=courtier, journal=journal, plan=PLAN, niveau=1, mode=mode, registre=registre,
                         interrupteur=arret, horloge=lambda: horloge["t"], confirmer=confirmer,
                         chemin_autorisation=autorisation, attente=lambda s: None)
    return dict(journal=journal, courtier=courtier, registre=registre, arret=arret, horloge=horloge,
                fabrique=fabrique, tmp=tmp_path)


# ---------- défauts et réglages ----------

def test_mode_manuel_par_defaut():
    assert Reglages().mode_execution is Mode.MANUEL


def test_limites_non_reglables_depuis_les_reglages():
    with pytest.raises(ValueError):
        Reglages.model_validate({"niveau": 1, "montant_max_par_ordre_eur": "5000"})


def test_mode_manuel_n_envoie_jamais(env):
    cr = env["fabrique"](mode=Mode.MANUEL).envoyer(ordre())
    assert not cr.envoye and env["courtier"].ordres == []


# ---------- limites codées en dur ----------

def test_constantes():
    assert limites.MONTANT_MAX_PAR_ORDRE_EUR == D("500")
    assert limites.ORDRES_MAX_PAR_JOUR == 2
    assert "NDX-TURBO-1" not in limites.LISTE_BLANCHE


@pytest.mark.parametrize("modif,mot", [
    (dict(quantite=4), "montant"),                       # 4 × 164 = 656 € > 500 €
    (dict(trade_id="NDX-TURBO-1", isin="DE000XXX"), "turbo"),
    (dict(trade_id="BTC-ETP-1", isin="XX"), "liste blanche"),
    (dict(isin="US0000000000"), "isin"),
    (dict(verdict="INTERDIT"), "feu vert"),
    (dict(verdict="ATTENDRE"), "feu vert"),
    (dict(prix_stop=D("170")), "stop"),
    (dict(devise="USD"), "devise"),
])
def test_ordres_refuses(env, modif, mot):
    cr = env["fabrique"]().envoyer(ordre(**modif))
    assert not cr.envoye
    assert any(mot in r.lower() for r in cr.raisons), cr.raisons
    assert env["courtier"].ordres == []


def test_turbo_refuse_meme_en_confirmation(env):
    cr = env["fabrique"](mode=Mode.CONFIRMATION).envoyer(ordre(trade_id="NDX-TURBO-1", isin="DE000XXX"))
    assert not cr.envoye


@pytest.mark.parametrize("quand,ok", [
    (datetime(2026, 10, 23, 15, 35, tzinfo=PARIS), False),  # 9:35 New York : trop tôt
    (datetime(2026, 10, 23, 15, 50, tzinfo=PARIS), True),   # 9:50 New York
    (datetime(2026, 10, 27, 14, 50, tzinfo=PARIS), True),   # semaine décalée : 9:50 New York
    (datetime(2026, 10, 27, 21, 50, tzinfo=PARIS), False),  # 16:50 New York : fermé
    (datetime(2026, 10, 24, 17, 0, tzinfo=PARIS), False),   # samedi
])
def test_creneau_horaire(env, quand, ok):
    env["horloge"]["t"] = quand
    assert env["fabrique"]().envoyer(ordre()).envoye is ok


def test_nombre_max_d_ordres_par_jour(env):
    ex = env["fabrique"]()
    assert ex.envoyer(ordre(fiche_id="F1")).envoye
    assert ex.envoyer(ordre(fiche_id="F2")).envoye
    cr = ex.envoyer(ordre(fiche_id="F3"))
    assert not cr.envoye and any("par jour" in r for r in cr.raisons)


# ---------- modes ----------

def test_confirmation_refusee_n_envoie_rien(env):
    cr = env["fabrique"](mode=Mode.CONFIRMATION, confirmer=lambda o: False).envoyer(ordre())
    assert not cr.envoye and env["courtier"].ordres == []


def test_confirmation_acceptee_envoie_un_ordre(env):
    vus = []
    cr = env["fabrique"](mode=Mode.CONFIRMATION, confirmer=lambda o: vus.append(o) or True).envoyer(ordre())
    assert cr.envoye and len(vus) == 1


# ---------- stop chez le courtier, rapprochement ----------

def test_achat_et_stop_poses_ensemble_chez_le_courtier(env):
    cr = env["fabrique"]().envoyer(ordre())
    assert cr.envoye
    stops = [o for o in env["courtier"].ordres if o.type == "STP"]
    assert len(stops) == 1 and stops[0].sens == "SELL" and stops[0].duree == "GTC"
    assert stops[0].prix == D("147.62") and stops[0].parent_id is not None
    assert stops[0].statut == "Submitted"  # actif chez le courtier, indépendant de ton ordinateur


def test_journal_ne_note_que_l_execution_reelle(env):
    env["courtier"].comportement = dict(prix_execution=D("163.95"), quantite_executee=1)
    cr = env["fabrique"]().envoyer(ordre())
    p = env["journal"].positions[-1]
    assert p.achat.prix_execution_eur == D("163.95")  # prix du courtier, pas le prix limite
    assert p.achat.quantite == 1                       # exécution partielle notée telle quelle
    assert cr.envoye


def test_ordre_non_execute_rien_dans_le_journal(env):
    env["courtier"].comportement = dict(statut="Submitted", quantite_executee=0)
    cr = env["fabrique"]().envoyer(ordre())
    assert cr.envoye and env["journal"].positions == []
    assert "en attente" in cr.etat


@pytest.mark.parametrize("comportement,mot", [
    (dict(statut="Inconnu"), "inattendu"),
    (dict(prix_execution=D("170")), "prix limite"),
    (dict(sans_stop=True), "stop"),
    (dict(exception=True), "erreur"),
    (dict(quantite_executee=5), "quantité"),
])
def test_reponse_inattendue_declenche_l_arret(env, comportement, mot):
    env["courtier"].comportement = comportement
    cr = env["fabrique"]().envoyer(ordre())
    assert env["arret"].actif
    assert any(mot in a.lower() for a in cr.anomalies), cr.anomalies
    assert env["registre"].anomalies()  # comptée dans la simulation


# ---------- interrupteur d'arrêt ----------

def test_interrupteur_bloque_et_annule_les_achats_mais_garde_les_stops(env):
    env["courtier"].comportement = dict(statut="Submitted", quantite_executee=0)
    ex = env["fabrique"]()
    ex.envoyer(ordre(fiche_id="F1"))
    env["courtier"].comportement = {}
    ex.envoyer(ordre(fiche_id="F2"))  # exécuté, son stop est actif
    ex.arreter("bouton d'arrêt")
    achats_ouverts = [o for o in env["courtier"].ordres if o.sens == "BUY" and o.statut in ("Submitted", "PreSubmitted")]
    stops_actifs = [o for o in env["courtier"].ordres if o.type == "STP" and o.statut == "Submitted"]
    assert achats_ouverts == []
    assert len(stops_actifs) == 1  # le stop qui protège la position exécutée reste en place
    cr = ex.envoyer(ordre(fiche_id="F3"))
    assert not cr.envoye and any("arrêt" in r.lower() for r in cr.raisons)
    # l'arrêt survit à un redémarrage
    assert Interrupteur(env["tmp"] / "ARRET").actif


def test_donnees_perimees_declenchent_l_arret(env):
    cr = env["fabrique"]().envoyer(ordre(perimees=("cours",)))
    assert not cr.envoye and env["arret"].actif


def test_seuil_de_perte_declenche_l_arret(env):
    j = env["journal"]
    a = j.acheter(Achat(quand=SEANCE - timedelta(days=2), trade_id="NVDA-1", quantite=10,
                        prix_execution_eur=D("100"), stop_eur=D("90"), raison="x"))
    j.vendre(a.id, Vente(quand=SEANCE - timedelta(days=1), quantite=10, prix_eur=D("70")))  # -302 €
    cr = env["fabrique"]().envoyer(ordre())
    assert not cr.envoye and env["arret"].actif


# ---------- simulation obligatoire avant le réel ----------

def test_compte_reel_refuse_sans_simulation(env):
    env["courtier"].compte = "U1234567"  # compte réel
    cr = env["fabrique"]().envoyer(ordre())
    assert not cr.envoye and env["arret"].actif
    assert any("simulation" in r.lower() for r in cr.raisons)


def _remplir_simulation(registre, debut, n, anomalie_a=None):
    for k in range(n):
        registre.noter(quand=debut + timedelta(days=k * 32 / max(n - 1, 1)), ordre=ordre(fiche_id=f"F{k}"),
                       etat="Filled", anomalies=["x"] if k == anomalie_a else [], ecarts_fiche=[])


def test_porte_ordres_reels(tmp_path):
    reg = RegistreSimulation(tmp_path / "s.json")
    autor = tmp_path / "AUTORISATION.txt"
    debut = datetime(2026, 11, 1, 17, 0, tzinfo=PARIS)
    _remplir_simulation(reg, debut, 19)
    ok, raisons = porte_ordres_reels(reg, debut + timedelta(days=40), autor)
    assert not ok and any("20" in r for r in raisons)
    _remplir_simulation(reg, debut + timedelta(days=33), 1)
    ok, raisons = porte_ordres_reels(reg, debut + timedelta(days=40), autor)
    assert not ok and any("autorisation" in r.lower() for r in raisons)
    autor.write_text(PHRASE_AUTORISATION + "\n", encoding="utf-8")
    ok, raisons = porte_ordres_reels(reg, debut + timedelta(days=40), autor)
    assert ok, raisons


def test_anomalie_remet_la_simulation_a_zero(tmp_path):
    reg = RegistreSimulation(tmp_path / "s.json")
    autor = tmp_path / "AUTORISATION.txt"
    autor.write_text(PHRASE_AUTORISATION, encoding="utf-8")
    debut = datetime(2026, 11, 1, 17, 0, tzinfo=PARIS)
    _remplir_simulation(reg, debut, 25, anomalie_a=20)
    ok, raisons = porte_ordres_reels(reg, debut + timedelta(days=40), autor)
    assert not ok  # seulement 4 ordres sans anomalie depuis la dernière


def test_moins_de_30_jours_refuse(tmp_path):
    reg = RegistreSimulation(tmp_path / "s.json")
    autor = tmp_path / "AUTORISATION.txt"
    autor.write_text(PHRASE_AUTORISATION, encoding="utf-8")
    debut = datetime(2026, 11, 1, 17, 0, tzinfo=PARIS)
    for k in range(25):
        reg.noter(quand=debut + timedelta(days=k), ordre=ordre(), etat="Filled", anomalies=[], ecarts_fiche=[])
    ok, raisons = porte_ordres_reels(reg, debut + timedelta(days=25), autor)
    assert not ok and any("30 jours" in r for r in raisons)


def test_simulation_compare_avec_la_fiche(env):
    env["courtier"].comportement = dict(prix_execution=D("163.95"))
    env["fabrique"]().envoyer(ordre())
    e = env["registre"].entrees[-1]
    assert e["fiche_id"] == "F1" and e["etat"] == "Filled"
    assert "ecarts_fiche" in e


# ---------- clés du courtier ----------

def test_ibkr_sans_identifiants_dans_le_code():
    import inspect
    from poste.execution import ibkr
    params = inspect.signature(ibkr.CourtierIBKR.__init__).parameters
    assert set(params) <= {"self", "hote", "port", "client_id", "ib"}
    source = inspect.getsource(ibkr).lower()
    for mot in ("password", "mot_de_passe", "secret"):
        assert mot not in source


def test_arret_signale_l_echec_d_annulation(env):
    def panne():
        raise ConnectionError("injoignable")
    env["courtier"].annuler_achats_en_attente = panne
    ex = env["fabrique"]()
    assert ex.arreter("bouton d'arrêt") is None  # None = annulation NON confirmée
    assert env["arret"].actif


def test_arret_actif_ne_contacte_plus_le_courtier(env):
    env["arret"].declencher("test", SEANCE)
    appels = []
    env["courtier"].est_simulation = lambda: appels.append(1) or True
    cr = env["fabrique"]().envoyer(ordre())
    assert not cr.envoye and appels == []
