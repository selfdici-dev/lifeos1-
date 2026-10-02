from decimal import Decimal as D

from poste.plan import charger_plan


def test_plan_charge_avec_decimaux():
    p = charger_plan()
    assert p.capital_eur == D("2500")
    assert not hasattr(p, "feu_vert")  # le feu vert est codé en dur (poste/regles.py)
    assert set(p.niveaux) == {"1", "2", "3"}
    assert {t.id for t in p.trades} == {"NVDA-1", "SEMI-ETF-1", "BTC-ETP-1", "NDX-TURBO-1"}


def test_turbo_a_une_plage_de_barriere():
    p = charger_plan()
    assert p.trade("NDX-TURBO-1").barriere_distance_pct == (D("25"), D("33"))


import json

import pytest

from poste.plan import CHEMIN_PLAN


def _plan_modifie(tmp_path, modif):
    d = json.loads(CHEMIN_PLAN.read_text(encoding="utf-8"))
    modif(d)
    f = tmp_path / "plan.json"
    f.write_text(json.dumps(d), encoding="utf-8")
    return f


def test_plan_refuse_cle_inconnue(tmp_path):
    # impossible de réintroduire un seuil de feu vert assoupli dans le plan
    f = _plan_modifie(tmp_path, lambda d: d.update(feu_vert={"taux_us10a_max_pct": "9"}))
    with pytest.raises(ValueError):
        charger_plan(f)


def test_plan_exige_les_trois_niveaux(tmp_path):
    f = _plan_modifie(tmp_path, lambda d: d["niveaux"].pop("3"))
    with pytest.raises(ValueError):
        charger_plan(f)


def test_niveaux_de_plus_en_plus_agressifs(tmp_path):
    def inverse(d):
        d["niveaux"]["2"]["risque_max_par_trade_eur"] = "20"
    with pytest.raises(ValueError):
        charger_plan(_plan_modifie(tmp_path, inverse))


def test_objectifs_decroissants_refuses(tmp_path):
    def m(d):
        d["trades"][0]["objectifs_pct"] = ["25", "12"]
    with pytest.raises(ValueError):
        charger_plan(_plan_modifie(tmp_path, m))


def test_identifiants_uniques(tmp_path):
    def m(d):
        d["trades"][1]["id"] = d["trades"][0]["id"]
    with pytest.raises(ValueError):
        charger_plan(_plan_modifie(tmp_path, m))
