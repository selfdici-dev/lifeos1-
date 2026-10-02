# Exécution automatisée (phase 6) : ce qui est confirmé, ce qui ne l'est pas

Désactivée par défaut (mode MANUEL). Trade Republic n'a pas d'API officielle : l'application ne
l'automatise pas et ne le fera pas.

## Interactive Brokers : vérifié dans les sources publiques (2 octobre 2026)

| Point | État | Source |
|---|---|---|
| API officielle et documentée (TWS API) | confirmé | [IBKR API](https://www.interactivebrokers.com/en/trading/ib-api.php), [docs](https://www.interactivebrokers.com/docs/) |
| Ordres liés achat + stop (« bracket »), transmis ensemble | confirmé | [Bracket Orders](https://www.interactivebrokers.com/docs/general/order-types/complex-orders/bracket-orders), [stop loss](https://www.interactivebrokers.com/docs/tws-api/doc/orders/place-order/adding-a-profit-taker-and-stop-loss) |
| Compte de démonstration utilisable avec l'API (TWS paper : port 7497) | confirmé | [Configurer TWS pour l'API](https://www.interactivebrokers.com/campus/trading-lessons/installing-configuring-tws-for-the-api/) |
| Accessible aux résidents français | confirmé par des sites tiers, à vérifier à l'ouverture du compte | [BrokerChooser](https://brokerchooser.com/broker-reviews/interactive-brokers-review/interactive-brokers-france) |
| **PEA** | **disponible depuis novembre 2024** (contrairement à ce que disait le prompt) | [communiqué](https://www.businesswire.com/news/home/20241120627874/en/Interactive-Brokers-Launches-Plan-dEpargne-en-Actions-PEA-Classique-Accounts) |
| ETF UCITS | disponibles ; les ETF américains sont bloqués pour les particuliers de l'UE (règlement PRIIPs) | [Finorum](https://finorum.com/us-etfs-in-europe/) |
| Frais actions européennes | IBKR Pro « Tiered » : environ 0,05 %, minimum ≈ 1,25 € par ordre ; « Fixed » : minimum plus élevé. **À vérifier pour ton compte** | [Commissions Europe](https://www.interactivebrokers.ie/en/pricing/commissions-stocks-europe.php) |

**Non confirmé** (à vérifier toi-même dans TWS avant tout usage) :
- le code de place `FWB` et la cotation en euros de Nvidia chez IBKR (liste blanche dans `poste/execution/limites.py`) ;
- la disponibilité chez IBKR des turbos, des ETP bitcoin et de l'ETF semi-conducteurs UCITS que tu choisiras ;
- le préfixe « D » des comptes de démonstration (utilisé pour reconnaître un compte de simulation) ;
- le comportement exact du stop lié en cas d'exécution partielle (l'application réduit la quantité du stop) ;
- les abonnements aux données de marché nécessaires.

## Garde-fous codés en dur (`poste/execution/limites.py`)

- 500 € maximum par ordre, 2 ordres maximum par jour.
- Liste blanche : Nvidia seulement pour l'instant (ISIN vérifié auprès d'IBKR avant chaque ordre).
- Jamais de turbo, dans aucun mode (plus strict que le prompt, qui ne l'interdisait qu'en AUTO).
- Jamais de vente à découvert : l'application n'envoie que des achats, chacun avec son stop de vente lié.
- Créneau : 9:45-15:45 à New York, du lundi au vendredi (provisoire, annexe B absente).
- Jamais sans fiche FEU VERT (donc jamais un jour interdit), jamais avec des données périmées.
- `reglages.json` refuse toute clé inconnue : ces limites ne se règlent pas depuis l'interface.

## Modes

- **MANUEL** (défaut) : fiche seulement.
- **CONFIRMATION** : l'ordre complet s'affiche ; il ne part que si tu tapes `OUI`. Un ordre à la fois.
- **AUTO** : envoi sans confirmation, dans les limites ci-dessus.

`python -m poste execution mode CONFIRMATION` pour changer, `python -m poste execution` pour l'état.

## Simulation obligatoire

Un compte réel est refusé (et l'arrêt se déclenche) tant que les conditions suivantes ne sont pas toutes
remplies :
1. au moins **20 ordres** sur le compte de démonstration ;
2. au moins **30 jours** de simulation ;
3. **zéro anomalie** (une anomalie remet le compteur à zéro) ;
4. un fichier `AUTORISATION_ORDRES_REELS.txt`, écrit par toi, contenant exactement :
   `J'autorise l'envoi d'ordres réels par l'application, dans les limites codées en dur.`

Chaque ordre est consigné dans `.cache/simulation.json`, avec la comparaison entre ce qui a été
exécuté et ce que disait la fiche (quantité, prix).

## Stops chez le courtier

L'achat à cours limité et le stop de vente (valable jusqu'à annulation) partent ensemble. Le stop vit
chez IBKR : si ton ordinateur s'éteint, il reste actif. Après chaque envoi, l'application relit l'état
réel chez le courtier : un stop absent ou inactif est une anomalie.

## Interrupteur d'arrêt

`python -m poste arret` : plus aucun envoi, et annulation des **achats** non exécutés.
**Les stops de protection ne sont pas annulés** : les annuler laisserait tes positions sans protection.
Le prompt disait « annule les ordres non exécutés » ; j'ai exclu les stops volontairement.
Arrêt automatique en cas de : seuil de perte atteint, données périmées, réponse inattendue du courtier
(statut inconnu, prix au-dessus de la limite, quantité anormale, stop absent, erreur réseau), ou compte
réel sans simulation validée. Seul `python -m poste reprise` lève l'arrêt, à la main.

## Clés et accès

Aucun identifiant dans le code ni dans les logs : tu te connectes toi-même à TWS ou IB Gateway
(mot de passe et authentification forte à ta charge). L'application parle seulement au logiciel déjà
connecté, sur ta machine. La TWS API ne permet ni retrait ni virement. Tant que tu ne veux aucun envoi,
coche « Read-Only API » dans TWS.

## Rapprochement

Le journal ne reçoit que ce qu'IBKR déclare exécuté (quantité et prix moyen réels). Un ordre encore en
attente n'y est pas noté. Un statut inconnu n'est jamais interprété : il déclenche l'arrêt.

**L'adaptateur IBKR (`poste/execution/ibkr.py`) n'a jamais été testé contre un vrai TWS** : ce conteneur
n'y a pas accès. Toute la logique est testée avec un faux courtier ; le premier essai réel doit se faire
sur le compte de démonstration.
