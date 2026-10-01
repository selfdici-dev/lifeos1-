"""Phase 1 : exposition par thème et alerte au-delà de 60 % du capital."""
from decimal import Decimal as D

import pytest

from poste.exposition import Position, calculer_exposition


def test_exposition_par_theme():
    pos = [Position(instrument="NVDA", theme="semi-conducteurs", valeur_eur=D("600")),
           Position(instrument="ETP BTC", theme="crypto", valeur_eur=D("300"))]
    e = calculer_exposition(pos, D("2500"))
    assert e.par_theme == {"semi-conducteurs": D("600"), "crypto": D("300"), "nasdaq_turbo": D("0")}
    assert e.total_correle_eur == D("900")
    assert e.total_correle_pct == D("36.00")
    assert e.avertissement is None


def test_avertissement_au_dela_de_60_pct():
    pos = [Position(instrument="NVDA", theme="semi-conducteurs", valeur_eur=D("1500"))]
    assert calculer_exposition(pos, D("2500")).avertissement is None  # 60 % pile
    pos.append(Position(instrument="Turbo", theme="nasdaq_turbo", valeur_eur=D("1")))
    assert "60" in calculer_exposition(pos, D("2500")).avertissement


def test_ajout_projete():
    pos = [Position(instrument="NVDA", theme="semi-conducteurs", valeur_eur=D("1200"))]
    e = calculer_exposition(pos, D("2500"), ajout=("crypto", D("400")))
    assert e.par_theme["crypto"] == D("400")
    assert e.avertissement is not None


def test_theme_inconnu_refuse():
    # Micron (164 €) est hors plan : il n'a pas de thème valide et n'entre pas dans le calcul
    with pytest.raises(ValueError):
        Position(instrument="Micron", theme="autre", valeur_eur=D("164"))


def test_valeur_negative_refusee():
    with pytest.raises(ValueError):
        Position(instrument="NVDA", theme="semi-conducteurs", valeur_eur=D("-1"))


def test_texte_affiche_tous_les_themes():
    t = calculer_exposition([], D("2500")).texte()
    for th in ("semi-conducteurs", "crypto", "nasdaq_turbo"):
        assert th in t


from poste.exposition import charger_positions


def test_charger_positions_absent(tmp_path):
    assert charger_positions(tmp_path / "absent.json") == []


def test_charger_positions(tmp_path):
    f = tmp_path / "positions.json"
    f.write_text('[{"instrument": "NVDA", "theme": "crypto", "valeur_eur": "12.5"}]', encoding="utf-8")
    assert charger_positions(f)[0].valeur_eur == D("12.5")
