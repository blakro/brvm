# brvm

Les cours de la **Bourse Régionale des Valeurs Mobilières** — la bourse
commune à huit pays d'Afrique de l'Ouest — collectés chaque jour, archivés
depuis 2015, et analysés.

**➜ [Ouvrir l'application](https://brvm227.streamlit.app)** — rien à
installer, ça marche dans le navigateur.

> **Ce n'est pas un conseil en investissement.** Cet outil décrit ce qui
> s'est passé. Il ne dit pas ce qui va se passer, et il est construit pour
> ne jamais le prétendre.

---

## Sommaire

- [C'est quoi, en deux minutes](#cest-quoi-en-deux-minutes)
- [Le petit lexique](#le-petit-lexique)
- [Ce que les données disent](#ce-que-les-données-disent)
- [Ce qu'il y a dans le dépôt](#ce-quil-y-a-dans-le-dépôt)
- [L'application](#lapplication)
- [La ligne de commande](#la-ligne-de-commande)
- [D'où viennent les données](#doù-viennent-les-données)
- [Où sont stockées les données](#où-sont-stockées-les-données)
- [Les pièges de brvm.org](#les-pièges-de-brvmorg)
- [Ce qui reste à faire](#ce-qui-reste-à-faire)
- [Tests, configuration, licence](#tests-configuration-licence)

---

## C'est quoi, en deux minutes

La BRVM est la bourse de l'UEMOA : **47 sociétés cotées**, réparties sur
huit pays (Bénin, Burkina Faso, Côte d'Ivoire, Guinée-Bissau, Mali, Niger,
Sénégal, Togo). C'est un marché **étroit** : peu de sociétés, peu
d'échanges certains jours, et des informations dispersées.

Ce projet fait trois choses :

1. **Il collecte.** Chaque soir, un robot lit la cote publiée sur
   brvm.org et enregistre les cours du jour.
2. **Il archive.** Tout est conservé dans des fichiers texte versionnés
   dans ce dépôt Git, mis à jour chaque jour de séance — à ce jour
   **112 913 lignes, 3 000 séances, du 2 janvier 2015 au 31 juillet
   2026**, plus **309 versements de dividendes** sur 41 sociétés.
3. **Il analyse.** Une application web affiche le marché, la fiche de
   chaque valeur, un classement, et les résultats des tests statistiques.

Et il en tire une conclusion, mesurée sur onze ans et demi de cotation :

> **Aucune méthode de sélection basée sur les prix ne bat le hasard sur ce
> marché.** Ce qui rapporte, ce sont les dividendes.

Le reste de ce document explique comment on le sait.

---

## Le petit lexique

Cinq mots reviennent partout. Si vous les connaissez déjà, sautez cette
section.

| Mot | Ce que ça veut dire |
|---|---|
| **Séance** | Une journée de bourse. Il y en a environ 250 par an — ni week-ends, ni jours fériés. |
| **Cours de clôture** | Le prix de l'action à la fin de la journée. |
| **Dividende** | La part du bénéfice qu'une société verse à ses actionnaires, en général une fois par an. |
| **Détachement** | Le jour où le dividende est versé. Le cours baisse mécaniquement du montant versé : ce n'est pas une perte, l'argent est passé de l'action à votre poche. |
| **Backtest** | Rejouer une stratégie sur le passé pour voir ce qu'elle aurait donné. Utile pour éliminer les mauvaises idées, **jamais** pour prouver qu'une idée est bonne. |

Deux mots de plus, qui apparaissent dans les résultats :

- **IC** (*information coefficient*) — une note entre −1 et +1 qui mesure
  si un classement prédit vraiment l'avenir. À 0, le classement ne vaut
  pas mieux qu'un tirage au sort. Sur ce marché, tout ce qui est mesuré
  reste très proche de 0.
- **Liquidité** — la facilité à acheter ou revendre. Une action peu
  liquide peut afficher un beau prix sans que personne ne puisse
  réellement l'acheter à ce prix.

---

## Ce que les données disent

Ces conclusions sont **mesurées sur l'archive**, pas supposées. Elles
conditionnent la lecture de tout le reste.

### 1. Le dividende, c'est l'essentiel du rendement

Sur les quatre exercices connus, le dividende rapporte 7 à 10 % par an,
**tous les ans**. Le cours, lui, fait n'importe quoi : de −1,6 % à
+61,4 % selon l'année.

| Exercice | Cours (médiane) | Dividende | Total |
|---|---|---|---|
| 2022 | +3,6 % | +7,3 % | +10,9 % |
| 2023 | −1,6 % | +8,5 % | +6,9 % |
| 2024 | +15,8 % | +10,0 % | +25,8 % |
| 2025 | +61,4 % | +9,7 % | +71,1 % |

Conséquence : une analyse qui ne regarde que les cours ignore la partie
la plus régulière du rendement, et ne garde que la plus bruyante.

### 2. Aucun facteur de prix ne bat le hasard

On a testé **144 combinaisons** — huit méthodes × six segments de marché
× trois horizons de temps. Une seule survit une fois corrigée le fait
qu'en testant 144 choses, on en trouve forcément quelques-unes « qui
marchent » par pur hasard.

Cette unique survivante — le fait qu'une action qui a beaucoup baissé sur
un mois a tendance à remonter le mois suivant — **rapporte moins que les
frais qu'elle coûte**. Simulée avec dix lignes et un rééquilibrage
mensuel : +7,2 % par an avant frais, **−8,3 % après**. Les frais valent
huit fois le gain.

Momentum, tendance, volatilité, liquidité : indiscernables du bruit sur
onze ans et demi.

### 3. Sur le rendement du dividende, on ne peut pas conclure

Et « on ne peut pas conclure » est une réponse différente de « non ».

Le rendement du dividende connu au moment du détachement, confronté à la
performance du cours des douze mois suivants, donne un IC de **+0,086**.
Positif sur 6 saisons sur 9 — mais avec seulement neuf saisons, la marge
d'erreur est trop large pour trancher. Là où les facteurs de prix ont été
**réfutés** sur 148 périodes, celui-ci n'a simplement pas encore pu être
testé, faute d'historique.

L'absence de preuve n'est pas une preuve d'absence.

### Ce que ça change pour vous

Sur un marché où toute stratégie qui tourne plus de quelques fois par an
est mangée par les frais, la conclusion raisonnable est **la détention
longue et diversifiée**, pas la sélection active. L'application affiche
un classement — mais elle affiche aussi, en permanence et avant tout le
reste, que ce classement ne prédit rien.

---

## Ce qu'il y a dans le dépôt

```
streamlit_app.py          l'application web (point d'entrée)
config.exemple.toml       configuration commentée, à copier si besoin
pyproject.toml            dépendances et métadonnées du paquet

data/                     L'ARCHIVE — c'est la base de données du projet
  cours.csv                 112 913 séances-valeurs depuis 2015
  referentiel.csv           les 47 sociétés : ticker, nom, secteur
  dividendes.csv            309 détachements datés
  fondamentaux.csv          indicateurs par société
  exogenes.csv              séries externes (commodités), à charger à la main
  referentiel_amorce.csv    filet de secours si la collecte du référentiel échoue

src/brvm/
  cli.py                    toutes les commandes
  config.py                 lecture de la configuration
  db.py                     schéma SQLite et accès
  features.py               calcul des indicateurs
  scoring.py                le classement
  backtest.py               rejeu de la stratégie dans le temps
  prediction.py             modèle appris, et sa validation
  recherche.py              balayage systématique des prédicteurs
  dividende.py              logique des détachements
  exogene.py                séries externes
  qualite.py                détection des anomalies d'archive
  pedagogie.py              les textes explicatifs de l'app
  ingestion/
    brvm_org.py               la cote du jour
    sikafinance.py            l'historique
    dividendes.py             les calendriers de dividendes

tests/                    237 tests, tous hors ligne
  donnees/                  captures réelles de pages web, servant de témoins

.github/workflows/
  ingestion.yml             collecte quotidienne, 16 h UTC en semaine
  rapatriement.yml          rattrapage d'historique
  versement.yml             verse les séances collectées, 16 h 45 UTC
  veille.yml                alerte si l'archive cesse d'avancer
  tests.yml                 les tests à chaque modification
```

Un fichier n'est **pas** versionné : `data/brvm.db`, la base SQLite. Elle
se reconstruit à partir des CSV. Voir
[Où sont stockées les données](#où-sont-stockées-les-données).

---

## L'application

Elle tourne sur **Streamlit Community Cloud**, gratuitement, et se met à
jour toute seule à chaque nouvelle donnée versée dans le dépôt.

**Cinq onglets**, tous cadrés par un même rang de filtres placé au-dessus
(secteurs, recherche) — vous n'avez jamais à vous demander quel réglage
s'applique où :

| Onglet | Ce qu'on y voit |
|---|---|
| **Marché** | L'état du jour : qui monte, qui baisse, quels volumes. |
| **Valeur** | La fiche d'une société : son cours dans le temps, ses dividendes. |
| **Classement** | Les valeurs ordonnées, et ce que vaut cet ordre. La section « modèle appris » y est incluse. |
| **Backtest** | Ce qu'aurait donné le classement s'il avait été suivi. |
| **Données** | La couverture de l'archive et le journal de collecte. |

Le résultat le mieux établi du projet — aucun facteur de prix ne bat le
hasard — s'affiche **avant** les onglets, pas au fond de l'un d'eux : la
hiérarchie visuelle doit dire la force de la preuve.

Chaque tableau s'exporte en CSV, et chaque graphique a son jumeau
tabulaire. Une infobulle ne doit jamais être le seul accès à un chiffre.

### L'onglet ouvert reste ouvert

Streamlit rejoue tout le script à chaque clic. Deux conséquences, toutes
deux corrigées :

- **L'onglet ne se perd plus.** Il est retenu d'une relance à l'autre, et
  écrit dans l'URL — donc il survit aussi au rechargement de la page, et
  `?onglet=Backtest` se partage tel quel. La société ouverte dans l'onglet
  **Valeur** y est écrite de même, ce qui rend chaque fiche partageable
  par son lien : `?onglet=Valeur&valeur=SNTS`. Les réglages avancés d'un
  onglet survivent de leur côté à un aller-retour par un autre.
- **Seul l'onglet visible se calcule.** Les quatre autres étaient
  entièrement recalculés à chaque interaction : 176 secondes entre deux
  rendus, pour un affichage qui n'en montre qu'un cinquième. Les résultats
  sont en outre gardés en mémoire tant que l'archive ne change pas.

Ouvrir l'app demande aujourd'hui **2,7 secondes**, et une interaction
**deux à cinq dixièmes**. Seule la première ouverture du classement coûte
une dizaine de secondes — c'est la validation glissante du modèle appris,
annoncée par son message d'attente et gardée ensuite.

### Les couleurs

Le mode sombre est une palette **choisie**, pas un inversement
automatique : l'app lit le thème actif et sélectionne le jeu
correspondant, chacun validé contre son propre fond.

Hausse et baisse suivent une paire **bleu ↔ rouge**, pas le vert/rouge
boursier habituel — la confusion vert-rouge est le déficit visuel le plus
répandu. Et le signe reste toujours écrit dans les tableaux : la couleur
ne porte jamais seule une information.

### Redéployer l'application

1. Sur [share.streamlit.io](https://share.streamlit.io), connectez ce
   dépôt GitHub.
2. Fichier principal : `streamlit_app.py`. Branche : `main`.
3. Déployez. Les dépendances sont lues dans `requirements.txt`.

L'app **ne lit que les CSV versionnés**. Elle n'écrit rien et ne conserve
aucun état — sur un hébergeur gratuit, le conteneur redémarre quand il
veut et son disque ne survit pas. Y stocker des données donnerait une app
affichant ce que personne ne peut retrouver ailleurs.

---

## La ligne de commande

**Vous n'en avez pas besoin pour utiliser le projet.** Elle sert au
diagnostic et aux actions automatiques. L'usage courant passe par l'app.

Si vous voulez quand même :

```bash
pip install -e ".[dev]"      # Python 3.11 minimum
python -m brvm --help
```

Pour lancer l'app en local :

```bash
pip install -e ".[web]"
streamlit run streamlit_app.py
```

### Collecter

```bash
python -m brvm verifier      # les sélecteurs tiennent-ils ? n'écrit rien
python -m brvm ingerer       # enregistre la séance publiée par brvm.org
python -m brvm referentiel   # met à jour la liste des sociétés
python -m brvm rapatrier --debut 2015-01-01 --fin 2026-07-31
python -m brvm dividendes    # calendriers et historique des dividendes
```

Lancez toujours `verifier` avant de compter sur la collecte automatique.

### Analyser

```bash
python -m brvm noter         # classe les valeurs
python -m brvm rechercher --valeurs   # quel prédicteur marche, et où
python -m brvm predire       # probabilité de surperformance à 3 mois
python -m brvm rendement     # retour à la moyenne du rendement du dividende
python -m brvm backtester    # rejoue le classement dans le temps
```

### Archiver et diagnostiquer

```bash
python -m brvm exporter      # base → CSV versionnés
python -m brvm importer      # CSV versionnés → base
python -m brvm etat          # ce que contient la base
python -m brvm veille        # l'archive s'enrichit-elle encore ?
python -m brvm qualite       # séances fantômes et désaccords entre sources
python -m brvm importer-dividendes fichier.csv
python -m brvm importer-fondamentaux fichier.csv
python -m brvm importer-exogenes fichier.csv
```

### Sonder une source (mise au point)

Ces commandes font de vrais appels réseau, pour trancher ce qui ne peut
pas l'être hors ligne :

```bash
python -m brvm sonder              # un appel à l'API sikafinance
python -m brvm sonder-historique   # jusqu'où remonte le calendrier
python -m brvm sonder-dividendes   # ce que rendent les trois sources
python -m brvm sonder-avis         # les avis officiels sont-ils atteignables
python -m brvm texte-avis          # vider le texte des avis, pour l'extracteur
```

---

## D'où viennent les données

| Source | Ce qu'elle donne | Lue par |
|---|---|---|
| [brvm.org](https://www.brvm.org) `/fr/cours-actions/0` | la cote du jour : clôture, volumes, symboles | `ingestion/brvm_org.py` |
| sikafinance `/api/general/GetHistos` | l'historique séance par séance depuis 2015 | `ingestion/sikafinance.py` |
| brvm.org `/fr/esv/paiement-de-dividendes` | le calendrier officiel des détachements | `ingestion/dividendes.py` |
| sikafinance `/marches/dividendes` | le calendrier **et** quatre exercices de rendements | `ingestion/dividendes.py` |

brvm.org fait autorité sur la clôture ; sikafinance apporte la profondeur
et le détail ouverture/haut/bas. La primauté se joue **colonne par
colonne** — voir `db.fusionner_cours`.

### L'historique n'est pas une page web, c'est une API

La page `/marches/historiques/SDSC.ci` n'est qu'une vitrine ; le tableau
est rempli par un appel que le navigateur fait en arrière-plan :

```
POST https://www.sikafinance.com/api/general/GetHistos
{"ticker": "SDSC.ci", "datedeb": "2026-01-01",
 "datefin": "2026-03-31", "xperiod": "0"}
→ {"lst": [{"Date": "31/03/2026", "Open": …, "Close": …, "Volume": …}, …]}
```

Ce protocole vient du paquet R [`BRVM` de Koffi Fredy
Sessie](https://github.com/Koffi-Fredysessie/BRVM) (MIT). Aucune ligne de
son code n'est reprise ; ce qui l'est — l'adresse, la forme du corps, le
pas de 89 jours — ce sont des faits sur le service, et le mérite de les
avoir établis lui revient.

Trois choses que la sonde a **démenties**, et qu'il aurait été naturel de
supposer de travers :

- **`Volume` compte des titres, pas des francs.** Son ordre de grandeur
  suggérait le contraire. L'erreur évitée valait un facteur 1 700.
- **L'API est cohérente là où la page ne l'est pas.** Dans le tableau
  HTML, « plus bas » dépasse la clôture huit fois sur dix ; dans l'API, la
  relation tient partout.
- **Le milieu de `bas` et `haut` est le prix moyen de la séance.** Vérifié
  au franc près sur dix séances. C'est ce qui permet de reconstituer le
  volume en francs, que l'API ne fournit pas.

---

## Où sont stockées les données

**Le dépôt Git est la base de données.** Pas de service externe, pas de
compte à créer, pas de mot de passe à gérer.

Les fichiers `data/*.csv` sont versionnés. La base SQLite
(`data/brvm.db`) ne l'est pas : elle se reconstruit en quelques secondes
par `python -m brvm importer`. Trois raisons :

- un fichier binaire versionné grossit sans qu'on puisse lire ce qui a
  changé, et deux collectes simultanées y produisent un conflit
  irréparable ;
- une nouvelle collecte après correction d'un sélecteur apparaît ligne à
  ligne dans le diff — c'est exactement ce qu'on veut relire pour valider
  la correction ;
- Git fournit alors l'historique et la sauvegarde, gratuitement.

Réenregistrer une séance déjà présente la **corrige** au lieu de la
dupliquer.

### Les tables

Six tables, déclarées dans `src/brvm/db.py` :

| Table | Clé | Contenu |
|---|---|---|
| `cours` | (date, ticker) | ouverture, haut, bas, clôture, volumes |
| `referentiel` | ticker | nom, secteur, première et dernière présence |
| `dividendes` | (ticker, date_detachement) | montant net, exercice |
| `fondamentaux` | (ticker, date, indicateur) | dividende, rendement, et ce qui viendra |
| `exogenes` | (date, serie) | commodités, taux — chargés à la main |
| `journal_ingestion` | — | trace de chaque exécution |

### Le référentiel garde la mémoire des sociétés disparues

`referentiel` porte `premiere_vue` et `derniere_vue`, et **aucune ligne
n'est jamais effacée**.

Auparavant, le référentiel était réécrit depuis la photo du jour : une
société retirée de la cote y perdait sa ligne, y compris pour les années
où elle cotait. Le passé devenait celui des seuls survivants — ce qui
fabrique mécaniquement des performances passées trop belles, puisqu'on
oublie ceux qui ont échoué.

### Qui collecte, qui verse, et qui signe

`ingestion.yml` et `rapatriement.yml` sont en **lecture seule**. Ils
publient un artefact `archive-<run_id>` contenant `data/` et n'écrivent
rien : ce sont des collecteurs.

`versement.yml` écrit. Il tourne chaque jour ouvré à 16 h 45 UTC, relit
les artefacts **des ingestions et des rapatriements** récents, contrôle ce
qu'il y trouve, et verse dans `data/` — **en signant**.

**Deux façons d'être absente, une seule se verse.** Une séance postérieure
à l'archive est un retard, elle se verse. Une ligne antérieure, sur une
date que l'archive connaît déjà, en a été retirée à dessein : la
ressusciter est la panne contre laquelle `db.effacer_cours` a été écrit,
et le versement la refuse. Entre les deux il y a le **trou** — une date
entièrement absente, comme le 6 août 2026 dont l'ingestion fut annulée à
mi-course. Celui-là se comble, et c'est à quoi sert `rapatriement.yml` :
`brvm rapatrier --debut … --fin …` relit la période, dépose son artefact,
et le versement suivant le reprend. `brvm veille` liste les trous.

**Pourquoi une clé pour un robot.** Le versement était d'abord manuel,
au motif qu'un runner ne sait pas signer et qu'un historique à moitié
vérifiable ne vaut guère mieux qu'un historique nu. L'objection portait
sur la signature, pas sur l'écriture : une clé propre au robot la lève.
Chaque versement reste « Verified », et l'auteur — `versement
automatique` — dit qui a agi.

Ce que la contrepartie coûte, dit franchement : une signature ne prouve
plus qu'une personne tenait sa clé, seulement que le commit vient de ce
dépôt-ci. La distinction reste lisible dans le journal, mais elle change
de nature.

**Ce que le robot vérifie avant d'écrire**, parce que personne ne
regardera : en-têtes identiques, aucune ligne déjà présente, aucune
séance antérieure à l'archive — ce garde-fou a déjà empêché de
ressusciter 38 séances fantômes — tri préservé, et aucune clôture nulle
ou négative. Un seul contrôle qui tombe annule le versement.

**Ce qu'il ne refuse pas : la limite de ±7,5 %.** La tentation est d'en
faire un invariant dur ; mesurée sur l'archive, elle lève 356 alertes dont
l'immense majorité est légitime — au détachement le prix de référence est
ajusté du dividende, la limite relie deux séances *consécutives* et non
deux blocs séparés d'un mois, et une division du nominal la franchit par
construction. Bloquer là-dessus arrêterait le versement toute la saison
des détachements, de mai à août. Les dépassements sont donc notés dans le
journal ; `brvm qualite` les range par cause probable.

**Quand il ne verse pas**, il retombe sur son ancien comportement :
émettre l'incrément dans son journal, compressé et empreinté, à reprendre
à la main. Une clé absente, un contrôle en échec ou une poussée refusée
font perdre l'automatisme, jamais la donnée.

#### Installer la clé du robot

Une fois, et le versement tourne seul ensuite :

```bash
ssh-keygen -t ed25519 -C "versement automatique brvm" -f cle_versement -N ""
```

1. **Clé publique** (`cle_versement.pub`) → *Settings → SSH and GPG keys →
   New SSH key*, type **Signing Key**. Pas « Authentication » : une clé
   d'authentification ne signe rien.
2. **Clé privée** (`cle_versement`) → *Settings → Secrets and variables →
   Actions → New repository secret*, nom `CLE_VERSEMENT`.
3. **Variable** `COURRIEL_VERSEMENT` (même écran, onglet *Variables*) :
   une adresse **vérifiée** du compte. L'adresse `@users.noreply.github.com`
   convient. Sans elle, le workflow s'arrête plutôt que de produire un
   commit non vérifié.
4. Supprimez `cle_versement` de votre disque.

#### Verser une séance à la main

Si le robot s'est arrêté, l'incrément est dans le journal de
`versement.yml`, avec son empreinte :

```bash
# depuis le journal de l'action : la ligne « --- increment base64 gzip --- »
base64 -d increment.b64 | gunzip > increment.csv
sha256sum increment.csv   # doit correspondre à l'empreinte annoncée
```

puis fusionner dans `data/cours.csv` en respectant le tri, et committer.
L'autre voie reste ouverte : télécharger l'artefact `archive-…`,
décompresser dans `data/`, `python -m brvm importer`.

`veille.yml` surveille l'ensemble : elle ouvre une issue GitHub quand la
donnée cesse de progresser pendant cinq jours ouvrés, et son message
distingue les deux causes possibles — un versement en panne, ou une
collecte cassée.

`veille.yml` lance aussi `brvm verifier` **sur la page vivante**, une fois
par semaine. La distinction fait tout le dispositif : `tests.yml` lance le
même diagnostic sur les captures figées du dépôt — il resterait vert
pendant que brvm.org change de mise en page.

---

## Les pièges de brvm.org

Le site a plusieurs comportements qui produisent des données **fausses
mais plausibles**. Ils sont documentés dans
`src/brvm/ingestion/brvm_org.py` et verrouillés par des tests ; les
résumer ici évite de les redécouvrir.

- **La cote n'est pas paginée.** `/fr/cours-actions/{n}` n'est pas un
  numéro de page mais un **identifiant de secteur** (194 à 200). Les
  47 sociétés tiennent sur `/0`.
- **Un identifiant inconnu ne renvoie pas d'erreur** : le site sert la
  cote entière. Une lecture sectorielle mal ciblée rangerait donc les
  47 sociétés dans un seul secteur, sans que rien ne se déclenche.
- **L'URL demandée ne garantit pas le secteur servi.** Le 27/07/2026,
  `/fr/cours-actions/197` a rendu « Energie » puis « Industriels » à dix
  minutes d'intervalle. Le code ne croit donc que l'intitulé affiché par
  la page elle-même.
- **La page des sociétés cotées ne publie aucun symbole boursier.**
  `/fr/emetteurs/societes-cotees` est une vue en fiches — logo, adresse,
  téléphone. Le référentiel se lit donc sur la cote, seule page à porter
  « Symbole » et « Nom ». (`/fr/societes-cotees/0`, l'URL qu'on croirait
  bonne, renvoie une 404 habillée du thème complet.)
- **Les colonnes ne se rafraîchissent pas ensemble.** Même séance close,
  `clôture / veille − 1` ne redonne la variation publiée que pour environ
  la moitié des lignes. Le diagnostic le signale sans bloquer : ni
  `veille` ni `variation` ne sont enregistrées.
- **La date de séance vient d'un bloc précis** — le « Dernière mise à
  jour » posé au-dessus de la cote, cherché dans `section.block-tools` —
  et pas de la bannière du site : deux horodatages différents cohabitent
  sur la page. Aucun repli sur la date du jour : une séance mal datée
  fausserait tous les calculs sans être détectable.

### Les séances fantômes

`python -m brvm qualite` cherche une signature étroite : une ligne dont
le cours vaut un multiple entier — ×2, ×5, ×10 — de la séance qui la
précède **et** de celle qui la suit. Sous une limite de ±7,5 % par
séance, l'aller-retour est deux fois impossible.

Trente-huit lignes portaient cette marque, toutes entre 2015 et 2017. Leur
mécanisme se lit à découvert sur ONTBF : cours divisé par deux, quantité
doublée, capitaux échangés identiques au franc près à ceux de la veille.
Ce ne sont pas des cours mal transcrits, ce sont des échos de la séance
précédente rejoués à une autre échelle.

---

## Ce qui reste à faire

Le préalable est toujours **la donnée**, jamais le code.

| Ce qui manque | Pourquoi c'est bloquant |
|---|---|
| **Une série longue de dividendes** | Quatre exercices donnent un ordre de grandeur, pas de quoi mesurer un pouvoir prédictif. C'est la donnée qui débloquerait le plus. |
| **Les fondamentaux des émetteurs** (PER, ROE, P/B) | Un des quatre facteurs du cadre initial n'a jamais pu être testé. |
| **Les cours des commodités et le taux BCEAO** | Aucune source n'est joignable depuis ce projet ; le chargement se fait à la main par `importer-exogenes`. |

Et une **question ouverte** : le retournement à un mois, seul effet retenu
par le balayage, est-il un artefact de détachement ? Un dividende fait
chuter le cours mécaniquement, et « baisse puis reprise » est exactement
la forme du signal.

### Pourquoi il n'y a pas de modèle par secteur

Les secteurs de la BRVM n'obéissent pas aux mêmes moteurs, et on pourrait
vouloir un modèle par secteur. Le balayage systématique n'a trouvé
**aucun modèle sectoriel dans les prix** : toutes les approches
envisageables reposent sur des données d'une autre nature, qu'on n'a pas.

Deux exemples de ce que ça donnerait, et de ce qu'il faudrait :

- **Télécoms et services publics** (Sonatel, Orange CI, Onatel, CIE,
  SODECI) — revenus réguliers, tarifs régulés, logique d'obligation plus
  que d'action. Le cours y oscille autour d'un rendement d'équilibre.
  `python -m brvm rendement` estime ce retour à la moyenne. Manque : une
  série longue de rendements. Cinq valeurs ne font pas un échantillon
  d'apprentissage — pas de modèle appris ici, et ce n'est pas un manque.
- **Agro-industrie** (SAPH, SOGB, Palmci, Sucrivoire) — c'est là que le
  pouvoir prédictif serait le meilleur, parce qu'il existe un moteur
  **extérieur** au marché : le prix du caoutchouc, de l'huile de palme,
  du sucre. Manque : ces cours, qu'aucune source joignable ne fournit.

Un détail qui a son importance : le prix du caoutchouc à une date donnée
est **le même pour les 47 sociétés**. Versé tel quel dans un modèle de
classement, il ne distingue aucune valeur et l'IC ne bougerait pas — on
conclurait à tort que les commodités n'expliquent rien. La variable utile
est son produit avec l'appartenance sectorielle.

---

## Tests, configuration, licence

### Tests

```bash
pytest -q                     # ou : python tests/test_brvm_org.py
```

**237 tests, tous hors ligne.** Un test qui dépend du réseau échoue pour
des raisons étrangères au code qu'il vérifie.

`test_brvm_org.py` travaille sur les captures réelles de `tests/donnees/`,
y compris les pages pathologiques : la 404 habillée du thème complet, la
vue en fiches sans symboles, la vue sectorielle qui se réclame d'un autre
secteur.

Deux fichiers de tests posent une question inhabituelle mais décisive —
**le modèle doit aussi savoir ne rien trouver**. `test_prediction.py` et
`test_recherche.py` lui soumettent du bruit pur : il ne doit **rien** en
tirer. Un modèle qui bat la référence sur une marche aléatoire a une
fuite, et cette fuite le fera briller en validation avant de perdre de
l'argent.

`test_dividendes.py` vérifie surtout les **refus**. Les sources nomment
les sociétés sans les coder, et attribuer le dividende de BANK OF AFRICA
BENIN à la BIIC Bénin ne se verrait jamais. Dès que deux candidats
correspondent, l'appariement refuse et la ligne est signalée plutôt
qu'écrite.

### Configuration

Tout a une valeur par défaut utilisable ; `config.toml` à la racine est
**facultatif**. Voir `config.exemple.toml`. Deux variables
d'environnement priment :

| Variable | Effet |
|---|---|
| `BRVM_CONFIG` | chemin d'un autre fichier de configuration |
| `BRVM_BASE` | chemin de la base SQLite |

### Licence

MIT — voir [LICENSE](LICENSE).

---

## Avertissements

- **Ce n'est pas un conseil en investissement.** Aucun élément affiché ne
  constitue une recommandation d'achat ou de vente.
- **Un backtest ne valide rien.** Il sert à éliminer les mauvaises idées.
  On trouve toujours une règle qui aurait marché sur le passé.
- **Les performances passées affichées sont optimistes.** Elles reposent
  sur un univers qui ne contient pas les sociétés radiées.
- **Diffusion publique.** Publier des recommandations d'achat ou de vente
  relève du conseil en investissement boursier, encadré par l'AMF-UMOA
  (ex-CREPMF). Pour un usage personnel, aucun problème. Faites vérifier
  avant toute commercialisation.
- **Collecte.** Le délai entre requêtes est configurable ; ne descendez
  pas sous une seconde.
