# brvm

Ingestion de la cote de la [Bourse Régionale des Valeurs Mobilières](https://www.brvm.org)
— les 47 sociétés cotées de l'UEMOA — dans une base SQLite locale.

## L'application web

Le tableau de bord est le point d'entrée. Six onglets — marché, fiche par
valeur, classement, prédiction, backtest, données — cadrés par un **filtre
unique** (secteurs, recherche) placé au-dessus : tous se redessinent sur la
même tranche, le lecteur n'a pas à se demander quel réglage s'applique où.
Il tourne sur **Streamlit Community Cloud**, sans rien à installer.

Chaque tableau s'exporte en CSV, et chaque graphique a son jumeau
tabulaire : une infobulle ne doit jamais être le seul accès à une valeur.

### Couleurs

Le mode sombre est une palette **choisie**, pas un inversement automatique :
l'app lit le thème actif et sélectionne le jeu correspondant, chacun validé
séparément contre son propre fond.

Hausse et baisse suivent une paire **bleu ↔ rouge** et non le vert/rouge
boursier habituel — la confusion vert-rouge est le déficit visuel le plus
répandu. La paire retenue mesure ΔE 21,6 en protanopie là où vert/rouge
s'effondre, et le signe reste écrit dans les tableaux.

Le texte ne porte jamais la couleur d'une série : l'identité vient de la
marque colorée posée à côté — un point en bout de courbe — parce qu'une
teinte claire est illisible en texte sur le fond.

### Déploiement

1. Sur [share.streamlit.io](https://share.streamlit.io), connectez le
   dépôt GitHub.
2. Fichier principal : `streamlit_app.py`. Branche : `main`.
3. Déployez. Les dépendances viennent de `requirements.txt`.

L'app **ne lit que les CSV versionnés** du dépôt : elle n'écrit rien et ne
conserve aucun état. C'est délibéré — sur un hébergeur gratuit le
conteneur redémarre quand il veut et son disque ne survit pas ; y stocker
des données donnerait une app affichant ce que personne ne peut retrouver
ailleurs. Les données arrivent par l'action `ingestion.yml`, qui commite
l'archive.

Il n'y a donc **rien à faire tourner en local**. La ligne de commande
ci-dessous reste disponible pour le diagnostic et sert à l'action GitHub,
mais l'usage courant passe par l'app.

### En local, si besoin

```bash
pip install -e ".[web]"
streamlit run streamlit_app.py
```

## Ligne de commande

```bash
pip install -e ".[dev]"
```

Python 3.11 ou plus (le module lit sa configuration avec `tomllib`).

```bash
python -m brvm verifier        # diagnostic des sélecteurs, sans rien écrire
python -m brvm ingerer         # enregistre la séance publiée
python -m brvm referentiel     # met à jour ticker / nom / secteur
python -m brvm noter           # classe les valeurs
python -m brvm predire         # probabilité de surperformance à 3 mois
python -m brvm rendement       # retour à la moyenne du rendement du dividende
python -m brvm importer-dividendes fichier.csv
python -m brvm importer-exogenes   fichier.csv
python -m brvm importer-fondamentaux fichier.csv
python -m brvm backtester      # rejoue le classement dans le temps
python -m brvm exporter        # base → CSV versionnés
python -m brvm importer        # CSV versionnés → base
python -m brvm veille          # l'archive s'enrichit-elle encore ?
python -m brvm etat            # ce que contient la base
```

`verifier` accepte un fichier, pour travailler sans réseau :

```bash
curl -sL https://www.brvm.org/fr/cours-actions/0 -o cote.html
python -m brvm verifier cote.html
```

C'est la commande à lancer en premier quand l'ingestion échoue : elle
imprime les colonnes reconnues et leur intitulé d'origine, ce qui dit
exactement quoi corriger dans `ALIAS_COLONNES` ou `SELECTEURS`.

## Configuration

Tout a un défaut utilisable ; `config.toml` à la racine est facultatif.
Voir `config.exemple.toml`. Deux variables d'environnement priment :

| Variable | Effet |
|---|---|
| `BRVM_CONFIG` | chemin d'un autre fichier de configuration |
| `BRVM_BASE` | chemin de la base SQLite |

## Ce que le code sait de brvm.org

Le site a plusieurs comportements qui produisent des données fausses mais
plausibles. Ils sont documentés dans `src/brvm/ingestion/brvm_org.py` et
verrouillés par des tests ; les résumer ici évite de les redécouvrir.

- **La cote n'est pas paginée.** `/fr/cours-actions/{n}` n'est pas un
  numéro de page mais un **identifiant de secteur** (194 à 200). Les 47
  sociétés tiennent sur `/0`.
- **Un identifiant inconnu ne renvoie pas 404** : le site sert la cote
  entière. Une vue sectorielle mal ciblée rangerait donc les 47 sociétés
  dans un seul secteur, sans qu'aucune erreur ne se déclenche.
- **L'URL demandée ne garantit pas le secteur servi.** Le 27/07/2026,
  `/fr/cours-actions/197` a rendu « Energie » puis « Industriels » à dix
  minutes d'intervalle. Le code ne croit donc que l'intitulé affiché par
  la page elle-même, et écarte toute vue qui ne se réclame pas du secteur
  demandé.
- **La page des sociétés cotées ne publie aucun symbole boursier.**
  `/fr/emetteurs/societes-cotees` est une vue en fiches — logo, adresse,
  téléphone. Le référentiel se lit donc sur la cote, seule page à porter
  « Symbole » et « Nom ». (`/fr/societes-cotees/0`, l'URL qu'on croirait
  bonne, renvoie une 404 habillée du thème complet.)
- **Les colonnes ne se rafraîchissent pas ensemble.** Même séance close,
  `clôture / veille - 1` ne redonne la variation publiée que pour environ
  la moitié des lignes. Le diagnostic le signale sans bloquer : ni
  `veille` ni `variation` ne sont enregistrées.
- **La date de séance vient de `#block-tools-date-maj`**, pas de la
  bannière du site — deux horodatages différents cohabitent sur la page.
  Aucun repli sur la date du jour : une séance mal datée fausserait tous
  les décalages J → J+1 sans être détectable.

## Base

SQLite, `data/brvm.db` par défaut. Trois tables, déclarées dans
`src/brvm/db.py` :

| Table | Clé | Contenu |
|---|---|---|
| `cours` | (date, ticker) | ouverture, haut, bas, clôture, volumes |
| `referentiel` | ticker | nom, secteur, première et dernière présence |
| `journal_ingestion` | — | trace de chaque exécution |

Réenregistrer une séance déjà présente la corrige au lieu de la dupliquer.

`data/referentiel_amorce.csv` est le filet de secours quand le scraping du
référentiel échoue. Il a été constitué à partir des captures du 27/07/2026
et couvre les 47 sociétés avec leur secteur.

### Les actions ne committent pas, elles déposent

Un runner GitHub n'a pas de clé de signature : tout commit qu'il produirait
resterait non signé, et l'historique du dépôt cesserait d'être
intégralement vérifiable pour la commodité d'un cron.

`ingestion.yml` et `rapatriement.yml` sont donc en **lecture seule** et
publient un artefact `archive-<run_id>` contenant `data/`. Le versement se
fait depuis une session, qui signe :

1. onglet **Actions** → l'exécution → télécharger l'artefact `archive-…` ;
2. décompresser dans `data/` ;
3. `python -m brvm importer` puis `git add data/ && git commit`.

Le prix est réel et assumé : **l'archive n'avance plus toute seule**.
C'est précisément ce que `veille.yml` surveille — elle ouvre une issue
quand la donnée cesse de progresser, et son message distingue les deux
causes possibles : des artefacts en attente, ou une collecte cassée.

### La source de vérité est le CSV, pas la base

`data/cours.csv` et `data/referentiel.csv` sont versionnés ; `data/brvm.db`
ne l'est pas et se reconstruit par `brvm importer`. Trois raisons :

- un binaire versionné grossit sans qu'on puisse lire ce qui a changé, et
  deux ingestions concurrentes y produisent un conflit irréparable ;
- une réingestion après correction d'un sélecteur apparaît en diff, ligne à
  ligne — c'est exactement ce qu'on veut relire pour valider la correction ;
- git fournit alors l'historique et la sauvegarde, sans service externe ni
  identifiants à gérer.

L'action `ingestion.yml` s'appuie là-dessus : elle reconstruit la base
depuis les CSV, ingère la séance, réécrit les CSV et les commite. Elle
tourne à 16 h UTC du lundi au vendredi, une heure après la clôture.

Un refus d'ingestion n'y est pas traité comme une panne — jour férié,
séance non close, site en maintenance sont des cas normaux. Marquer
l'exécution en rouge chaque jour chômé apprendrait à ignorer les alertes.

Le revers de ce choix est qu'une panne DURABLE ne se verrait pas non plus :
le pipeline pourrait être mort depuis trois semaines sans que rien ne le
dise. C'est ce que ferme `veille.yml`, qui tourne le lundi et ne regarde pas
si la dernière exécution a réussi mais si **la donnée avance**. Au-delà de
cinq jours ouvrés sans nouvelle séance, elle ouvre une issue — une seule,
commentée les semaines suivantes plutôt que rouverte, et refermée
automatiquement dès que l'archive repart.

### Le référentiel est historisé, et ce n'est pas cosmétique

`referentiel` porte `premiere_vue` et `derniere_vue`, et **aucune ligne
n'est jamais effacée**. Le référentiel était auparavant réécrit depuis
l'instantané du jour : une société radiée y perdait sa ligne, son nom et son
secteur, y compris pour les années où elle cotait. Le passé simulé devenait
celui des seuls survivants — le biais que `backtest.py` documente était en
train de se fabriquer à chaque exécution.

Les reclassements sectoriels sont signalés pour la même raison : reclasser
une valeur sans le dire réécrit rétroactivement la composition des secteurs,
donc la neutralisation sectorielle de tout l'historique, sans qu'aucun
chiffre ne bouge visiblement.

## Analyse

```bash
python -m brvm noter -n 15
```

Momentum « 12-1 » — rendement sur un an en sautant le dernier mois —
combiné à une tendance courte et pénalisé par la volatilité, le tout filtré
par un volume médian minimal et neutralisé par secteur.

**Ces pondérations n'ont été calibrées sur rien.** Le module sait produire
un classement reproductible ; il ne sait pas si ce classement gagne de
l'argent, et personne ne le saura avant plusieurs années de séances en base
et un backtest tenant compte des frais et de l'impact de marché — lequel
est considérable sur une place où certaines lignes ne s'échangent pas tous
les jours. Traitez la sortie comme une liste de valeurs à examiner.

Quatre partis pris, détaillés dans `src/brvm/scoring.py` :

- **rangs centiles plutôt que z-scores** — sur 47 valeurs dont certaines
  bougent de 7 % en une séance, une aberration déplacerait la moyenne et
  donc le score de toutes les autres ;
- **filtre de liquidité avant notation** — écartée après coup, une valeur
  illiquide aurait quand même servi à calculer les rangs des autres ;
- **saut du dernier mois dans le momentum** — momentum à un an et
  retournement à un mois sont deux effets opposés ; mesurer jusqu'à
  aujourd'hui achète les hausses les plus fraîches, les plus fragiles ;
- **neutralisation sectorielle au-delà de cinq membres** — seize bancaires
  sur quarante-sept : sans elle, une bonne année du secteur suffirait à
  transformer la sélection de valeurs en pari sectoriel déguisé. En deçà de
  cinq, la valeur est notée face au marché entier, comme celles dont le
  secteur est inconnu.

Un historique trop court ne produit pas un classement approximatif : il ne
produit rien, et la commande le dit.

### Prédiction

```bash
python -m brvm predire
```

Probabilité, par valeur, de **surperformer le marché sur trois mois**.

Le cadrage n'est pas une esquive, ce sont les seules conditions où la
question est soluble ici. La BRVM cote par fixing, avec une limite de
variation de ±7,5 % et des lignes qui ne s'échangent parfois que quelques
fois par semaine : un modèle entraîné à prédire le lendemain apprend
« demain ≈ aujourd'hui », affiche un R² magnifique et produit un backtest
brillant et inexécutable. Et 47 valeurs sur des années font un panel
utilisable en **classement**, là où chaque valeur prise isolément est une
série trop courte et trop bruitée.

**La métrique est l'IC de Spearman**, jamais le RMSE — on juge l'ordre
prédit, pas un cours. **La référence est le score composite** de
`scoring.py`, sans apprentissage. Sur ce marché, un composite simple bat
très souvent un modèle appris : s'il gagne encore ici, c'est lui qui part
en production et le module de prédiction n'est qu'une vérification
coûteuse. L'app le dit explicitement quand c'est le cas.

Ordres de grandeur : un IC de 0,02 à 0,05 est exploitable, 0,10 excellent.
Au-delà de 0,30, cherchez la fuite avant d'y croire.

Deux fuites sont fermées et testées : la validation est glissante — jamais
de découpe aléatoire, qui entraînerait sur mardi pour prédire lundi — et
les dates dont l'étiquette déborde sur la période de test sont **purgées**.
À trois mois d'horizon, cela fait soixante dates retirées avant chaque
période.

Le premier échantillon exige environ quinze mois de cotation : un an pour
que le momentum existe, trois mois de plus pour que la première étiquette
soit connue.

### Backtest

```bash
python -m brvm backtester --journal
```

Rejoue le classement dans le temps : rééquilibrage mensuel, dix positions
équipondérées, frais et impact déduits, comparé à l'univers éligible
équipondéré — c'est cette référence qu'il faut battre, pas zéro.

La question qu'on doit poser à un backtest n'est pas « combien
rapporte-t-il ? » mais « triche-t-il ? ». Deux garde-fous :

- la décision d'une date `t` ne voit que les cours jusqu'à `t` inclus ;
- l'exécution est retardée d'une séance — décider et acheter au même cours
  revient à passer un ordre à un prix déjà connu.

`tests/test_backtest.py` construit une valeur qui monte régulièrement puis
s'effondre juste après avoir été sélectionnée, et exige que le portefeuille
**la détienne** et **encaisse le krach**. Un moteur qui gagne sur ce
scénario est un moteur qui triche. Le test a été vérifié par mutation :
supprimer la coupe temporelle le fait échouer.

Trois biais lui survivent en revanche, et aucun n'est corrigeable avec les
données du projet. Ils accompagnent chaque résultat affiché :

- **biais du survivant** — le référentiel liste les sociétés cotées
  aujourd'hui ; celles radiées entre-temps ont disparu de l'univers, y
  compris des périodes où elles cotaient, et elles ont généralement été
  radiées après avoir mal fini ;
- **dividendes absents** — la table `cours` porte des cours nus, alors que
  les rendements dépassent souvent 5 % sur cette place ;
- **frais estimés** — commissions et impact sont des paramètres pris du
  côté prudent, pas des relevés de courtage.

## Tests

```bash
pytest -q                     # ou : python tests/test_brvm_org.py
```

Soixante et un tests, tous hors ligne.

`test_brvm_org.py` travaille sur les captures réelles de `tests/donnees/`,
y compris les pages pathologiques : la 404 habillée du thème complet, la
vue en fiches sans symboles, la vue sectorielle qui se réclame d'un autre
secteur. Un test qui dépend du réseau échoue pour des raisons étrangères au
code qu'il vérifie.

`test_prediction.py` pose au module les deux questions opposées qui le
jugent : sur du bruit pur il ne doit **rien** trouver — un modèle qui bat
la référence sur une marche aléatoire a une fuite, et cette fuite le fera
briller en validation puis perdre de l'argent ; sur un signal planté à la
main il doit le trouver — un modèle qui ne trouve jamais rien est honnête
et inutile.

`test_analyse.py` travaille sur des séries fabriquées, faute d'historique :
la base ne contient qu'une séance. Ces tests ne disent pas que la stratégie
gagne — ils ne peuvent pas. Ils vérifient que le calcul fait ce qu'il
annonce sur des séries dont la bonne réponse se pose à la main : que le
saut du momentum écarte bien un krach de trois semaines, qu'une valeur
illiquide n'influence pas les rangs des autres, qu'un historique court
donne un vide et non un nombre.

## Licence

MIT — voir [LICENSE](LICENSE).

## Modèles sectoriels

Les secteurs de la BRVM n'obéissent pas aux mêmes moteurs. Deux traitements
sont désormais implémentés ; les autres attendent des données.

### Rendement du dividende — télécoms et services publics

```bash
python -m brvm rendement
```

Sonatel, Orange CI, Onatel, la CIE, la SODECI : revenus réguliers, tarifs
régulés ou quasi, logique d'obligation plus que d'action. Le cours y oscille
autour d'un rendement d'équilibre, estimé par un processus
d'Ornstein-Uhlenbeck. Pas de ML : cinq valeurs ne font pas un échantillon
d'apprentissage.

**La demi-vie est le garde-fou.** Un retour à la moyenne dont la demi-vie
dépasse l'horizon de détention ne dit rien d'exploitable — il aura lieu
après qu'on aura vendu. C'est ce contrôle qui distingue le modèle d'un
simple « ce titre a beaucoup baissé ».

Et un second contrôle, appris à la dure : **les moindres carrés appliqués à
une marche aléatoire trouvent presque toujours un retour à la moyenne**.
Avant correction, ce code en « détectait » un sur 162 marches aléatoires sur
200 — le biais de Dickey-Fuller. La significativité du coefficient est donc
testée, ce qui ramène le taux à 3,5 %. Un test verrouille cette proportion.

### Variables exogènes — agro-industrie

Le cours du caoutchouc à une date donnée est **le même pour les 47
sociétés** : versé tel quel dans un modèle de classement, il a une variance
nulle à l'intérieur d'une séance et ne peut distinguer aucune valeur. Un
modèle l'ingérerait sans broncher et l'IC ne bougerait pas — on conclurait à
tort que les commodités n'expliquent rien.

La variable utile est son produit avec l'appartenance sectorielle :
`caoutchouc(t-L) × 1[valeur en Consommation de Base]`. Celle-là varie bien
entre valeurs d'une même séance. Le retard vaut deux mois par défaut : une
hausse du caoutchouc passe d'abord dans les marges, puis dans des résultats
publiés trimestriellement.

Les séries sont alignées sur le calendrier de la cote par **report de la
dernière valeur connue, jamais par interpolation** — interpoler entre deux
publications mensuelles fabriquerait des valeurs dépendant de la
publication suivante, donc du futur.

Aucune source de commodités n'étant joignable depuis ce projet, les séries
se chargent à la main :

```bash
python -m brvm importer-exogenes commodites.csv   # date,serie,valeur
```

Les noms de séries attendus sont configurables (`[exogenes.correspondance]`
dans `config.exemple.toml`).

### Ce qui reste à faire, et la donnée que chacun réclame

| Secteur | Approche adaptée | Données manquantes |
|---|---|---|
| Télécommunications (Sonatel, Orange CI, Onatel) | Retour à la moyenne sur le rendement du dividende (Ornstein-Uhlenbeck) + calendrier des annonces. Le ML n'apporte rien : revenus stables, logique de rendement | historique des dividendes, calendrier des annonces |
| Consommation de Base / agro (SAPH, SOGB, Palmci, Sucrivoire) | ARIMAX ou VAR à variables exogènes retardées de 1 à 3 mois — le temps que la marge passe dans les résultats publiés. **C'est là que le pouvoir prédictif est le meilleur** | cours du caoutchouc (TSR20, RSS3), huile de palme (CPO), sucre, parité EUR/USD |
| Services Financiers (16 valeurs) | Le secteur le plus profond, donc le seul assez large pour un modèle transversal de fondamentaux | ROE, P/B, taux de distribution, croissance du crédit, taux directeur BCEAO, coût du risque |
| Services Publics (CIE, SODECI) | Retour à la moyenne sur le rendement, point. Tarifs régulés, volatilité quasi obligataire — un modèle complexe ne ferait que surajuster | historique des dividendes |
| Industriels, Consommation Discrétionnaire, Énergie | **Ne pas chercher à prédire.** Trop illiquides, mouvements dictés par les annonces. Filtre de liquidité et écran de valorisation | flux d'annonces émetteurs |

Le préalable commun est la **donnée**, pas le code : les tables
`dividendes`, `fondamentaux` et `exogenes` existent, et `brvm
importer-*` les alimente depuis des CSV. Ce qui manque est un scraper des
rapports des sociétés cotées, et une source pour les commodités et les
taux — aucune n'est joignable depuis l'environnement de ce projet.

## Ce qui manque aussi

**Des données de marché.** Le moteur de backtest et celui de prédiction
sont écrits et vérifiés, mais la base contient une séance : les deux
refusent de conclure et disent combien il leur manque. Tant que la série ne
s'est pas accumulée — quinze mois avant la première prévision calculable —
les pondérations du scoring restent un parti pris et non un résultat.

**Une validation en conditions réelles.** Tout a été vérifié contre des
captures ; le premier `brvm ingerer` face au site vivant reste à faire. Les
runners GitHub n'atteignent pas toujours brvm.org depuis leurs plages
d'adresses : si `ingestion.yml` échoue systématiquement au téléchargement,
c'est cela, et il faudra la faire tourner ailleurs.
