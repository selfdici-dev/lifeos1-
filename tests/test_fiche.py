"""Phase 0 : tests de la fiche d'ordre (écrits avant le code)."""
from decimal import Decimal as D

import pytest
from hypothesis import given, settings, strategies as st

from poste.fiche import Saisie, Verdict, build_order_sheet
from poste.plan import charger_plan

PLAN = charger_plan()
RAPPEL = "aide à la décision, pas un conseil financier"


def saisie_ok(**surcharges):
    """Saisie cohérente pour NVDA : 180 $ / 1,10 = 163,64 € ; vendeur à 163,70 €."""
    base = dict(
        prix_vendeur_eur=D("163.70"),
        cours_ref=D("180"),
        mm50_ref=D("170"),
        eurusd=D("1.10"),
        taux_us10a_pct=D("4.20"),
        sp500_variation_seance_pct=D("-0.3"),
        evenement_majeur_24h=False,
        perte_cumulee_eur=D("0"),
    )
    base.update(surcharges)
    return Saisie(**base)


# ---------- cas concrets ----------

def test_feu_vert_calculs_nvda_niveau_1():
    f = build_order_sheet("NVDA-1", saisie_ok(), 1, plan=PLAN)
    assert f.verdict is Verdict.FEU_VERT
    # limite = 163,70 × 1,002 = 164,0274 -> arrondi au centime supérieur
    assert f.prix_limite_eur == D("164.03")
    # stop = 164,03 × 0,90 = 147,627 -> arrondi au centime inférieur
    assert f.prix_stop_eur == D("147.62")
    # risque par titre 16,41 ; (50 - 2 frais) / 16,41 = 2,9 -> 2 ; montant (625-1)/164,03 = 3,8 -> 3
    assert f.quantite == 2
    assert isinstance(f.quantite, int)
    assert f.perte_max_eur == D("34.82")  # 2 × 16,41 + 2 € de frais
    assert f.objectifs_eur == [D("183.71"), D("205.04")]
    assert f.ratio_gain_risque is not None and f.ratio_gain_risque > 0
    assert len(f.etapes) >= 4
    assert any("164.03" in e for e in f.etapes)
    assert any("147.62" in e for e in f.etapes)


def test_texte_contient_perte_max_et_rappel():
    f = build_order_sheet("NVDA-1", saisie_ok(), 1, plan=PLAN)
    t = f.texte().lower()
    assert RAPPEL in t
    assert "perte maximale" in t
    assert "à vérifier dans ton appli" in t
    assert "si ça tourne mal" in t and "si ça marche" in t


def test_conversion_dollars_euros():
    f = build_order_sheet("NVDA-1", saisie_ok(), 1, plan=PLAN)
    assert f.conversion["cours_ref_eur"] == D("163.64")
    assert f.conversion["mm50_ref_eur"] == D("154.55")
    assert f.conversion["eurusd"] == D("1.10")


def test_interdit_si_annonce_majeure():
    f = build_order_sheet("NVDA-1", saisie_ok(evenement_majeur_24h=True), 1, plan=PLAN)
    assert f.verdict is Verdict.INTERDIT
    assert any("annonce" in r.lower() for r in f.raisons)


def test_interdit_si_taux_trop_haut():
    f = build_order_sheet("NVDA-1", saisie_ok(taux_us10a_pct=D("5.41")), 1, plan=PLAN)
    assert f.verdict is Verdict.INTERDIT


def test_taux_pile_au_seuil_autorise():
    f = build_order_sheet("NVDA-1", saisie_ok(taux_us10a_pct=D("5.40")), 1, plan=PLAN)
    assert f.verdict is Verdict.FEU_VERT


def test_interdit_si_sp500_baisse_plus_de_1_5():
    f = build_order_sheet("NVDA-1", saisie_ok(sp500_variation_seance_pct=D("-1.6")), 1, plan=PLAN)
    assert f.verdict is Verdict.INTERDIT
    f2 = build_order_sheet("NVDA-1", saisie_ok(sp500_variation_seance_pct=D("-1.5")), 1, plan=PLAN)
    assert f2.verdict is Verdict.FEU_VERT


def test_interdit_si_sous_mm50():
    f = build_order_sheet("NVDA-1", saisie_ok(mm50_ref=D("185")), 1, plan=PLAN)
    assert f.verdict is Verdict.INTERDIT
    assert any("moyenne mobile" in r.lower() for r in f.raisons)


def test_interdit_si_seuil_perte_cumulee_atteint():
    f = build_order_sheet("NVDA-1", saisie_ok(perte_cumulee_eur=D("250")), 1, plan=PLAN)
    assert f.verdict is Verdict.INTERDIT
    f3 = build_order_sheet("NVDA-1", saisie_ok(perte_cumulee_eur=D("250")), 3, plan=PLAN)
    assert f3.verdict is Verdict.FEU_VERT  # seuil 500 € au niveau 3


def test_attendre_si_ecart_prix_suspect():
    # vendeur à 200 € alors que 180 $ / 1,10 = 163,64 € : faute de frappe ou mauvais instrument
    f = build_order_sheet("NVDA-1", saisie_ok(prix_vendeur_eur=D("200")), 1, plan=PLAN)
    assert f.verdict is Verdict.ATTENDRE
    assert f.etapes == []


def test_usd_sans_eurusd_refuse():
    with pytest.raises(ValueError):
        build_order_sheet("NVDA-1", saisie_ok(eurusd=None), 1, plan=PLAN)


def test_prix_negatif_refuse():
    with pytest.raises(ValueError):
        saisie_ok(prix_vendeur_eur=D("-1"))


def test_trade_inconnu_refuse():
    with pytest.raises(KeyError):
        build_order_sheet("XXX", saisie_ok(), 1, plan=PLAN)


def test_quantite_nulle_interdit():
    # au niveau 1, risque 50 € : un titre à 1 000 € avec stop à -10 % risque 100 € -> 0 titre
    s = saisie_ok(prix_vendeur_eur=D("1000"), cours_ref=D("1100"), mm50_ref=D("1000"))
    f = build_order_sheet("NVDA-1", s, 1, plan=PLAN)
    assert f.verdict is Verdict.INTERDIT
    assert f.quantite is None


def test_turbo_perte_max_est_la_mise_entiere():
    s = saisie_ok(prix_vendeur_eur=D("5.00"), cours_ref=D("20000"), mm50_ref=D("19000"),
                  barriere_ref=D("14000"))  # barrière à 30 % sous le cours
    f = build_order_sheet("NDX-TURBO-1", s, 2, plan=PLAN)
    assert f.verdict is Verdict.FEU_VERT
    assert f.perte_max_eur == f.quantite * f.prix_limite_eur + 2 * PLAN.frais_par_ordre_eur
    assert f.perte_max_eur <= PLAN.niveaux["2"].risque_max_par_trade_eur


def test_turbo_barriere_hors_plage_attendre():
    s = saisie_ok(prix_vendeur_eur=D("5.00"), cours_ref=D("20000"), mm50_ref=D("19000"),
                  barriere_ref=D("18000"))  # barrière à 10 % : trop proche
    f = build_order_sheet("NDX-TURBO-1", s, 2, plan=PLAN)
    assert f.verdict is Verdict.ATTENDRE


def test_turbo_sans_barriere_refuse():
    s = saisie_ok(prix_vendeur_eur=D("5.00"), cours_ref=D("20000"), mm50_ref=D("19000"))
    with pytest.raises(ValueError):
        build_order_sheet("NDX-TURBO-1", s, 2, plan=PLAN)


def test_fourchette_au_dessus_attendre():
    plan = PLAN.model_copy(deep=True)
    t = next(t for t in plan.trades if t.id == "NVDA-1")
    t.fourchette_entree_ref = (D("160"), D("175"))
    f = build_order_sheet("NVDA-1", saisie_ok(), 1, plan=plan)
    assert f.verdict is Verdict.ATTENDRE
    assert any("fourchette" in r.lower() for r in f.raisons)


def test_ratio_trop_faible_attendre():
    plan = PLAN.model_copy(deep=True)
    plan.ratio_min_gain_risque = D("10")
    f = build_order_sheet("NVDA-1", saisie_ok(), 1, plan=plan)
    assert f.verdict is Verdict.ATTENDRE


def test_niveau_inconnu_refuse():
    with pytest.raises(KeyError):
        build_order_sheet("NVDA-1", saisie_ok(), 7, plan=PLAN)


# ---------- propriétés (hypothesis) ----------

prix = st.decimals(min_value=D("0.10"), max_value=D("3000"), places=2)
ids = st.sampled_from([t.id for t in PLAN.trades])
niveaux = st.sampled_from([1, 2, 3])


@st.composite
def saisies(draw):
    trade_id = draw(ids)
    trade = PLAN.trade(trade_id)
    p = draw(prix)
    eurusd = draw(st.decimals(min_value=D("0.90"), max_value=D("1.40"), places=4))
    if trade.meme_cours_que_ref:
        bruit = draw(st.decimals(min_value=D("-0.05"), max_value=D("0.05"), places=3))
        cours = p * (eurusd if trade.devise_ref == "USD" else 1) * (1 + bruit)
    else:
        cours = draw(st.decimals(min_value=D("1"), max_value=D("100000"), places=2))
    cours = max(cours.quantize(D("0.01")), D("0.01"))
    mm50 = max((cours * draw(st.decimals(min_value=D("0.8"), max_value=D("1.2"), places=3))).quantize(D("0.01")), D("0.01"))
    barriere = None
    if trade.type == "turbo_long":
        barriere = (cours * draw(st.decimals(min_value=D("0.5"), max_value=D("0.95"), places=3))).quantize(D("0.01"))
    s = Saisie(
        prix_vendeur_eur=p, cours_ref=cours, mm50_ref=mm50, eurusd=eurusd,
        taux_us10a_pct=draw(st.decimals(min_value=D("2"), max_value=D("7"), places=2)),
        sp500_variation_seance_pct=draw(st.decimals(min_value=D("-5"), max_value=D("5"), places=2)),
        evenement_majeur_24h=draw(st.booleans()),
        perte_cumulee_eur=draw(st.decimals(min_value=D("0"), max_value=D("600"), places=2)),
        barriere_ref=barriere,
    )
    return trade_id, s


@settings(max_examples=400, deadline=None)
@given(saisies(), niveaux)
def test_proprietes_fiche(ts, niveau):
    trade_id, s = ts
    f = build_order_sheet(trade_id, s, niveau, plan=PLAN)
    n = PLAN.niveaux[str(niveau)]
    frais = PLAN.frais_par_ordre_eur

    # le rappel est toujours là
    assert RAPPEL in f.texte().lower()

    if f.verdict is Verdict.INTERDIT:
        # aucune fiche d'ordre émise
        assert f.quantite is None
        assert f.etapes == []
        return

    if f.verdict is Verdict.ATTENDRE:
        assert f.etapes == []

    if f.quantite is not None:
        assert isinstance(f.quantite, int) and f.quantite >= 1
        # stop toujours sous le prix d'achat
        assert D("0") < f.prix_stop_eur < f.prix_limite_eur
        # perte max jamais au-dessus du budget du trade
        assert f.perte_max_eur <= n.risque_max_par_trade_eur
        # quantité × prix (+ frais d'achat) jamais au-dessus du montant prévu
        assert f.quantite * f.prix_limite_eur + frais <= n.montant_max_par_trade_eur
        # prix limite >= prix vendeur
        assert f.prix_limite_eur >= s.prix_vendeur_eur
        # perte max affichée dans le texte
        assert f"{f.perte_max_eur}" in f.texte()


@settings(max_examples=200, deadline=None)
@given(saisies(), niveaux)
def test_aucune_fiche_jour_interdit(ts, niveau):
    trade_id, s = ts
    s = s.model_copy(update={"evenement_majeur_24h": True})
    f = build_order_sheet(trade_id, s, niveau, plan=PLAN)
    assert f.verdict is Verdict.INTERDIT
    assert f.quantite is None and f.etapes == []
