"""python -m poste.backtest telecharger   (sur ton ordinateur, via yfinance)
python -m poste.backtest rapport       (écrit rapport_backtest.md)"""
import sys

from poste.backtest.donnees import telecharger
from poste.backtest.rapport import DOSSIER, INSTRUMENTS, generer_rapport


def main(argv):
    if argv[:1] == ["telecharger"]:
        for inst in INSTRUMENTS:
            try:
                n = telecharger(inst.symbole, DOSSIER / f"{inst.fichier}.csv")
                print(f"✓ {inst.nom} ({inst.symbole}) : {n} séances")
            except Exception as e:  # noqa: BLE001
                print(f"✗ {inst.nom} ({inst.symbole}) : échec ({type(e).__name__})")
    elif argv[:1] == ["rapport"]:
        texte = generer_rapport()
        sortie = DOSSIER.parent / "rapport_backtest.md"
        sortie.write_text(texte, encoding="utf-8")
        print(texte)
        print(f"\n(rapport écrit dans {sortie.name})")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
