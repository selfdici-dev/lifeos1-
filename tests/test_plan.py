from decimal import Decimal as D

from poste.plan import charger_plan


def test_plan_charge_avec_decimaux():
    p = charger_plan()
    assert p.capital_eur == D("2500")
    assert p.feu_vert.taux_us10a_max_pct == D("5.40")
    assert set(p.niveaux) == {"1", "2", "3"}
    assert {t.id for t in p.trades} == {"NVDA-1", "SEMI-ETF-1", "BTC-ETP-1", "NDX-TURBO-1"}


def test_turbo_a_une_plage_de_barriere():
    p = charger_plan()
    assert p.trade("NDX-TURBO-1").barriere_distance_pct == (D("25"), D("33"))
