"""Phase 2 : le diagnostic dit ce qui marche, sans jamais afficher une clé."""
import json

from poste.diagnostic import diagnostiquer
from poste.donnees.fabrique import creer_marche
from poste.donnees.fournisseurs import Reponse
from tests.test_donnees import CLES, MAINTENANT, FauxReseau, Horloge, rep_finnhub, ts


def test_diagnostic_sans_cle(tmp_path):
    m = creer_marche(env={}, transport=FauxReseau({}), horloge=Horloge(), dossier_cache=tmp_path, yfinance_module=None)
    lignes = "\n".join(diagnostiquer(m))
    for nom in ("Finnhub", "Twelve Data", "Alpha Vantage", "FRED", "yfinance"):
        assert nom in lignes
    assert lignes.count("clé absente") == 4


def test_diagnostic_ok_et_ko_sans_fuite(tmp_path, capsys):
    reseau = FauxReseau({
        "finnhub": rep_finnhub(),
        "twelvedata": Reponse(401, "apikey=cle-td-SECRETE invalide"),
        "stlouisfed": Reponse(200, json.dumps({"observations": [{"date": "2026-09-30", "value": "4.1"}]})),
        "alphavantage": Reponse(200, "symbol,name,reportDate\nNVDA,NVIDIA,2026-11-18\n"),
    })
    m = creer_marche(env=CLES, transport=reseau, horloge=Horloge(), dossier_cache=tmp_path, yfinance_module=None)
    lignes = diagnostiquer(m)
    texte = "\n".join(lignes)
    assert "OK" in next(l for l in lignes if "Finnhub" in l)
    assert "401" in next(l for l in lignes if "Twelve Data" in l)
    assert "restantes aujourd'hui : 24" in texte
    for cle in CLES.values():
        assert cle not in texte
    assert (tmp_path / "compteurs.json").exists()
