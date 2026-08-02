# brvm

Les cours de la [Bourse Régionale des Valeurs Mobilières](https://www.brvm.org)
— 47 sociétés cotées, huit pays de l'UEMOA — collectés, archivés et
analysés, avec un tableau de bord web comme point d'entrée.

**112 725 lignes, 2 996 séances, du 2 janvier 2015 au 27 juillet 2026.**
Ouverture, plus haut, plus bas, clôture et volumes pour chaque valeur et
chaque séance, plus **309 détachements de dividendes datés, onze
exercices (2015-2025), 41 sociétés** — dont **254 exploitables** : les
montants d'avant la réduction du nominal ne sont pas sur la même
échelle que les cours archivés, et sont refusés plutôt que corrigés
(voir `dividende.detachements`).

## Ce que les données disent

Ces conclusions sont mesurées sur l'archive, pas supposées. Elles sont
rappelées ici parce qu'elles conditionnent la lecture de tout le reste.

**Le dividende est l'essentiel du rendement.** Sur les quatre exercices
connus, il rapporte 7 à 10 % par an, tous les ans. Le cours, lui, va de
−1,6 % à +61,4 % selon l'année, et rend 2,8 % l'an en moyenne sur onze
ans. Un backtest sur cours nus ne mesure donc pas la moitié du rendement :
il en mesure le quart, et c'est le quart le plus bruyant.

| exercice | cours (médiane) | dividende | total |
|---|---|---|---|
| 2022 | +3,6 % | +7,3 % | +10,9 % |
| 2023 | −1,6 % | +8,5 % | +6,9 % |
| 2024 | +15,8 % | +10,0 % | +25,8 % |
| 2025 | +61,4 % | +9,7 % | +71,1 % |

**Aucun facteur de prix ne bat le hasard.** Sur 144 cases balayées —
huit prédicteurs × six segments × trois horizons — une seule survit à la
correction du test multiple : le retournement à un mois sur l'ensemble du
marché, IC +0,067 pour une erreur type de 0,019 sur 148 périodes
disjointes (t = 3,6). Momentum, tendance, volatilité et liquidité
sont indiscernables du bruit sur 11,5 ans.

**Le rendement du dividende : on ne peut pas conclure, et c'est une
réponse différente de « non ».** Le rendement connu au détachement,
confronté à la performance du cours sur les douze mois suivants, donne un
IC de **+0,086** — positif sur 6 saisons sur 9, mais avec une erreur type
de 0,085 sur neuf saisons disjointes, soit t = 1,0. Le seuil de détection
de ce test est un IC de 0,169 : en deçà, il ne dit rien. Là où les
facteurs de prix ont été réfutés sur 148 périodes, celui-ci n'a pas été
testé, faute d'histoire. L'absence de preuve n'est pas une preuve
d'absence.

*(Deux corrections successives. Un premier calcul confrontait le rendement de l'exercice N à l'année
civile N+1 entière. C'était un regard en avant : le dividende de
l'exercice N se détache au milieu de l'année N+1 et n'est pas connu en
janvier. Un second tournait avant le garde-fou d'échelle et laissait
entrer les saisons 2016-2017, dont les rendements implicites étaient
impossibles — voir `dividende.detachements`. Le chiffre ci-dessus est
celui du test purgé des deux défauts ; il porte sur neuf saisons au lieu
de dix, et sa puissance en souffre.)*

**Et ce seul effet est inexploitable.** Simulé à dix lignes et
rééquilibrage mensuel, il rend +7,2 % l'an brut contre 5,4 % pour la
référence — puis **−8,3 % net** dès 2,5 % de frais aller-retour. Les frais
valent huit fois l'alpha. Sur cette place, toute stratégie qui tourne plus
de quelques fois par an est morte avant de commencer.

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
ailleurs. Les données arrivent par les actions GitHub, qui déposent
l'archive en artefact — voir « Les actions ne committent pas ».

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

**Collecte**

```bash
python -m brvm verifier        # diagnostic des sélecteurs, sans rien écrire
python -m brvm ingerer         # enregistre la séance publiée par brvm.org
python -m brvm referentiel     # met à jour ticker / nom / secteur
python -m brvm sonder          # un appel réel à l'API sikafinance
python -m brvm sonder-historique  # jusqu'où remonte le calendrier
python -m brvm rapatrier --debut 2015-01-01 --fin 2026-07-27
python -m brvm sonder-dividendes   # ce que rendent les trois sources
python -m brvm dividendes      # calendriers et historique → archive
```

**Analyse**

```bash
python -m brvm noter           # classe les valeurs
python -m brvm rechercher --valeurs   # quel prédicteur marche, et où
python -m brvm predire         # probabilité de surperformance à 3 mois
python -m brvm rendement       # retour à la moyenne du rendement du dividende
python -m brvm backtester      # rejoue le classement dans le temps
```

**Archive et diagnostic**

```bash
python -m brvm importer-dividendes fichier.csv
python -m brvm importer-exogenes   fichier.csv
python -m brvm importer-fondamentaux fichier.csv
python -m brvm exporter        # base → CSV versionnés
python -m brvm importer        # CSV versionnés → base
python -m brvm veille          # l'archive s'enrichit-elle encore ?
python -m brvm qualite         # séances fantômes et désaccords entre sources
python -m brvm etat            # ce que contient la base
```

### Les séances fantômes

`qualite` cherche une signature étroite : une ligne dont le cours vaut un
multiple entier — ×2, ×5, ×10 — de la séance qui la précède **et** de
celle qui la suit. Sous une limite de ±7,5 % par séance, l'aller-retour
est deux fois impossible.

Trente-huit lignes portaient cette marque, toutes entre 2015 et 2017, sur
ONTBF, SAFC et UNXC. Leur mécanisme se lit à découvert sur ONTBF : cours
divisé par deux, quantité doublée, capitaux échangés identiques au franc
près à ceux de la veille. Ce ne sont pas des cours mal transcrits, ce
sont des échos de la séance précédente rejoués à une autre échelle —
d'où le retrait plutôt que la réparation, puisqu'il n'y a aucune vraie
observation à récupérer derrière.

### La limite de ±7,5 % est décrite, jamais imposée

`qualite` rapporte aussi les variations qui franchissent la limite de
séance, rangées par cause probable — **193** sur l'archive :

| | |
|---|---|
| 106 | entre mai et août : le prix de référence est ajusté du dividende au détachement |
| 21 | séance précédente à plus d'une semaine : la limite ne relie pas deux blocs |
| 66 | à examiner |

Aucune n'est refusée. Un contrôle qui crie sur des données justes
s'apprend à s'ignorer, et le jour où il a raison personne ne l'écoute.

Le seuil porte un dixième de point de tolérance, et il n'est pas
arbitraire : les cours se cotent en francs entiers, si bien qu'un
mouvement **bridé** par la limite arrondit et ressort parfois à 7,52 %
sans l'avoir franchie. La distribution le montre — 1 985 variations se
pressent dans [7,45 % ; 7,50 %[. Les compter ferait passer le total de
193 à 411 et noierait les vraies sous cinq fois leur nombre.

### Les deux sources ne disent pas la même chose

`qualite` compare aussi le calendrier de brvm.org au tableau de
sikafinance sur la centaine de couples (société, exercice) qu'ils
partagent. **43 divergent de plus de 10 %**, et plusieurs d'un facteur 2
exact — brvm.org annonce 684 pour BOA Côte d'Ivoire en 2023, sikafinance
342.

Aucune des deux n'est corrigée. Un facteur aussi rond désigne une
convention qui diffère — montant total contre acompte, brut contre net —
pas une faute de saisie ; et la chute du cours au détachement ne
départage pas, la limite de ±7,5 % empêchant un dividende de 9 % de
s'ajuster en une séance. Choisir sans savoir reviendrait à préférer une
source pour la commodité.

**Pourquoi l'avis officiel ne tranche pas.** Le calendrier lie chaque
détachement à l'avis publié par la Bourse, et ces PDF sont bien
atteignables — leur adresse porte la date, le numéro d'avis, l'exercice
et la société. Mais ce sont des **scans sans couche texte** : zéro
caractère extractible sur 340 Ko. Le montant y est lisible par un œil,
pas par un programme. En tirer le chiffre demanderait de la
reconnaissance optique et la validation de cette reconnaissance sur des
montants — un chiffre mal lu serait exactement l'erreur silencieuse que
ce projet s'attache à rendre bruyante. `brvm sonder-avis` et
`brvm texte-avis` restent livrés pour qu'on n'ait pas à refaire le
chemin.

**Ce que ce désaccord coûte, mesuré.** L'archive retient les montants de
brvm.org. Rejouer les mêmes calculs avec ceux de sikafinance donne :

| | apport du dividende | rendement total | IC du rendement |
|---|---|---|---|
| brvm.org (archive) | +95,9 % | +53,4 % | +0,086 (t = 1,0) |
| sikafinance | +84,4 % | +41,8 % | +0,046 (t = 0,5) |

Douze points d'écart sur le rendement total, et un IC qui passe du simple
au double. **C'est l'incertitude ouverte la plus coûteuse du projet** :
elle ne vient ni du modèle ni de la méthode, mais d'une question de
convention que les deux sources ne tranchent pas.

`--retirer` écrit l'archive CSV **et** efface les lignes de la base :
`importer` étant un INSERT OR REPLACE, nettoyer le seul CSV les laisserait
en base, et le premier `exporter` les réécrirait sans un mot.

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

## Les sources

| Source | Ce qu'elle donne | Lue par |
|---|---|---|
| [brvm.org](https://www.brvm.org) `/fr/cours-actions/0` | la cote du jour : clôture, volumes, symboles, secteurs | `ingestion/brvm_org.py` |
| sikafinance `/api/general/GetHistos` | l'historique séance par séance depuis 2015 : OHLC + volume en titres | `ingestion/sikafinance.py` |
| brvm.org `/fr/esv/paiement-de-dividendes` | le calendrier officiel des détachements | `ingestion/dividendes.py` |
| sikafinance `/marches/dividendes` | le calendrier, **et quatre exercices de dividendes et rendements** | `ingestion/dividendes.py` |

brvm.org fait autorité sur la clôture ; sikafinance apporte la profondeur
et l'OHLC. La primauté se joue **colonne par colonne** — voir
`db.fusionner_cours`.

### L'historique n'est pas du HTML, c'est une API

La page `/marches/historiques/SDSC.ci` n'est qu'une vitrine ; le tableau
est rempli par un appel que le navigateur fait derrière :

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

Trois choses que la sonde a démenties, et qu'il aurait été naturel de
supposer de travers :

- **`Volume` compte des titres, pas des francs.** Son ordre de grandeur
  suggérait les francs. Un témoin — une séance dont les deux nombres
  étaient connus par ailleurs — a tranché. L'erreur évitée valait un
  facteur 1 700.
- **L'API est cohérente là où la page ne l'est pas.** Dans le tableau
  HTML, « plus bas » dépasse la clôture huit fois sur dix ; dans l'API,
  la relation tient partout. C'est le rendu du site qui déforme.
- **Le milieu de `bas` et `haut` est le prix moyen de la séance.** Vérifié
  au franc près sur dix séances dont le volume en francs était connu
  ailleurs. C'est ce qui permet de reconstituer `volume_fcfa`, que l'API
  ne rend pas — ni la clôture (−3,4 %) ni l'ouverture (+3,4 %) n'y
  parviennent.

Ces colonnes portent donc les noms du site, pas leur sens habituel : la
propriété est mesurée, l'intitulé est hérité.

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

SQLite, `data/brvm.db` par défaut. Six tables, déclarées dans
`src/brvm/db.py` :

| Table | Clé | Contenu |
|---|---|---|
| `cours` | (date, ticker) | ouverture, haut, bas, clôture, volumes |
| `referentiel` | ticker | nom, secteur, première et dernière présence |
| `dividendes` | (ticker, date_detachement) | montant net, exercice |
| `fondamentaux` | (ticker, date, indicateur) | format long : dividende, rendement, et ce qui viendra |
| `exogenes` | (date, serie) | commodités, taux — chargés à la main |
| `journal_ingestion` | — | trace de chaque exécution |

Cinq d'entre elles sont archivées en CSV versionné et rechargées par
`brvm importer`.

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

Les artefacts sont hébergés hors de GitHub, sur un stockage que certains
environnements d'exécution ne peuvent pas atteindre. `ingestion.yml`
écrit donc aussi l'incrément du jour — une cinquantaine de lignes — dans
son journal, entre `--- DÉBUT INCRÉMENT CSV ---` et `--- FIN INCRÉMENT
CSV ---`. Il suffit alors de lire le journal pour verser la séance.
L'artefact reste la voie normale et complète ; le journal est le filet.

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

**Ces pondérations n'ont été calibrées sur rien, et l'archive dit
maintenant pourquoi cela ne changerait pas grand-chose.** Aucun des quatre
traits ne se distingue du hasard sur 11,5 ans, et le classement met 80 %
de son poids sur les deux plus vides. Ce n'est pas un mauvais réglage,
c'est un socle absent. Le classement reste une **description** utile du
marché — qui a monté, qui s'échange — mais rien n'autorise à en attendre
un rendement, et l'app le dit à l'écran.

Le classement par **rendement du dividende**, lui, ordonne la part du
rendement qui existe réellement. Il figure sous le premier dans l'app.

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

### Recherche systématique

```bash
python -m brvm rechercher --valeurs --csv balayage.csv
```

Balaie prédicteurs × segments × horizons — huit, six et trois — et mesure
chaque case avec l'erreur-type honnête, puis corrige le test multiple par
Benjamini-Hochberg.

**Sans cette correction, la question « quel est le meilleur modèle ? » a
toujours une réponse**, y compris quand la bonne réponse est « aucun » :
144 tests à 5 % de seuil produisent sept cases significatives sur du bruit
pur. Bonferroni ne laisserait rien passer ; Benjamini-Hochberg contrôle la
*part* de fausses découvertes parmi les retenues, ce qui est la question
qu'on se pose vraiment.

Le retour à la moyenne valeur par valeur tombe dans le même piège un cran
plus bas : trois sociétés sur quarante-cinq passent le test de
Dickey-Fuller quand le hasard seul en produirait 2,2. Le nombre attendu
accompagne le tableau.

### L'IC ne circule jamais sans son incertitude

Un IC moyenné sur toutes les dates d'un historique quotidien semble
reposer sur des milliers d'observations. Avec un horizon de 60 séances,
l'étiquette du lundi recouvre celle du mardi à 59/60 : deux dates voisines
racontent la même histoire. Les compter comme indépendantes multiplie le
*t* par racine de l'horizon — environ huit.

Le projet est tombé dans ce piège : la volatilité y est apparue comme un
signal exploitable, *t* = −10,2. Sur les périodes réellement disjointes,
elle vaut −1,4. `prediction.mesurer_ic` calcule donc l'erreur-type sur
`dates / horizon` périodes disjointes, et l'intervalle est collé au
chiffre partout où il s'affiche.

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

Rejoue le classement dans le temps : dix positions équipondérées, frais et
impact déduits, **dividende compté**, comparé à l'univers éligible
équipondéré — c'est cette référence qu'il faut battre, pas zéro.

Sur l'archive, le verdict est net et il ne s'améliore pas quand on compte
le dividende, il empire :

|  | cours nus | dividende compté |
|---|---|---|
| référence | +36,4 % (2,9 % l'an) | **+76,4 % (5,3 % l'an)** |
| stratégie | −41,3 % (−4,7 % l'an) | **−22,0 % (−2,2 % l'an)** |

Le dividende profite davantage à la référence, qui détient les valeurs de
rendement que le momentum délaisse : l'écart se creuse au lieu de se
refermer. Et 42 rééquilibrages à 41 % de rotation coûtent **51,8 % de
frais cumulés** — plus que ce que la référence rapporte.

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
- **dividende approximé** — le tableau pluriannuel donne un exercice, pas
  une date de détachement : il est réparti sur les séances de l'année au
  lieu d'être crédité le jour même. C'est une correction de *niveau*, pas
  de profil, et elle ne vaut rien à quelques jours — un détachement fait
  chuter le cours d'un coup. Elle ne couvre que 35 % des séances ;
- **frais estimés** — commissions et impact sont des paramètres pris du
  côté prudent, pas des relevés de courtage.

## Tests

```bash
pytest -q                     # ou : python tests/test_brvm_org.py
```

Cent trente-sept tests, tous hors ligne.

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

`test_recherche.py` pose la même paire de questions au balayage
systématique, et la première est la plus importante : sur douze marches
aléatoires il ne doit retenir **aucune** case. Une grille de 144 tests à
5 % de seuil en produit sept significatives par pur hasard ; un outil qui
répond toujours « voici le meilleur modèle » se trompe donc la plupart du
temps, et il se trompe en paraissant précis.

`test_dividendes.py` vérifie surtout les REFUS. Les sources nomment les
sociétés sans les coder, et attribuer le dividende de BANK OF AFRICA
BENIN à la BIIC Bénin ne se verrait jamais : aucun contrôle en aval ne
peut le rattraper. Dès que deux candidats correspondent, l'appariement
refuse et la ligne est listée plutôt qu'écrite.

`test_analyse.py` travaille sur des séries fabriquées : la bonne réponse y
est connue d'avance, ce qui est impossible sur des données réelles. Ces
tests ne disent pas que la stratégie gagne — ils ne peuvent pas. Ils vérifient que le calcul fait ce qu'il
annonce sur des séries dont la bonne réponse se pose à la main : que le
saut du momentum écarte bien un krach de trois semaines, qu'une valeur
illiquide n'influence pas les rangs des autres, qu'un historique court
donne un vide et non un nombre.

## Licence

MIT — voir [LICENSE](LICENSE).

## Modèles sectoriels

Les secteurs de la BRVM n'obéissent pas aux mêmes moteurs. Le balayage
systématique n'a trouvé **aucun modèle sectoriel dans les prix** : les
approches ci-dessous reposent toutes sur des données d'une autre nature,
et c'est leur disponibilité qui décide, pas le code.

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
| Télécommunications (Sonatel, Orange CI, Onatel) | Retour à la moyenne sur le rendement du dividende (Ornstein-Uhlenbeck) + calendrier des annonces. Le ML n'apporte rien : revenus stables, logique de rendement | **quatre exercices acquis** — assez pour voir, trop peu pour valider ; calendrier des annonces |
| Consommation de Base / agro (SAPH, SOGB, Palmci, Sucrivoire) | ARIMAX ou VAR à variables exogènes retardées de 1 à 3 mois — le temps que la marge passe dans les résultats publiés. **C'est là que le pouvoir prédictif est le meilleur** | cours du caoutchouc (TSR20, RSS3), huile de palme (CPO), sucre, parité EUR/USD |
| Services Financiers (16 valeurs) | Le secteur le plus profond, donc le seul assez large pour un modèle transversal de fondamentaux | ROE, P/B, taux de distribution, croissance du crédit, taux directeur BCEAO, coût du risque |
| Services Publics (CIE, SODECI) | Retour à la moyenne sur le rendement, point. Tarifs régulés, volatilité quasi obligataire — un modèle complexe ne ferait que surajuster | **quatre exercices acquis**, série longue manquante |
| Industriels, Consommation Discrétionnaire, Énergie | **Ne pas chercher à prédire.** Trop illiquides, mouvements dictés par les annonces. Filtre de liquidité et écran de valorisation | flux d'annonces émetteurs |

Le préalable commun reste la **donnée**, pas le code. Les dividendes sont
désormais collectés automatiquement — quatre exercices, 30 sociétés — ce
qui suffit à établir que le dividende domine le rendement, et pas du tout
à mesurer s'il le prédit : quatre dates ne font pas une validation.

Ce qui manque encore : une série longue de rendements et de PER
(`abourse.com` la publierait par séance, mais son formulaire n'a pas
encore été percé), les fondamentaux des émetteurs, et les cours des
commodités.

## Ce qui manque, et ce qui a été réglé

**Réglé aujourd'hui.** L'archive contenait une séance ; elle en contient
2 996. Le backtest et la prédiction refusaient de conclure ; ils
concluent, et leur conclusion est négative — ce qui est un résultat. Les
dividendes n'existaient pas en base ; ils y sont.

**Ce qui manque encore, par ordre d'importance :**

- **Une série longue de dividendes.** Quatre exercices donnent un ordre de
  grandeur, pas de quoi mesurer un pouvoir prédictif. C'est la donnée qui
  débloquerait trois des cinq approches sectorielles.
- **Le PER et les fondamentaux des émetteurs.** Le quatrième facteur du
  cadre initial — rendement, momentum, P/B, liquidité — n'a jamais pu être
  testé.
- **Les cours des commodités et le taux BCEAO.** Aucune source n'est
  joignable depuis l'environnement de ce projet ; le chargement se fait à
  la main par `brvm importer-exogenes`.
- **Une réponse à une question ouverte** : le retournement à un mois,
  seul effet retenu par le balayage, est-il un artefact de détachement ?
  Un dividende fait chuter le cours mécaniquement, et « baisse puis
  reprise » est exactement la forme du signal. Testable en excluant les
  fenêtres qui contiennent un détachement.
