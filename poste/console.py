"""Console : couleurs ANSI. La console Windows classique affiche « ←[31m » au lieu des couleurs
tant qu'on ne les active pas ; si l'activation échoue, on retire simplement les couleurs."""
import os
import re

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def sans_couleurs(texte: str) -> str:
    return _ANSI.sub("", texte)


def couleur(texte: str) -> str:
    """Le texte tel quel, ou sans ses codes couleur si la console ne les comprend pas."""
    return sans_couleurs(texte) if os.environ.get("NO_COLOR") else texte


def preparer_console() -> bool:
    """Active les couleurs dans la console Windows. Renvoie False si elles restent indisponibles."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        noyau = ctypes.windll.kernel32
        sortie = noyau.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if noyau.GetConsoleMode(sortie, ctypes.byref(mode)) and noyau.SetConsoleMode(sortie, mode.value | 0x0004):
            return True
    except Exception:  # noqa: BLE001 - au pire, on affiche sans couleurs
        pass
    os.environ["NO_COLOR"] = "1"
    return False
