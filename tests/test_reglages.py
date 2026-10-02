"""Phase 1 : le niveau d'agressivité se change dans un réglage."""
import pytest

from poste.reglages import Reglages, charger_reglages, enregistrer_reglages


def test_defaut_niveau_1_si_absent(tmp_path):
    assert charger_reglages(tmp_path / "absent.json").niveau == 1


def test_changer_niveau(tmp_path):
    f = tmp_path / "reglages.json"
    enregistrer_reglages(Reglages(niveau=3), f)
    assert charger_reglages(f).niveau == 3


def test_niveau_invalide(tmp_path):
    with pytest.raises(ValueError):
        Reglages(niveau=4)
    f = tmp_path / "reglages.json"
    f.write_text('{"niveau": 9}')
    with pytest.raises(ValueError):
        charger_reglages(f)
