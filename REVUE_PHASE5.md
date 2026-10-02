# Revue critique avant usage réel (phase 5)

## État des corrections (2 octobre 2026)

| Point | Décision | État |
|---|---|---|
| C2 liquidités | corriger | **corrigé** : quantité plafonnée par capital + résultat encaissé − investi ; INTERDIT si 0 |
| H1 perte maximale | corriger | **corrigé** : « Perte au stop » (≤ budget) + « PERTE MAXIMALE » = toute la mise + exemple de gap à −30 % |
| H2 seuil d'arrêt | depuis le point haut | **corrigé** : baisse du résultat encaissé depuis son point haut |
| M1 clé dans les logs | corriger | **corrigé** : clé en en-tête HTTP pour Finnhub et Twelve Data ; masquage des clés dans tous les logs urllib3 (test en DEBUG réel) |
| M2 rappel d'ouverture | corriger | **corrigé** : rappel calé sur 9:30 New York, converti en heure de Paris chaque jour |
| M5 achat ≠ fiche | corriger | **corrigé** : quantité, stop, instrument et prix comparés à la fiche, alerte immédiate et bilan |
| C1, H3, H4, M3, M4, M6, F1-F6 | — | ouverts |

Points encore ouverts : la perte possible des positions ouvertes (stops) ne bloque toujours pas un nouvel
achat (seconde moitié de H2) ; C1 reste à confirmer sur une vraie réponse de Twelve Data.

Liste d'origine ci-dessous, inchangée.
« Prouvé » = reproduit par une expérience le 2 octobre 2026. « À confirmer » = déduit du code ou de la
documentation, pas encore observé sur une vraie réponse.

## Critique (à corriger avant tout argent réel)

**C1. Variation du S&P 500 probablement fausse via Twelve Data (à confirmer).**
`TwelveData._quote` demande `interval=1min`. Dans ce cas, `percent_change` est calculé par rapport à la
bougie précédente (une minute), pas à la clôture de la veille. Le test de feu vert verrait donc ≈ 0 % même un
jour de krach. Twelve Data n'est utilisé que si Finnhub échoue, mais alors une règle bloquante est
contournée sans aucun signal. Fichier : `poste/donnees/fournisseurs.py`.

**C2. Les liquidités ne sont jamais vérifiées (prouvé).**
Avec 2 000 € déjà investis au niveau 3, la fiche Nvidia sort FEU VERT pour 821 € de plus : 2 821 € engagés
pour 2 500 € de capital. Seule l'alerte d'exposition à 60 % apparaît, et elle ne bloque pas. Ni le nombre de
positions simultanées ni l'argent disponible ne sont contrôlés. Fichier : `poste/fiche.py`.

## Haute

**H1. « PERTE MAXIMALE » n'est pas un maximum (prouvé).**
La fiche affiche la perte au stop (84 € dans l'exemple). Si Nvidia ouvre 30 % plus bas après une annonce, le
stop s'exécute à l'ouverture : perte ≈ 248 €, trois fois plus. Le gap n'est mentionné que plus bas, dans
« si ça tourne mal ». Le titre en majuscules laisse croire à une garantie. Pour une action, la vraie perte
maximale est le montant engagé. Fichier : `poste/fiche.py`.

**H2. Le seuil d'arrêt se calcule sur la perte nette (prouvé).**
+200 € puis −400 € donnent une « perte cumulée » de 204 €, alors que tu as perdu 400 € depuis ton point
haut. Les gains passés retardent l'arrêt. De plus, la perte possible des positions ouvertes (stops) ne
compte pas pour bloquer un nouvel achat. Question pour toi : seuil sur la perte nette, ou sur la baisse
depuis le point haut ? Fichiers : `poste/journal.py`, `poste/fiche.py`.

**H3. Biais du survivant dans le backtest.**
Nvidia a été choisi en 2026, en sachant qu'elle a été l'une des meilleures actions de la décennie. Un
backtest 2015-2026 sur Nvidia paraîtra excellent pour presque n'importe quelle règle. Ce n'est pas une fuite
du futur dans le code, c'est une fuite dans le choix de l'instrument. Le rapport ne le dit pas.
Fichier : `poste/backtest/rapport.py`.

**H4. Le backtest ne teste pas exactement la règle de la fiche.**
- Filtre : la fiche compare le cours *en séance* à la MM50 ; le backtest compare la clôture *de la veille*.
- Taille : la fiche dimensionne par le risque (50 € max au niveau 1, soit environ 2 Nvidia, ~330 €) ; le
  backtest investit toujours 625 €, quel que soit l'écart du stop. Les rendements en euros et la comparaison
  des stops (un stop ATR plus large donnerait une position plus petite) ne correspondent pas à la réalité.
- Une seule position à la fois par instrument, jamais les quatre ensemble : la perte corrélée (tout baisse
  en même temps) n'est pas mesurée.

## Moyenne

**M1. Clé visible si quelqu'un active les logs détaillés (prouvé).**
Avec `logging` en mode DEBUG, la bibliothèque urllib3 écrit l'URL complète, donc `token=…` / `apikey=…`.
Aujourd'hui rien n'active ce mode, mais il suffit d'une ligne de débogage. Corrections possibles : forcer
urllib3 au niveau WARNING et envoyer les clés dans un en-tête HTTP plutôt que dans l'URL (Finnhub et
Twelve Data l'acceptent, à vérifier dans leur documentation). Les clés dans l'URL peuvent aussi finir dans
les journaux d'un proxy. Fichier : `poste/donnees/fournisseurs.py`.

**M2. Rappel faux pendant la semaine décalée (prouvé).**
Du 26 au 30 octobre 2026, l'Europe est passée à l'heure d'hiver (25/10), pas encore les États-Unis
(1er/11) : la séance US ouvre à **14:30** à Paris. Le rappel de 15:15 dit « ouvre à 15:30 » et arrive
45 minutes après l'ouverture. Même problème en mars (du 8 au 29 mars 2026). Fichier : `poste/rappels.py`.

**M3. Le mode manuel n'a aucun contrôle de fraîcheur.**
`python -m poste` accepte n'importe quelle valeur tapée, même lue la veille ou un week-end. Rien ne date la
saisie et rien ne vérifie que la séance US est ouverte. Le contrôle d'écart à 3 % ne protège que le cours.
Fichier : `poste/__main__.py`.

**M4. Taux US 10 ans de la veille.**
FRED publie avec un jour de décalage : le test de feu vert peut passer alors que le taux a franchi 5,40 %
dans la journée. C'est documenté, mais la fiche ne le rappelle pas au moment du verdict.

**M5. Le journal ne compare pas l'achat à la fiche.**
Acheter 10 titres quand la fiche en prévoit 2, ou poser un stop plus bas que celui de la fiche, n'est pas
signalé dans le bilan. Seul le dépassement du prix limite l'est. Fichier : `poste/bilan.py`.

**M6. ATTENDRE affiche quand même quantité et prix.**
C'est fait pour apprendre, mais un débutant pourrait passer l'ordre quand même. Le bilan ne détecte pas
« achat sur une fiche ATTENDRE » (il le compte comme « sans fiche FEU VERT », ce qui reste juste mais flou).

## Faible

- **F1.** Le compteur de 25 requêtes Alpha Vantage change de jour à minuit heure de Paris ; Alpha Vantage
  remet peut-être le sien à zéro à une autre heure (non documenté) : risque de quelques requêtes refusées.
- **F2.** L'exposition est calculée au prix d'achat, pas au cours actuel.
- **F3.** Comparaisons de dates dans le même fuseau pendant l'heure en double de la nuit du 25 octobre
  (02:00-03:00 existe deux fois) : un événement saisi à cette heure-là peut être mal ordonné. Sans effet
  pratique sur les marchés.
- **F4.** `telecharger` corrige en silence les plus hauts/plus bas incohérents de yfinance : il devrait le
  signaler.
- **F5.** L'année 2026 du walk-forward est incomplète mais pèse comme une année entière.
- **F6.** Les annonces déjà passées (une Fed il y a 10 minutes) ne bloquent pas, alors que la volatilité
  juste après est forte.

## Vérifié, sans problème trouvé

- **Fuite du futur :** la MM50 en direct et le moteur de backtest ne lisent que le passé (tests dédiés :
  modifier le futur ne change aucune décision passée). Les stops ATR et « plus bas 10 séances » sont
  calculés sur les séances précédentes.
- **Donnée périmée → fiche :** en mode auto, une donnée obligatoire rouge bloque la fiche, revérifiée juste
  avant l'émission ; si toutes les sources échouent : « PÉRIMÉ » en rouge, aucune fiche.
- **Clés :** aucune clé dans les logs du programme (test), dans le cache disque (la clé est ajoutée après le
  calcul de la clé de cache), dans le diagnostic, ni dans `repr`. `.env` jamais lu par moi, jamais publié.
- **Arrondis :** calculs d'argent en Decimal, prix limite arrondi au centime supérieur, stop au centime
  inférieur, quantité à l'entier inférieur ; les propriétés hypothesis tiennent sur des centaines de cas.
- **Fuseaux de la fenêtre de 24 h :** comparés en UTC, passage à l'heure d'hiver testé ; badges affichés en
  heure de Paris ; bilan du vendredi 22:05 et rappels en heure de Paris, y compris autour du 25 octobre.
- **Aucun ordre réel, aucune automatisation de Trade Republic.**
