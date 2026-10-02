"""Menu simple, couleurs de la console Windows, fichiers à double-cliquer."""
from pathlib import Path

from poste.console import preparer_console, sans_couleurs
from poste.donnees.modeles import badge
from poste.menu import AIDE, menu

RACINE = Path(__file__).resolve().parent.parent


def _lancer(choix, actions):
    """Fait tourner le menu avec des réponses toutes prêtes ; renvoie tout ce qui a été affiché."""
    reponses = iter(choix)
    affiche = []
    menu(actions=actions, entree=lambda _="": next(reponses), sortie=affiche.append)
    return "\n".join(str(a) for a in affiche)


def test_menu_lance_la_bonne_action_puis_quitte():
    appels = []
    actions = [("1", "Préparer un achat", lambda: appels.append("fiche")),
               ("2", "Mon risque", lambda: appels.append("risque"))]
    texte = _lancer(["2", "", "1", "", "0"], actions)
    assert appels == ["risque", "fiche"]
    assert "Préparer un achat" in texte and "Quitter" in texte


def test_menu_choix_inconnu():
    texte = _lancer(["7", "0"], [("1", "Préparer un achat", lambda: None)])
    assert "Choix inconnu" in texte


def test_une_erreur_ne_ferme_pas_le_menu():
    def plante():
        raise ValueError("prix illisible")
    appels = []
    actions = [("1", "Préparer un achat", plante), ("2", "Mon risque", lambda: appels.append("ok"))]
    texte = _lancer(["1", "", "2", "", "0"], actions)
    assert "prix illisible" in texte and "Rien n'a été envoyé" in texte
    assert appels == ["ok"]


def test_menu_rappelle_qu_aucun_ordre_n_est_passe():
    texte = _lancer(["0"], [])
    assert "aucun ordre" in texte.lower()
    assert "pas un conseil financier" in texte.lower()


def test_aide_disponible():
    texte = _lancer(["?", "", "0"], [])
    assert AIDE.splitlines()[0] in texte


def test_menu_par_defaut_ne_propose_pas_d_ordres_reels():
    from poste.menu import actions_par_defaut
    libelles = " ".join(l.lower() for _, l, _ in actions_par_defaut())
    assert "ibkr" not in libelles and "auto" not in libelles.split()


# ---------- couleurs ----------

def test_sans_couleurs():
    assert sans_couleurs("\x1b[31mPÉRIMÉ\x1b[0m cours") == "PÉRIMÉ cours"


def test_badge_sans_couleurs_si_console_incompatible(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    b = badge("cours", None, __import__("datetime").datetime.now(__import__("zoneinfo").ZoneInfo("Europe/Paris")))
    assert "\x1b[" not in b and "PÉRIMÉ" in b


def test_preparer_console_ne_plante_pas():
    assert preparer_console() in (True, False)


# ---------- fichiers à double-cliquer (Windows) ----------

def test_fichiers_bat():
    for nom, contenu in (("INSTALLER.bat", "requirements.txt"), ("LANCER.bat", "-m poste"),
                         ("METTRE_A_JOUR.bat", "git pull")):
        f = RACINE / nom
        assert f.exists(), nom
        brut = f.read_bytes()
        assert b"\r\n" in brut, f"{nom} doit avoir des fins de ligne Windows"
        assert contenu in brut.decode("ascii"), nom  # ASCII pur : pas d'accents mal affichés


def test_mode_d_emploi():
    texte = (RACINE / "MODE_D_EMPLOI.md").read_text(encoding="utf-8")
    for mot in ("LANCER.bat", "INSTALLER.bat", "FEU VERT", "ATTENDRE", "INTERDIT", "Trade Republic",
                "pas un conseil financier"):
        assert mot in texte
