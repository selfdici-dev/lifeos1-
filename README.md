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

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Avancement

- [x] Phase 0 : fiche d'ordre
- [ ] Phase 1 : plan en données, règles bloquantes, exposition par thème
- [ ] Phase 2 : données en direct
- [ ] Phase 3 : backtest honnête
- [ ] Phase 4 : journal, risque, bilan
- [ ] Phase 5 : revue critique
- [ ] Phase 6 : exécution automatisée (désactivée par défaut)
