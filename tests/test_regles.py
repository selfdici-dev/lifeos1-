"""Phase 1 : règles bloquantes codées en dur."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from poste import regles
from poste.regles import Evenement, evenements_bloquants, raisons_feu_vert

PARIS = ZoneInfo("Europe/Paris")


def test_constantes():
    assert regles.TAUX_US10A_MAX_PCT == D("5.40")
    assert regles.SP500_BAISSE_MAX_PCT == D("1.5")
    assert regles.FENETRE_EVENEMENT == timedelta(hours=24)
    assert regles.SEUIL_CORRELE_PCT == D("60")


@pytest.mark.parametrize("taux,sp,ok", [
    (D("5.40"), D("-1.5"), True),
    (D("5.41"), D("0"), False),
    (D("4"), D("-1.51"), False),
    (D("4"), D("2"), True),
])
def test_feu_vert(taux, sp, ok):
    assert (raisons_feu_vert(taux, sp) == []) is ok


def ev(dt, impact="fort"):
    return Evenement(nom="Inflation US", debut=dt, impact=impact)


def test_evenement_dans_24h_bloque():
    now = datetime(2026, 10, 6, 10, 0, tzinfo=PARIS)
    assert evenements_bloquants(now, [ev(now + timedelta(hours=23))])
    assert evenements_bloquants(now, [ev(now + timedelta(hours=24))])
    assert not evenements_bloquants(now, [ev(now + timedelta(hours=24, minutes=1))])
    assert not evenements_bloquants(now, [ev(now - timedelta(minutes=1))])


def test_impact_moyen_ne_bloque_pas():
    now = datetime(2026, 10, 6, 10, 0, tzinfo=PARIS)
    assert not evenements_bloquants(now, [ev(now + timedelta(hours=2), impact="moyen")])


def test_date_sans_fuseau_refusee():
    with pytest.raises(ValueError):
        ev(datetime(2026, 10, 6, 10, 0))
    with pytest.raises(ValueError):
        evenements_bloquants(datetime(2026, 10, 6, 10, 0), [])


def test_passage_heure_hiver_europe():
    # nuit du 24 au 25 octobre 2026 : 3 h -> 2 h à Paris, la journée dure 25 h
    now = datetime(2026, 10, 24, 14, 30, tzinfo=PARIS)
    evt = ev(datetime(2026, 10, 25, 14, 30, tzinfo=PARIS))  # même heure murale, mais 25 h plus tard
    assert not evenements_bloquants(now, [evt])


def test_evenement_us_en_heure_new_york():
    # 14:30 Paris le 29 octobre 2026 = 9:30 New York (décalage de 5 h entre les deux passages d'heure)
    ny = ZoneInfo("America/New_York")
    now = datetime(2026, 10, 28, 14, 31, tzinfo=PARIS)
    evt = ev(datetime(2026, 10, 29, 8, 30, tzinfo=ny))  # 13:30 Paris
    assert evenements_bloquants(now, [evt])


from poste.regles import charger_calendrier


def test_charger_calendrier(tmp_path):
    f = tmp_path / "calendrier.json"
    f.write_text('[{"nom": "Fed", "debut": "2026-10-28T19:00:00+01:00", "impact": "fort"}]', encoding="utf-8")
    cal = charger_calendrier(f)
    assert cal[0].debut.utcoffset() == timedelta(hours=1)


def test_calendrier_absent_retourne_none(tmp_path):
    # None = « je ne sais pas » : l'assistant doit alors te poser la question
    assert charger_calendrier(tmp_path / "absent.json") is None
