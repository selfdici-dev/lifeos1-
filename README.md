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

## Données en direct (phase 2)

1. Copie `.env.exemple` en `.env` et colle tes clés gratuites (Finnhub, Twelve Data, Alpha Vantage, FRED).
2. `python -m poste.diagnostic` : un appel par source, te dit ce qui marche vraiment (aucune clé affichée).
3. `python -m poste auto` : la fiche avec cours, moyenne 50 jours, EUR/USD, taux US 10 ans et
   variation du S&P 500 récupérés automatiquement. Tu ne tapes que le prix vendeur de Trade Republic.

| Donnée | Sources, dans l'ordre |
|---|---|
| Cours action US | Finnhub, Twelve Data, yfinance |
| Moyenne 50 jours | Twelve Data, yfinance (clôtures **avant** aujourd'hui uniquement) |
| Bitcoin, Nasdaq-100, Europe | Twelve Data (Bitcoin), yfinance (différé) |
| EUR/USD | Twelve Data, yfinance |
| Taux US 10 ans | FRED (série DGS10 : valeur de la veille) |
| Variation S&P 500 | Finnhub (SPY), Twelve Data (SPY), yfinance (^GSPC) |
| Dates de résultats | Alpha Vantage (25 requêtes/jour, compteur dans `.cache/`, cache 24 h) |

Badge de fraîcheur : VERT / ORANGE / PÉRIMÉ (rouge), avec la source et l'heure de Paris.
Cours : vert ≤ 5 min, orange ≤ 30 min. Données quotidiennes : vert ≤ 4 jours, orange ≤ 6 jours.
Si une donnée obligatoire est périmée, **aucune fiche n'est générée**. Hors séance US, c'est normal.
Un fournisseur qui renvoie 3 erreurs 429/403 de suite est coupé 30 minutes (disjoncteur).
Les prix sont indicatifs : le prix d'exécution se lit dans Trade Republic.

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
- [x] Phase 2 : données en direct
- [ ] Phase 3 : backtest honnête
- [ ] Phase 4 : journal, risque, bilan
- [ ] Phase 5 : revue critique
- [ ] Phase 6 : exécution automatisée (désactivée par défaut)
