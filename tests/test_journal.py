"""Phase 4 : journal, tableau de risque, bilan hebdomadaire, rappels."""
from datetime import datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from poste.bilan import AJUSTEMENT_MIN_TRADES, bilan_hebdo, periode_bilan
from poste.journal import Achat, FicheJournal, Journal, Vente
from poste.plan import charger_plan
from poste.rappels import Rappel, envoyer_ntfy, prochains_rappels
from poste.risque import tableau_risque

PARIS = ZoneInfo("Europe/Paris")
PLAN = charger_plan()
LUNDI = datetime(2026, 10, 5, 16, 0, tzinfo=PARIS)


def achat(j, **kw):
    base = dict(quand=LUNDI, trade_id="NVDA-1", quantite=3, prix_execution_eur=D("160"), stop_eur=D("144"),
                objectif_eur=D("179.20"), raison="cassure au-dessus de la MM50")
    base.update(kw)
    return j.acheter(Achat(**base))


# ---------- journal ----------

def test_achat_vente_resultat(tmp_path):
    j = Journal(tmp_path / "journal.json", frais_par_ordre=D("1"))
    a = achat(j)
    j.vendre(a.id, Vente(quand=LUNDI + timedelta(days=2), quantite=3, prix_eur=D("170")))
    j2 = Journal(tmp_path / "journal.json", frais_par_ordre=D("1"))  # relu depuis le disque
    p = j2.position(a.id)
    assert p.fermee
    assert p.resultat_eur == D("28")  # 3 × 10 − 2 € de frais


def test_vente_partielle_puis_totale(tmp_path):
    j = Journal(tmp_path / "j.json", frais_par_ordre=D("1"))
    a = achat(j, quantite=4)
    j.vendre(a.id, Vente(quand=LUNDI + timedelta(days=1), quantite=2, prix_eur=D("180")))
    assert not j.position(a.id).fermee and j.position(a.id).quantite_restante == 2
    j.vendre(a.id, Vente(quand=LUNDI + timedelta(days=2), quantite=2, prix_eur=D("160")))
    assert j.position(a.id).resultat_eur == D("40") - 3  # 2×20 + 2×0 − 3 ordres


def test_vendre_plus_que_detenu_refuse(tmp_path):
    j = Journal(tmp_path / "j.json", frais_par_ordre=D("1"))
    a = achat(j)
    with pytest.raises(ValueError):
        j.vendre(a.id, Vente(quand=LUNDI, quantite=4, prix_eur=D("170")))


def test_quantite_entiere_et_stop_sous_achat():
    with pytest.raises(ValueError):
        Achat(quand=LUNDI, trade_id="NVDA-1", quantite=0, prix_execution_eur=D("1"), stop_eur=D("0.5"), raison="x")
    with pytest.raises(ValueError):
        Achat(quand=LUNDI, trade_id="NVDA-1", quantite=1, prix_execution_eur=D("10"), stop_eur=D("11"), raison="x")


def test_date_sans_fuseau_refusee():
    with pytest.raises(ValueError):
        Achat(quand=datetime(2026, 10, 5, 16), trade_id="NVDA-1", quantite=1, prix_execution_eur=D("10"),
              stop_eur=D("9"), raison="x")


def test_historique_des_stops(tmp_path):
    j = Journal(tmp_path / "j.json", frais_par_ordre=D("1"))
    a = achat(j)
    j.deplacer_stop(a.id, LUNDI + timedelta(hours=1), D("150"))
    j.deplacer_stop(a.id, LUNDI + timedelta(hours=2), D("140"))  # descendu : erreur à signaler
    p = j.position(a.id)
    assert p.stop_courant == D("140")
    assert p.stop_descendu


def test_perte_cumulee(tmp_path):
    j = Journal(tmp_path / "j.json", frais_par_ordre=D("1"))
    a = achat(j)
    j.vendre(a.id, Vente(quand=LUNDI + timedelta(days=1), quantite=3, prix_eur=D("144")))
    assert j.perte_cumulee() == D("50")  # 3 × 16 + 2


# ---------- tableau de risque ----------

def test_tableau_risque(tmp_path):
    j = Journal(tmp_path / "j.json", frais_par_ordre=D("1"))
    achat(j)  # 3 × 160 = 480 €, stop 144
    achat(j, trade_id="BTC-ETP-1", quantite=10, prix_execution_eur=D("20"), stop_eur=D("17"), objectif_eur=None)
    t = tableau_risque(j, PLAN, niveau=1)
    assert t.montant_investi_eur == D("680")
    # 3×16 + 1 frais de vente + 10×3 + 1 = 80
    assert t.perte_si_stops_eur == D("80")
    assert t.distance_seuil_eur == D("250")
    assert t.distance_seuil_pire_cas_eur == D("170")
    assert t.exposition.par_theme["semi-conducteurs"] == D("480")
    assert t.exposition.par_theme["crypto"] == D("200")
    assert "Perte si tous les stops sautent" in t.texte()


def test_stop_au_dessus_de_l_achat_reduit_le_risque(tmp_path):
    j = Journal(tmp_path / "j.json", frais_par_ordre=D("1"))
    a = achat(j)
    j.deplacer_stop(a.id, LUNDI + timedelta(days=3), D("165"))
    assert tableau_risque(j, PLAN, niveau=1).perte_si_stops_eur == D("-14")  # gain verrouillé 3×5 − 1


# ---------- bilan hebdomadaire ----------

def test_periode_bilan_vendredi_22h05():
    debut, fin = periode_bilan(datetime(2026, 10, 9, 22, 5, tzinfo=PARIS))
    assert fin == datetime(2026, 10, 9, 22, 5, tzinfo=PARIS)
    assert debut == datetime(2026, 10, 2, 22, 5, tzinfo=PARIS)


def test_bilan_trades_suivis_ignores_et_erreurs(tmp_path):
    j = Journal(tmp_path / "j.json", frais_par_ordre=D("1"))
    # fiche FEU VERT suivie, mais achetée au-dessus du prix limite et stop descendu ensuite
    f1 = j.noter_fiche(FicheJournal(quand=LUNDI - timedelta(minutes=5), trade_id="NVDA-1", verdict="FEU VERT",
                                    prix_limite_eur=D("159"), prix_stop_eur=D("143"), quantite=3))
    a = achat(j, fiche_id=f1.id)
    j.deplacer_stop(a.id, LUNDI + timedelta(hours=3), D("130"))
    # fiche FEU VERT ignorée
    j.noter_fiche(FicheJournal(quand=LUNDI + timedelta(days=1), trade_id="SEMI-ETF-1", verdict="FEU VERT",
                               prix_limite_eur=D("50"), prix_stop_eur=D("45"), quantite=5))
    # achat un jour interdit
    j.noter_fiche(FicheJournal(quand=LUNDI + timedelta(days=2), trade_id="BTC-ETP-1", verdict="INTERDIT"))
    achat(j, quand=LUNDI + timedelta(days=2, minutes=10), trade_id="BTC-ETP-1", quantite=10,
          prix_execution_eur=D("20"), stop_eur=D("17"), objectif_eur=None)
    b = bilan_hebdo(j, PLAN, datetime(2026, 10, 9, 22, 5, tzinfo=PARIS))
    assert b.suivis == 1 and b.ignores == 1
    assert b.erreurs["achat hors fourchette"] == 1
    assert b.erreurs["stop descendu"] == 1
    assert b.erreurs["achat un jour interdit"] == 1
    t = b.texte()
    assert f"0/{AJUSTEMENT_MIN_TRADES}" in t and "aucun ajustement" in t.lower()
    assert "pas un conseil financier" in t.lower()


def test_achat_sans_fiche_compte_comme_hors_plan(tmp_path):
    j = Journal(tmp_path / "j.json", frais_par_ordre=D("1"))
    achat(j)
    b = bilan_hebdo(j, PLAN, datetime(2026, 10, 9, 22, 5, tzinfo=PARIS))
    assert b.erreurs["achat sans fiche FEU VERT"] == 1


def test_seuil_30_trades():
    assert AJUSTEMENT_MIN_TRADES == 30


# ---------- rappels ----------

def test_rappels_heure_de_paris_avec_changement_d_heure():
    r = [Rappel(jours=(4,), heure="22:05", message="Bilan")]  # vendredi
    # 23 octobre 2026 (heure d'été) puis 30 octobre (heure d'hiver) : toujours 22:05 à Paris
    n = prochains_rappels(datetime(2026, 10, 20, 12, 0, tzinfo=PARIS), r, nombre=2)
    assert [x[0].strftime("%d %H:%M") for x in n] == ["23 22:05", "30 22:05"]
    assert n[0][0].utcoffset() == timedelta(hours=2) and n[1][0].utcoffset() == timedelta(hours=1)


def test_ntfy_desactive_sans_sujet():
    appels = []
    assert envoyer_ntfy(None, "x", transport=lambda *a: appels.append(a)) is False
    assert appels == []


def test_ntfy_envoie_le_message():
    appels = []
    assert envoyer_ntfy("mon-sujet-secret", "Bilan", transport=lambda url, data: appels.append((url, data)) or 200)
    assert appels == [("https://ntfy.sh/mon-sujet-secret", "Bilan".encode())]


def test_fiche_inconnue_refusee(tmp_path):
    j = Journal(tmp_path / "j.json", frais_par_ordre=D("1"))
    with pytest.raises(KeyError):
        achat(j, fiche_id="F99")
