"""Menu simple : tout l'outil avec des numéros, sans connaître aucune commande."""
import os
from typing import Callable, Optional

ENTETE = ("=== POSTE DE TRADING ===\n"
          "Aide à la décision, pas un conseil financier. Cet outil ne passe aucun ordre :\n"
          "il te dit quoi faire dans Trade Republic, et c'est toi qui tapes l'ordre dans l'appli.")

AIDE = """Comment ça marche, en 6 étapes :
1. Avant d'acheter, choisis 1 (ou 2 si tes clés marchent). L'outil te pose des questions :
   tu tapes les prix que tu lis dans Trade Republic et sur TradingView.
2. Il répond FEU VERT (tu peux y aller), ATTENDRE (pas maintenant, il dit pourquoi)
   ou INTERDIT (pas aujourd'hui). Avec FEU VERT, il donne les étapes à suivre dans l'appli,
   la quantité, le prix limite, le stop, et combien tu peux perdre au maximum.
3. Tu passes l'ordre toi-même dans Trade Republic, puis tu poses le stop.
4. Tout de suite après, choisis 3 pour noter ton achat (avec le numéro de la fiche, ex. F1).
5. Si tu montes ton stop ou si tu vends, choisis 4 ou 5 pour le noter.
6. Le vendredi soir, choisis 8 : le bilan te montre tes erreurs de la semaine.
Règle d'or : ne descends jamais ton stop, n'achète jamais plus que la quantité de la fiche."""

Action = tuple[str, str, Callable[[], None]]


def _diagnostic() -> None:
    from poste.diagnostic import main
    main()


def _ouvrir(chemin) -> None:
    if os.name == "nt":
        try:
            os.startfile(chemin)  # ouvre le rapport dans le Bloc-notes
        except OSError:
            pass


def _analyse_historique() -> None:
    from poste.backtest.donnees import telecharger
    from poste.backtest.rapport import DOSSIER, INSTRUMENTS, generer_rapport
    print("Téléchargement de l'historique (2015 à aujourd'hui)…")
    for inst in INSTRUMENTS:
        try:
            print(f"  ✓ {inst.nom} : {telecharger(inst.symbole, DOSSIER / f'{inst.fichier}.csv')} séances")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {inst.nom} : échec ({type(e).__name__}), on garde l'historique déjà présent s'il existe")
    print("Calculs en cours (1 à 2 minutes)…")
    texte = generer_rapport()
    sortie = DOSSIER.parent / "rapport_backtest.md"
    sortie.write_text(texte, encoding="utf-8")
    debut = texte.rfind("\n# Verdict")
    print(texte[debut:] if debut >= 0 else texte)
    print(f"\nRapport complet : {sortie}")
    _ouvrir(sortie)


def _changer_niveau(cli) -> None:
    from poste.plan import charger_plan
    plan = charger_plan()
    for k, n in sorted(plan.niveaux.items()):
        print(f"  {k}. {n.nom} : perte max {n.risque_max_par_trade_eur} € par trade, au plus"
              f" {n.montant_max_par_trade_eur} € par achat, arrêt des achats après {n.seuil_arret_perte_cumulee_eur} €"
              " de baisse")
    cli.cmd_niveau(input("Niveau choisi (1, 2 ou 3) : ").strip())


def actions_par_defaut() -> list[Action]:
    from poste import __main__ as cli
    return [
        ("1", "Préparer un achat (je tape les prix moi-même)", cli.cmd_fiche),
        ("2", "Préparer un achat avec les prix récupérés tout seuls (il faut tes clés)", cli.cmd_auto),
        ("3", "J'ai acheté : je le note dans mon journal", lambda: cli.cmd_journal(["achat"])),
        ("4", "J'ai déplacé mon stop : je le note", lambda: cli.cmd_journal(["stop"])),
        ("5", "J'ai vendu : je le note", lambda: cli.cmd_journal(["vente"])),
        ("6", "Voir mes positions", lambda: cli.cmd_journal([])),
        ("7", "Voir mon risque en ce moment", cli.cmd_risque),
        ("8", "Voir mon bilan de la semaine", cli.cmd_bilan),
        ("9", "Vérifier que mes clés marchent", _diagnostic),
        ("10", "Analyse historique des règles (1 à 2 minutes)", _analyse_historique),
        ("11", "Changer mon niveau d'agressivité", lambda: _changer_niveau(cli)),
    ]


def menu(actions: Optional[list[Action]] = None, entree=input, sortie=print) -> None:
    actions = actions_par_defaut() if actions is None else actions
    try:
        while True:
            sortie("")
            sortie(ENTETE)
            sortie("")
            for num, libelle, _ in actions:
                sortie(f"  {num:>2}. {libelle}")
            sortie("   ?. Comment ça marche ?")
            sortie("   0. Quitter")
            choix = entree("\nTon choix (tape le numéro puis Entrée) : ").strip()
            if choix == "0":
                sortie("À bientôt.")
                return
            if choix == "?":
                sortie(AIDE)
                entree("\nAppuie sur Entrée pour revenir au menu.")
                continue
            action = next((a for n, _, a in actions if n == choix), None)
            if action is None:
                sortie("Choix inconnu : tape un des numéros de la liste.")
                continue
            try:
                action()
            except KeyboardInterrupt:
                sortie("\nAnnulé.")
            except Exception as e:  # noqa: BLE001 - le menu ne doit jamais se fermer sur une erreur
                sortie(f"\nOups : {e} ({type(e).__name__}). Rien n'a été envoyé nulle part. Retour au menu.")
            entree("\nAppuie sur Entrée pour revenir au menu.")
    except (KeyboardInterrupt, EOFError):
        sortie("\nÀ bientôt.")
