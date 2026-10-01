# Poste de trading personnel

Aide à la décision, pas un conseil financier.

L'application ne passe aucun ordre : tu saisis tout à la main dans Trade Republic.
Tout ce qui concerne l'appli Trade Republic (boutons, types d'ordres, frais, horaires) est
marqué « à vérifier dans ton appli ». Tous les seuils de `plan.json` sont des points de
départ **non testés**.

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Utilisation (phase 0 : la fiche d'ordre)

```bash
.venv/bin/python -m poste
```

L'assistant te demande les prix lus dans Trade Republic et TradingView, puis affiche la fiche :
verdict (FEU VERT / ATTENDRE / INTERDIT), quantité entière, prix limite, stop, objectifs,
perte maximale en euros, étapes dans l'appli, « si ça tourne mal » et « si ça marche ».

## Réglages et fichiers personnels (non versionnés)

- `python -m poste niveau 2` : change le niveau d'agressivité (enregistré dans `reglages.json`).
- `python -m poste expo` : exposition par thème (semi-conducteurs, crypto, Nasdaq via turbos),
  avec une alerte au-delà de 60 % du capital. Les lignes hors plan (Micron) ne comptent pas.
- `positions.json` : tes positions, à saisir à la main (voir `positions.exemple.json`).
- `calendrier.json` : annonces à impact fort, avec fuseau horaire (voir `calendrier.exemple.json`).
  S'il est absent, l'assistant te pose la question.

## Règles bloquantes codées en dur (`poste/regles.py`)

- Pas d'achat dans les 24 h avant une annonce à impact fort.
- Test de feu vert avant chaque tranche : taux US 10 ans ≤ 5,40 % et S&P 500 pas en baisse de plus de 1,5 %.
- Arrêt des achats quand la perte cumulée atteint le seuil du niveau choisi.

`plan.json` refuse toute clé inconnue : ces règles ne peuvent pas être assouplies depuis le plan.

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Avancement

- [x] Phase 0 : fiche d'ordre
- [x] Phase 1 : plan en données, règles bloquantes, exposition par thème
- [ ] Phase 2 : données en direct
- [ ] Phase 3 : backtest honnête
- [ ] Phase 4 : journal, risque, bilan
- [ ] Phase 5 : revue critique
- [ ] Phase 6 : exécution automatisée (désactivée par défaut)
