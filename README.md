# brvm

Ingestion de la cote de la [Bourse Régionale des Valeurs Mobilières](https://www.brvm.org)
— les 47 sociétés cotées de l'UEMOA — dans une base SQLite locale.

## L'application web

Le tableau de bord est le point d'entrée : cote du jour, classement,
backtest, état des données. Il tourne sur **Streamlit Community Cloud**,
sans rien à installer.

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
python -m brvm backtester      # rejoue le classement dans le temps
python -m brvm exporter        # base → CSV versionnés
python -m brvm importer        # CSV versionnés → base
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
| `referentiel` | ticker | nom, secteur |
| `journal_ingestion` | — | trace de chaque exécution |

Réenregistrer une séance déjà présente la corrige au lieu de la dupliquer.

`data/referentiel_amorce.csv` est le filet de secours quand le scraping du
référentiel échoue. Il a été constitué à partir des captures du 27/07/2026
et couvre les 47 sociétés avec leur secteur.

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
Ce qui est anormal, plusieurs jours sans nouvelle ligne, se voit dans
l'historique du CSV.

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

Trente-neuf tests, tous hors ligne.

`test_brvm_org.py` travaille sur les captures réelles de `tests/donnees/`,
y compris les pages pathologiques : la 404 habillée du thème complet, la
vue en fiches sans symboles, la vue sectorielle qui se réclame d'un autre
secteur. Un test qui dépend du réseau échoue pour des raisons étrangères au
code qu'il vérifie.

`test_analyse.py` travaille sur des séries fabriquées, faute d'historique :
la base ne contient qu'une séance. Ces tests ne disent pas que la stratégie
gagne — ils ne peuvent pas. Ils vérifient que le calcul fait ce qu'il
annonce sur des séries dont la bonne réponse se pose à la main : que le
saut du momentum écarte bien un krach de trois semaines, qu'une valeur
illiquide n'influence pas les rangs des autres, qu'un historique court
donne un vide et non un nombre.

## Licence

MIT — voir [LICENSE](LICENSE).

## Ce qui manque

**Des données.** Le moteur de backtest est écrit et vérifié, mais la base
contient une séance : `brvm backtester` refuse de conclure et dit combien
il lui manque. Tant que la série ne s'est pas accumulée — quelques mois
pour une première idée, des années pour une conclusion — les pondérations
du scoring restent un parti pris et non un résultat.

**Une validation en conditions réelles.** Tout a été vérifié contre des
captures ; le premier `brvm ingerer` face au site vivant reste à faire. Les
runners GitHub n'atteignent pas toujours brvm.org depuis leurs plages
d'adresses : si `ingestion.yml` échoue systématiquement au téléchargement,
c'est cela, et il faudra la faire tourner ailleurs.
