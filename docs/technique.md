# brvm — documentation technique

Le fonctionnement détaillé du projet : ce que les données disent, la ligne
de commande, la collecte et le stockage. Pour une présentation simple, voir
le [README](../README.md) ; pour s'en servir, **[ouvrir
l'application](https://brvm227.streamlit.app)**.

> **Ce n'est pas un conseil en investissement.** Cet outil décrit ce qui
> s'est passé. Il ne dit pas ce qui va se passer, et il est construit pour
> ne jamais le prétendre.

---

## Sommaire

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

### 2. Trente-trois effets sur 360 résistent, et ils vivent à court terme

On a testé **360 combinaisons** — douze méthodes × six segments de marché
× cinq horizons de temps. Trente-trois survivent une fois corrigé le fait
qu'en testant 360 choses, on en trouve forcément quelques-unes « qui
marchent » par pur hasard. Elles se concentrent au bout court :

| Horizon | Cases retenues |
|---|---|
| 5 séances | **18** |
| 10 séances | 12 |
| 20 séances | 3 |
| 60 et 120 séances | 0 |

Les cinq plus fortes :

| Survivante | Segment | Horizon | IC | t |
|---|---|---|---|---|
| **choc éclair** | tout le marché | 5 | +0,049 | **+7,2** |
| retournement 1 mois | tout le marché | 5 | +0,051 | +6,5 |
| choc éclair | tout le marché | 10 | +0,059 | +5,9 |
| choc de volume | tout le marché | 5 | +0,034 | +5,1 |
| retournement 1 mois | Energie | 5 | +0,117 | +4,9 |

**Attention à la lecture du `t`, et c'est l'essentiel de cette section.**
L'erreur-type se calcule sur `dates / horizon` périodes disjointes : à cinq
séances il y a quatre fois plus de blocs qu'à vingt, donc quatre fois plus
de puissance **à effet égal**. Le passage de 2 survivantes à 33 vient
largement de là, pas d'un marché soudain plus prévisible. L'IC par période
le montre — pour la famille volume, il est plus FAIBLE à court terme :

| | 5 | 10 | 20 | 60 |
|---|---|---|---|---|
| choc de volume | 0,034 | 0,046 | 0,053 | **0,064** |
| choc éclair | 0,049 | 0,059 | **0,061** | 0,055 |
| retournement 1 mois | **0,051** | 0,048 | 0,041 | 0,025 |

Par pari, l'horizon long prédit mieux le choc de volume ; par an, l'horizon
court accumule dix fois plus de paris. Le retournement fait l'inverse et
s'éteint après un mois.

Deux remarques, parce qu'elles comptent plus que le classement :

- **La grille a grossi deux fois exprès, et chaque fois contre moi.** Les
  trois traits d'attention ajoutés pour la prédiction auraient pu rester
  dans `features` sans subir la correction que les autres subissent :
  c'eût été garder la meilleure case d'une loterie en refusant de compter
  les tickets. Puis la grille s'arrêtait à vingt séances, et ce vingt avait
  servi d'argument pour fixer l'horizon du modèle — un balayage dont la
  grille exclut la réponse ne peut pas la corroborer. De 162 à 216 puis à
  360 cases, le seuil s'est durci à chaque fois, et les effets sont passés
  quand même.
- **Ce que le marché dit vraiment.** Une action qui s'échange soudain
  beaucoup plus que d'habitude tend à surperformer ; ce n'est pas « une
  action très échangée » — ce niveau-là, la liquidité, ne prédit presque
  rien — c'est le changement de régime. Et une action qui vient de bondir
  tend à rendre une part de son mouvement, mais seulement à quelques
  séances.

Et elle ne paie pas. Simulée avec dix lignes et un rééquilibrage mensuel :

| | Avant frais | Après frais | Rotation |
|---|---|---|---|
| Choc de volume | +27,1 %/an | **+6,2 %/an** | 48 % × 12/an |
| Retournement à un mois | +14,8 %/an | **−14,3 %/an** | 78 % × 12/an |
| Ne rien faire (détention équipondérée) | +14,8 %/an | **+14,8 %/an** | aucune |

Les frais ne rabotent pas l'avantage, ils **renversent le classement** :
le signal le plus fort du marché, exploité comme il se doit, rend moins
de la moitié de ce que rapporte le fait de tout acheter et de ne plus y
toucher. (Ces rendements sont eux-mêmes gonflés par l'absence des
sociétés radiées — voir les avertissements. C'est la comparaison entre
les lignes qui vaut, pas leur niveau.)

Momentum, tendance, volatilité, liquidité : indiscernables du bruit sur
onze ans et demi.

> **Cette conclusion a changé, et c'est instructif.** Jusqu'à récemment
> ce dépôt annonçait le *retournement à un mois* comme seul survivant.
> Le balayage écartait alors sans le dire les valeurs qui ne cotent pas
> tous les jours : une moyenne mobile à 100 séances exige, dans pandas,
> 100 cotations **consécutives**, qu'une action échangée une séance sur
> deux n'a jamais. La grille se prononçait sur la moitié la plus
> régulièrement traitée du marché en croyant se prononcer sur le marché.
> Corrigée, elle désigne un autre vainqueur. Le détail est dans l'en-tête
> de `src/brvm/features.py`.

### 3. Sur le rendement du dividende, on ne peut pas conclure

Et « on ne peut pas conclure » est une réponse différente de « non ».

Le rendement du dividende connu au moment du détachement, confronté à la
performance du cours des douze mois suivants, donne un IC de **+0,086**.
Positif sur 6 saisons sur 9 — mais avec seulement neuf saisons, la marge
d'erreur est trop large pour trancher. Là où les facteurs de prix ont été
**réfutés** sur 151 périodes, celui-ci n'a simplement pas encore pu être
testé, faute d'historique.

L'absence de preuve n'est pas une preuve d'absence.

### 4. Ce que l'apprentissage ajoute, et ce qu'il n'ajoute pas

Le modèle appris de `prediction.py` — celui de l'onglet 🔮 Prédictions —
estime, pour chaque valeur, sa probabilité de **surperformer le marché**.
Mesurée ici à trois mois, sous un protocole unique — dix périodes de test
successives, entraînement toujours antérieur, étiquettes qui débordent
purgées :

| | IC | t | IR | Périodes positives | Pire période |
|---|---|---|---|---|---|
| Au départ | −0,056 | −1,1 | −0,43 | 4 / 10 | −0,240 |
| Univers corrigé, traits ajoutés | +0,045 | +1,5 | +0,52 | 7 / 10 | −0,095 |
| À secteur égal | +0,067 | +2,4 | +0,92 | 8 / 10 | −0,073 |
| **Prix seul, horizon d'une semaine** | **+0,077** | **+9,4** | **+1,84** | **10 / 10** | **+0,019** |

**Attention au `t` de la dernière ligne.** L'erreur-type se calcule sur le
nombre de périodes disjointes, soit `dates / horizon` : en passant de 60 à 5
séances, ce nombre est multiplié par douze (42 → 505) et le `t` grossit d'un
facteur racine de douze sans qu'aucune information soit apparue. **L'IR est
la seule colonne comparable d'une ligne à l'autre** — il vaut 0,92 puis 1,84,
et ce gain-là est réel. La dernière ligne a par ailleurs sa **pire période
positive** : les dix périodes de test le sont.

Les lignes deux à quatre sont mesurées le même jour, sur la même archive —
le gain ne vient pas de données en plus.

L'IC mesure si l'ordre proposé ressemble à l'ordre réalisé ; l'IR le
rapporte à ses écarts d'une période à l'autre, et c'est lui qui dit la
**fiabilité** — deux méthodes au même IC ne se valent pas si l'une le
réalise à chaque période et l'autre une fois sur deux.

Six changements, par ordre d'importance :

1. **Les données.** Une valeur qui n'échange pas tous les jours n'avait
   jamais de tendance calculable, donc jamais de place dans
   l'échantillon : 16 valeurs mesurées par séance sur 38 cotées. Corrigé,
   l'échantillon passe de 40 131 à 100 961 lignes.
2. **Les traits.** Le choc de volume et le retournement à un mois entrent ;
   ce sont eux qui portent tout. Ôtez le premier, l'IC retombe de +0,044
   à +0,011.
3. **Les sources.** Trois sont mesurées et affichées — une régression
   logistique, des poids par trait appris puis rétrécis vers zéro selon la
   force de leur preuve, et le composite de la configuration — mais **une
   seule ordonne** le classement retenu. Elles ont d'abord été moyennées à
   poids égaux ; le point 6 dit pourquoi ce n'est plus le cas, et le
   composite reste le repli quand la porte de production refuse le modèle.
4. **Comparer à secteur égal.** Un rang calculé sur toute la cote mesure
   en partie « est-ce une banque » : les Services Financiers pèsent 34,5 %
   de l'univers, et quand le secteur monte ses valeurs montent ensemble
   dans le classement sans qu'aucune n'ait rien montré. Chaque trait est
   donc désormais comparé à la moyenne de son propre secteur, et
   l'étiquette apprise devient « battre les siens » et non « battre tout le
   marché ». Les dix premières lignes passent de **41,2 % de financières à
   35,4 %** pour un univers à 34,5 % : le pari non choisi tombe de +6,7 à
   **+0,9 point**, et la concentration sectorielle de 0,237 à 0,215, à
   deux centièmes de celle de l'univers lui-même (0,202). Le pari hérité a
   pratiquement disparu.
5. **Trois traits d'attention.** Le choc de volume est le seul signal du
   projet qui tienne ; plutôt que de chercher ailleurs, trois traits
   décrivent mieux celui-là — le choc sur une semaine, la **part** des
   séances au-dessus de la normale plutôt que leur ampleur, et la fréquence
   réelle de cotation. IC +0,045 → +0,050 à eux seuls. À vingt séances, le
   **choc éclair est devenu le premier trait du projet** (IC +0,059,
   t +3,5), devant le choc de volume lui-même (+0,052).
6. **Un mois plutôt qu'un trimestre, et une seule source apprise.** Les deux
   changements viennent de la même mesure — le rendement de **cours** seul,
   sur les valeurs achetables — et la section « Le modèle de prix » ci-dessous
   donne la preuve de chacun.

Et **treize idées reçues, mesurées puis jetées** — elles sont documentées
dans `src/brvm/apprentissage.py`, parce qu'un échec qu'on ne consigne pas
sera retenté :

- **Apprendre les poids de la combinaison** par validation imbriquée : IC
  +0,036 contre +0,045 pour trois poids égaux décidés d'avance. Onze ans
  à trois mois d'horizon ne font que 42 périodes vraiment indépendantes —
  on n'y apprend pas trois poids, on y apprend du bruit.
- **Moyenner plusieurs régressions** (l'« ensemble ») : +0,037 contre
  +0,044 pour une seule. Six coefficients sur cent mille lignes, il n'y
  avait pas de variance à réduire. L'ensemble est conservé quand même,
  pour une autre raison : l'écart entre ses membres donne la **barre
  d'erreur** affichée à côté de chaque probabilité.
- **Sélectionner les traits qui marchent.** En retirant après coup les
  trois traits qui n'ont rien porté on lit +0,076 et un IR de 0,96 — le
  double. Ce chiffre n'existe pas : il suppose de savoir d'avance
  lesquels retirer. Toutes les façons honnêtes de faire ce choix sur la
  seule fenêtre d'entraînement rendent moins que de ne rien sélectionner.
  L'écart entre +0,076 et +0,044 est la mesure exacte de ce qu'un
  backtest gagne à tricher.
- **Le gradient boosting et les forêts.** Huit configurations, du plus
  bridé au plus libre : la meilleure rend +0,031 contre +0,044 pour la
  régression logistique, et la forêt la moins bridée est la plus mauvaise
  des huit. Quand la meilleure case d'un balayage perd de 29 %, il n'y a
  pas de case à cueillir. La raison est plus utile que le verdict : les
  traits sont des rangs centiles, donc un arbre ne gagne rien sur une
  transformation monotone, et il n'y a pas d'interaction à trouver — les
  15 produits croisés et les carrés donnés à la régression déplacent l'IC
  de 0,005, contre une erreur-type de 0,03. L'arbre paie une variance pour
  chercher ce qui n'est pas là.
- **Adapter la CADENCE D'ACHAT aux frais de l'utilisateur.** L'idée était
  séduisante et mesurable : à frais nuls, rééquilibrer tous les mois rend
  +6,5 % annuels contre +5,5 % tous les trimestres, donc un utilisateur peu
  taxé devrait tourner plus vite. Validée par moitiés sur le rendement
  **total**, elle s'effondre — la cadence mensuelle rend **+7,9 % sur la
  première moitié et −4,1 % sur la seconde**, et −13,6 % dès 0,5 % de frais.
  C'est le même piège que la zone tampon à 3,0, consigné dans
  `src/brvm/config.py` : le meilleur réglage de la première moitié est le
  pire de la seconde. La cadence reste donc trimestrielle pour tout le monde.

  **À ne pas confondre avec l'horizon de PRÉDICTION**, qui est passé à un
  mois et dont la section « Le modèle de prix » plus bas montre qu'il tient,
  lui, sur les deux moitiés. Les deux paramètres portent des noms voisins et
  répondent à des questions différentes : à quelle échéance on PRÉVOIT, et à
  quelle fréquence on ACHÈTE. Prévoir à un mois et n'acheter qu'au trimestre
  est la configuration retenue, et c'est celle qui mesure le mieux.
- **Une étiquette en rendement total.** C'est la bonne cible — le porteur
  encaisse le dividende — et l'archive ne la porte pas : le calendrier ne
  couvre que **48,7 %** des séances de détention, et la section 6 montre
  que les exercices non couverts ont bel et bien payé. Le modèle
  apprendrait à préférer les sociétés bien documentées.
- **Les moyennes sectorielles comme traits.** Donner au modèle le momentum
  moyen de chaque secteur : +0,043 contre +0,045. Ce n'est pas le momentum
  de secteur qui aide, c'est le **retrait** du biais de secteur — l'inverse.
- **Retirer le composite de la combinaison.** Son IC est le plus faible
  des trois sources (+0,032) et son pire trimestre le plus mauvais ; on le
  croirait donc dilutif. Mesuré, l'IC de la combinaison tombe de +0,045 à
  **+0,037** sans lui. Il diversifie, et il reste. *(Jugé plus tard sur le
  haut de liste et non plus sur l'IC, ce verdict s'est inversé — voir « Le
  modèle de prix ». Les deux mesures sont justes ; elles ne répondent pas à
  la même question.)*
- **N'apprendre que sur les valeurs achetables.** Deux lignes sur cinq de
  l'archive ne peuvent pas s'acheter : pourquoi apprendre d'un marché qu'on
  ne peut pas jouer ? Parce que c'est **pire** aux trois horizons essayés —
  l'avantage sur les achetables tombe de +7,72 % à +6,03 % annualisés à
  vingt séances. Ces lignes portent la même relation entre traits et
  rendement ; les jeter jette deux observations sur cinq pour rien. Le seuil
  d'achetabilité sert donc à MESURER et à trader, jamais à apprendre.
- **Prophet.** Ajusté valeur par valeur sur le passé seul, à 506 dates
  (19 398 ajustements), et jugé sur les mêmes lignes que le modèle livré.
  Comme prévision de cours, il fait **79 % d'erreur de plus** que « le cours
  ne bouge pas ». Comme classement, sa tendance (IC +0,000) et sa
  saisonnalité (+0,009) ne valent rien ; seul l'écart entre le cours et sa
  courbe porte un signal (+0,088), et une simple moyenne mobile à vingt
  séances fait mieux (+0,102) en millisecondes. Ajouté au modèle à côté de
  cette moyenne mobile, Prophet n'apporte plus rien qui tienne.
- **L'écart à la moyenne mobile, que Prophet cachait.** C'est l'idée qui est
  allée le plus loin avant de tomber, et elle tombe sur le prix seul. Elle
  devient la **case la plus forte** des 390 du balayage (t −9,6), et
  dixième trait du modèle elle porte l'IC de +0,077 à **+0,098** (écart
  apparié t +4,2). Mais le haut de liste ne gagne que deux points, que rien
  ne distingue du hasard (t +0,8), et elle échoue au contrôle que passe le
  modèle livré, l'entrée décalée d'une séance : les trois quarts du gain
  d'IC disparaissent dès t+1, et l'avantage des dix premières passe
  **sous** celui du modèle livré (+11,6 % contre +12,3 %). Ce qu'elle ajoute
  se joue dans la séance qui suit la clôture — un rebond de fixing plutôt
  qu'un mouvement de cours. Le détail est dans `src/brvm/apprentissage.py`.
- **Treize réglages et traits de plus, déclarés avant d'être mesurés.** Sur
  l'étiquette (lissée, extrêmes seuls, continue, sans cours reportés), sur
  l'apprentissage (récence, plusieurs horizons, secteur et marché, score
  lissé) et sur de l'information nouvelle (volume signé, **butées de
  ±7,5 %**, position de la clôture dans le jour, attention qui monte).
  Aucun ne bat le modèle livré : aucun écart n'atteint |t| = 2, sauf une
  perte, et les dix qui gagnent sur la première moitié perdent toutes sur
  la seconde. Les butées, contrairement à ce qu'on observe sur d'autres
  places à limite de prix, ne poursuivent pas : elles se retournent, ce que
  le modèle sait déjà. **Le plafond est dans les données** — cours et
  volumes ont rendu ce qu'ils avaient.
- **Les matières premières.** Cacao, café, sucre, huile de palme,
  caoutchouc, coton, cuivre et huile de coco, d'après les prix mensuels de
  la Banque mondiale, rapportés **valeur par valeur** — le caoutchouc à
  SAPH et SOGB, le sucre à Sucrivoire. Quatre variantes, aucune ne bouge le
  modèle (|t| ≤ 1). Le module prévu pour elles les versait à tout un
  secteur, forme qui s'annule dans un modèle comparant chaque valeur à son
  secteur : il est corrigé. Le **Brent**, qui viserait tout le secteur
  Énergie, a été mesuré à part, sur ses cours quotidiens et contre le
  marché : quand il vient de monter, le secteur tend à battre la cote la
  semaine suivante, sur les deux moitiés et même en entrant trois séances
  plus tard — mais t 1,8, et sans effet sur le classement. Le détail est
  dans `src/brvm/exogene.py`.

Un cinquième arbitrage mérite d'être écrit parce qu'il ne s'est pas joué
sur un chiffre : **ranger dans le secteur** plutôt que retrancher la
moyenne du secteur mesure la même chose (+0,052 contre +0,052). Le
départage est mécanique — le secteur médian ne compte que **4 valeurs
cotées** par séance et le premier quartile 2, si bien qu'une valeur seule
dans son secteur reçoit le rang **maximum** sur tous les traits à la fois,
pour la seule raison qu'elle est seule. Retranchée de sa moyenne, elle
reçoit zéro, c'est-à-dire « rien à dire ». Le cas pèse 0,2 % des lignes et
ne déplace aucune mesure ; c'est la manière de se tromper qui a décidé.

#### Le modèle de prix : ce qui a été retenu, et sur quelle preuve

Le dividende est écarté d'un bout à l'autre de cette section — ni dans la
cible, ni dans le rejeu. On ne juge que ce que le modèle prétend prévoir :
le **cours**.

Trois choix, chacun tranché par le protocole que le projet s'impose depuis
la zone tampon : **on classe les variantes sur la première moitié de
l'archive, on les juge sur la seconde.**

| Choix | Retenu | Preuve |
|---|---|---|
| Sources combinées | la **régression seule** | bat la moyenne des deux sources apprises aux 3 horizons testés, sur les deux moitiés |
| Composite | **retiré** de la combinaison | « avec » perd contre « sans » aux **5 horizons sur 5** |
| Horizon | **20 séances** | voir ci-dessous |

Le composite mérite un mot : son avantage du haut de liste est **négatif**
(−0,10 % par période). Il ordonne honorablement le ventre du marché — son IC
reste positif — et il dégrade les dix valeurs qu'on achète. C'est la même
divergence que plus haut, à l'intérieur d'un seul score.

**L'horizon est le levier principal, et il est monotone.** Le modèle livré,
horizon par horizon, sur les seules valeurs **achetables** (l'avantage
annualisé est mesuré à l'entrée du jour ; le tableau des délais d'exécution
vient plus bas) :

| Horizon | IC | IR | Périodes + | avantage annualisé | 1re moitié | 2nde moitié |
|---|---|---|---|---|---|---|
| **5 séances** | **+0,0768** | **+1,84** | **10 / 10** | **+15,50 %** | **+16,5 %** | **+14,5 %** |
| 10 séances | +0,0705 | +1,40 | 8 / 10 | +10,95 % | +11,4 % | +10,5 % |
| 20 séances | +0,0738 | +1,51 | 9 / 10 | +7,72 % | +9,1 % | +6,3 % |
| 40 séances | +0,0483 | +0,99 | 8 / 10 | +4,13 % | +5,3 % | +2,9 % |
| 60 séances | +0,0599 | +0,88 | 9 / 10 | +3,61 % | +4,2 % | +3,1 % |

Cinq séances gagne sur **toutes les colonnes comparables entre horizons** —
l'IC par période, l'IR, le nombre de périodes positives et l'équilibre entre
les deux moitiés. Le `t` n'en fait pas partie, pour la raison donnée à la
section 2.

Plus court est meilleur, sans exception — et **positif sur les deux moitiés à
tous les horizons**, ce qui distingue ce résultat du mirage de cadence
consigné plus haut. C'est aussi la signature classique
d'un effet de microstructure, d'où **quatre contrôles d'artefact, tous
passés** :

1. **Cours reportés.** 5,3 % des étiquettes de la configuration livrée
   reposent sur un cours reporté, et cette part **ne croît pas** quand
   l'horizon raccourcit (6,5 / 6,6 / 6,7 / 6,8 % à 5, 40, 60, 90 séances).
   Restreindre la mesure aux cours réellement traités en t+H ne change
   pratiquement rien : +15,40 % contre +15,50 %, t +5,13 contre +5,21. Un
   artefact de cours figé se serait effondré.
2. **Entrée décalée.** On ne peut pas acheter au cours qui a servi à
   décider : il est connu après la clôture. L'avantage survit à un décalage
   d'une, deux et trois séances, et cinq séances retardées de trois égalent
   encore vingt séances sans retard — le tableau est plus bas. Ce n'est donc
   pas du rebond de fourchette.
3. **Niveau de cours.** IC de **+0,075 / +0,073 / +0,081** par tercile de
   cours, contre +0,075 sur l'ensemble des achetables : l'effet est uniforme,
   donc ce n'est pas un artefact de pas de cotation sur les petites valeurs,
   où un seul tick fait un gros pourcentage.

   *C'est l'IC qui est mesuré ici, et non l'avantage des dix premières,
   parce que découper l'univers en terciles ne laisse que sept valeurs
   négociables par tranche : « les dix premières » y désignerait presque
   toute la tranche et l'écart s'annulerait par construction. L'IC, lui, se
   calcule sur un petit groupe sans rien couper.*
4. **Forme de la courbe.** Lisse et monotone de 5 à 60 séances, sans pic à
   l'endroit où l'horizon coïncide avec les fenêtres des traits (20).

**Cinq séances, et l'argument qui disait vingt était circulaire.** L'horizon
a d'abord été fixé à vingt, en partie parce que le balayage de `recherche.py`
désignait le choc de volume « à vingt séances » : deux analyses
indépendantes, disait-on, pointaient le même horizon. Or la grille du
balayage était (20, 60, 120) — **vingt était le plus court horizon qu'on lui
autorisait**, et il ne pouvait pas en désigner un autre. La grille contient
désormais 5 et 10, et elle place 18 de ses 33 survivantes à cinq séances,
aucune au-delà de vingt.

L'autre raison avancée alors — la robustesse à l'exécution — ne tient pas
non plus, et le chiffre que j'avais donné (30 % d'avantage perdu par séance
de retard à cinq séances) venait d'une variante à deux sources. Sur la
configuration livrée — le modèle étant réentraîné, pour chaque délai k, sur
le rendement de t+k à t+k+5 :

| Horizon | entrée t+0 | t+1 | t+2 | t+3 |
|---|---|---|---|---|
| **5 séances** | **+15,50 %** | **+12,05 %** | **+9,20 %** | **+7,12 %** |
| 20 séances | +7,72 % | +6,94 % | +6,17 % | +5,20 % |

Cinq séances avec **trois séances de retard** égale encore vingt séances sans
retard. Un effet de rebond de fourchette se serait effondré dès la première.

**Prédire à une semaine n'oblige pas à tourner toutes les semaines**, et les
deux réglages répondent à des questions différentes : `horizon` dit à quelle
échéance on PRÉVOIT, `pas_rebalancement` à quelle fréquence on ACHÈTE. Le
premier est une question de prévision et vaut cinq séances ; le second est
une question de frais et reste trimestriel. Ce n'est pas une incohérence,
c'est la séparation des deux.

#### Deux chiffres pour le haut de liste, et le plus flatteur n'est pas le bon

L'avantage du haut de liste se mesure désormais sur les valeurs
**achetables** — celles dont le volume médian atteint le seuil qu'exige déjà
le classement, 1 million de FCFA par séance. La raison est brutale :

| | avantage des 10 premières |
|---|---|
| tout l'échantillon | +23,1 % / an |
| valeurs achetables seulement | **+15,5 % / an** |

**Deux lignes sur cinq de l'archive n'atteignent pas le seuil**, et l'avantage
y paraît plus du double de ce qu'il est réellement. Un tableau de bord qui
compte des valeurs qu'aucun ordre ne peut atteindre annonce un gain que
personne ne touchera. La validation rend les deux, côte à côte, et la porte de
production se ferme sur le chiffre **achetable**.

C'est aussi ce qui réconcilie la mesure avec le backtest, qui donnait moins
de la moitié : 40 % de l'avantage vivait dans des valeurs non négociables,
l'entrée à la séance suivante en retirait encore 30 %, et le reste est la
composition du rejeu. La composition n'y était pour rien — la version
géométrique est plus haute, pas plus basse.

#### Et les frais, qui restent hors de portée

Cette section est là par honnêteté, pas parce qu'elle a décidé de l'horizon :
le choix ci-dessus s'est fait sur la prévision seule.

Rejeu du signal à cinq séances sur le **cours seul**, écart annuel contre
l'univers, selon la cadence d'achat — **en moyenne sur plusieurs calendriers
de rééquilibrage décalés**, pour la raison donnée juste après :

| Cadence | frais nuls | 0,25 % | 1,50 % | seuil de rentabilité, selon le calendrier |
|---|---|---|---|---|
| 5 séances | +10,3 % | +0,9 % | −36,1 % | 0,19 à 0,36 % |
| 20 séances | +4,9 % | +1,3 % | −15,1 % | 0,05 à 0,76 % |
| 60 séances | +0,7 % | −0,6 % | −6,9 % | aucun (3 fois sur 6) à 1,05 % |

Chaque ligne se refait depuis le dépôt : `python -m brvm backtester --signal
modele --seuil-frais --hors-dividende --pas 60 --calendriers 6`, et de même
pour les autres cadences (voir « La ligne de commande »).

> **Ce tableau a été corrigé une seconde fois.** Sa première version mêlait
> au modèle des décisions du composite : le modèle ne note rien pendant sa
> première tranche d'apprentissage, et le rejeu laissait alors le composite
> choisir, pour **5 décisions sur 47** au trimestre et **52 sur 558** à la
> semaine. Le rejeu commence désormais à la première date notée. Sans frais,
> le modèle seul fait un peu mieux (+10,3 % contre +9,3 % à la semaine) ; à
> 1,50 %, il perd davantage (−6,9 % contre −6,3 % au trimestre), parce qu'il
> tourne plus que le composite. Les seuils et le verdict ne bougent pas.

> **Cette conclusion a changé.** Cette section annonçait, pour 60 séances,
> **+8,0 %** sans frais et un seuil de **1,40 %** par sens, « à la limite »
> des 1,50 % facturés, parce que le signal court « se conserverait » au
> trimestre. Ces chiffres ne se reproduisent pas, pas même au commit qui les
> a écrits avec ses propres données (−3,7 % sans frais, aucun seuil). Surtout,
> **un rééquilibrage trimestriel ne tire qu'une quarantaine de dates de
> décision** sur l'archive : décaler le calendrier de dix séances en dix séances fait passer
> le même modèle de **−4,0 % à +5,4 %** l'an sans frais. Un seul calendrier
> est un seul tirage, d'où la moyenne.

Le signal ne disparaît pas au trimestre : mesurées sur toutes les dates, ses
dix premières achetables battent l'univers de **+2,4 % l'an** avant frais, sur
chaque moitié de l'archive. Mais c'est le cinquième de ce qu'il rend à la
semaine, et **la marge à combler reste d'un ordre de grandeur**, pas de
quelques dixièmes. Aucune cadence ne bat l'univers aux frais réels. Tourner
au trimestre reste le bon choix pour une seule raison, qui tient : à ces
frais, c'est la cadence qui perd le moins. Le conseiller continue de dire
« ne rien faire ».

#### L'IC et l'argent ne disent pas la même chose

C'est le constat le plus utile de tout le travail sur la prédiction, et il
a fallu fabriquer un second chiffre pour le voir.

L'IC note l'ordre de **toute** la cote. Personne n'achète toute la cote.
Un classement peut donc mieux ranger le ventre du marché — ce qui lève
l'IC — en rangeant plus mal les dix valeurs qui sont les seules que
quiconque achètera. Ce n'est pas une inquiétude théorique : c'était le cas
ici.

| Sur la même fenêtre, les mêmes lignes | IC | Avantage des 10 premières |
|---|---|---|
| Avant | +0,045 | **−0,67 %** |
| Après | +0,067 | **+1,39 %** |

L'ancien classement avait un IC positif et ses dix premières lignes
**perdaient** contre l'univers acheté à parts égales. Le tableau de bord
affichait une amélioration là où l'utilisateur aurait perdu de l'argent.

Deux conséquences, toutes deux dans le code :

- `apprentissage.avantage_par_date` mesure l'écart des `positions`
  premières contre la moyenne de la séance, hors échantillon. C'est un
  **rendement**, donc le seul chiffre du projet qui se compare aux frais
  sans passer par la relation de Grinold, et l'onglet 🔮 Prédictions
  l'affiche (« avance de ses 10 favorites »).
- **La porte de production a une seconde condition.** Un IC positif ne
  suffit plus : si le haut de liste a perdu hors échantillon, c'est le
  composite qui part en production. La règle est vérifiée par un test, et
  appliquée à l'ancienne configuration elle la **refuse**.

#### Ce qui n'a pas été démontré, et ce qui a empiré

Le tableau ci-dessus se lit dans les deux sens, et voici l'autre.

**Le gain n'est pas statistiquement établi.** Comparés période par période
sur les mêmes dates, les deux classements diffèrent de +0,013 d'IC avec un
`t` apparié de **+0,45**, et de +2,07 points d'avantage du haut de liste
avec un `t` apparié de **+1,43** — dans les deux cas l'intervalle contient
zéro. Ce qui est établi, c'est que le nouveau classement est
**distinguable du hasard** (`t` +2,4 contre +1,5) et plus régulier
(dispersion entre périodes 0,087 → 0,073, plus stable dans 88 % des
rééchantillonnages) ; pas que l'écart entre les deux soit réel.

**Et le rendement total mesuré, lui, a baissé.** Rejoué par le backtest sur
une fenêtre commune, dividendes compris, l'ancien classement rend +1,1 %
annuels contre l'univers à frais nuls, le nouveau **−0,3 %**. La cause est
identifiée et chiffrée : le portefeuille à secteur égal encaisse **38
points de dividende en moins** sur la fenêtre (194 % contre 232 %), parce
que sur cette place les dividendes sont concentrés dans les financières
dont la neutralisation réduit le poids.

Ce qui a été retenu malgré cela, et pourquoi : la section 6 mesure que le
cours ne reflète que **46 %** du dividende détaché deux séances après.
L'avantage de l'ancien classement passe donc en partie par le même
rendement fantôme que le projet refuse déjà d'exploiter ailleurs — s'y
adosser serait incohérent. Le pari sectoriel abandonné rapportait sur cette
archive ; il n'avait pas été choisi, et il tenait à un défaut d'ajustement
des cours, pas à un pouvoir prédictif. **Aucune des deux versions ne
franchit les frais réels**, et le conseil reste « ne rien faire ».

**Deux réserves, plus importantes que le tableau.** D'abord +0,045 n'est
pas significatif : le t vaut 1,5 là où il en faudrait 2. Le signe a
changé, la dispersion a fondu, sept périodes sur dix sont positives —
rien de tout cela n'autorise à dire que l'IC vrai diffère de zéro.
Ensuite, un IC de 0,045 n'est pas de l'argent : à 3 % l'aller-retour,
l'ordre proposé ne bat pas la simple détention du même univers.

C'est pourquoi les probabilités affichées sont **calibrées** : elles
tiennent entre 45 % et 54 %, et non entre 0 et 100 %. La première valeur
du classement bat le marché un peu plus souvent qu'une pièce. L'afficher
autrement serait un mensonge de présentation.

### 5. Les frais : le seuil, plutôt que le verdict

« Ça ne survit pas aux frais » est vrai et inutilisable — le lecteur ne sait
pas s'il en est loin de 10 % ou d'un facteur dix. `python -m brvm backtester
--signal choc_volume --seuil-frais` rend le **niveau de frais auquel la
stratégie cesse de battre la simple détention du même univers** :

| Signal rejoué | Écart sans frais | Seuil | Frais réels |
|---|---|---|---|
| Composite de la configuration | **−5,4 %/an** | aucun | 1,50 % |
| Choc de volume | **+3,4 %/an** | **0,69 %** | 1,50 % |

Deux lectures, opposées :

- Le **composite** — le classement de `brvm noter` — perd contre
  l'univers équipondéré **même à frais nuls**. Ce n'est pas le courtier qui
  le condamne, c'est le signal. Aucun seuil ne le sauverait.
- Le **choc de volume** gagne réellement avant frais. Son seuil vaut 0,69 %
  par sens ; le marché en coûte 1,50 %. Il manque un facteur deux.

La relation de Grinold — le rendement attendu d'une ligne vaut
IC × dispersion × écart de score — donne indépendamment 0,43 % par sens. Deux
méthodes, le même ordre de grandeur, le même verdict.

**Et réduire la rotation ne comble pas l'écart.** Une zone tampon (garder une
ligne tant qu'elle reste dans les 2N ou 3N premiers) fait bien tomber la
rotation de 64 % à 17 %, mais l'avantage tombe avec elle :

| Zone tampon | Tout l'historique | 1re moitié | 2nde moitié | Rotation |
|---|---|---|---|---|
| 1,0 | −3,86 % | −5,58 % | −4,60 % | 64 % |
| 1,5 | −0,59 % | −0,43 % | −3,43 % | 48 % |
| 2,0 | −2,98 % | −0,22 % | −1,25 % | 35 % |
| 3,0 | **+0,46 %** | **+1,13 %** | **−4,56 %** | 17 % |

Lisez la dernière ligne lentement. Sur l'historique entier, 3,0 est le seul
réglage positif — et il est aussi le meilleur sur la première moitié, donc
celui qu'on choisirait. Sur la seconde, jamais consultée, il est parmi les
**pires**. Le +0,46 % n'existe pas : c'est la meilleure case d'une grille, et
une grille a toujours une meilleure case.

La raison de fond se mesure ailleurs : il faudrait **dix mois de détention**
pour amortir un aller-retour à 3 %, et le choc de volume retombe au pur
hasard en deux périodes. On ne peut pas détenir pour amortir un frais quand
ce qu'on détient a cessé d'être bon.

### 6. Les dividendes : l'archive n'est pas encore utilisable

C'était la piste la plus prometteuse — le dividende fait 7 à 10 % du
rendement annuel contre 2,8 % pour le cours, et 309 détachements datés
dormaient en base sans que la prédiction s'en serve. Elle est fermée, pour
une raison qu'il valait la peine de mesurer.

L'étiquette de la prédiction est un rendement de **cours**. La corriger en
rendement **total** fait passer l'IC de +0,045 (t 1,5) à **+0,079 (t 2,3)** —
le seuil de signification franchi pour la première fois. Le chiffre ne vaut
rien :

- **La couverture.** 26 % des lignes n'ont aucun dividende connu et
  reçoivent donc zéro. Ce zéro n'est pas une société qui n'a rien versé :
  sur les 16 années-sociétés non datées que les fondamentaux peuvent
  arbitrer, **16 versaient bien un dividende**. C'est une donnée manquante
  déguisée en fait. Restreinte aux lignes couvertes, l'amélioration retombe
  à +0,050 (t 1,52) — non significative.
- **Le cours ne reflète pas ce qu'il détache.** `python -m brvm rendement
  --ajustement` le mesure : deux séances après un détachement, le cours
  archivé n'a rendu que **46 %** du dividende versé, en agrégat.

| Séances après le détachement | 1 | 2 | 5 | 10 | 20 | 40 |
|---|---|---|---|---|---|---|
| Part du dividende reflétée | 42 % | 46 % | 56 % | 69 % | 77 % | 88 % |

Ajouter le dividende entier crédite donc la moitié qui n'est jamais tombée.
Et tout trait qui prédit « un détachement approche » prédit alors ce
**rendement fantôme** : « jours depuis le dernier détachement » rend ainsi un
IC de +0,098 et un t de +2,5, entièrement artificiel. C'est le diagnostic qui
l'a démasqué.

Plusieurs causes concourent sans qu'on puisse les départager : la limite de
variation de ±7,5 % par séance, qui interdit à un dividende de 9 % de tomber
d'un coup ; les séances sans échange, où le cours reporté garde la valeur
d'avant détachement ; d'éventuels écarts d'échelle entre montants publiés et
cours archivés. Non séparable veut dire non exploitable.

Les cinq traits tirés du calendrier — rendement, croissance, régularité,
temps depuis le détachement, saisonnalité — mesurés contre l'étiquette de
cours, donnent tous entre −0,018 et +0,006 d'IC, |t| au plus 0,5, positifs
quatre à cinq années sur onze. Aucun n'entre dans le modèle.

Le verrou n'est donc ni le modèle ni le trait : il faut un calendrier de
détachements **complet** et un cours qui les **reflète**. Le jour où
`python -m brvm rendement --ajustement` répondra « utilisable », cette
section sera à refaire — et c'est le seul endroit du projet où il reste un
gain probable à prendre.

### 7. Que faire : la commande `conseiller`

Tout ce qui précède mesure. Cette section-ci décide — parce qu'un classement
ne répond pas à la question qu'on se pose vraiment : *dois-je vendre ce que
je détiens pour acheter ce qui est devant ?*

```bash
python -m brvm conseiller --detenu SGBC BOAC SNTS --frais 1.0 --impact 0.5
```

La règle est celle de n'importe quel arbitrage : **il ne se fait que si son
gain attendu dépasse son coût.** Le gain se calcule (relation de Grinold) :

    gain = IC × dispersion transversale × écart de score

À côté de cette chaîne d'estimations, la sortie donne maintenant un chiffre
**constaté** : ce qu'ont rapporté les dix premières lignes hors échantillon.
Les deux répondent à la même question, l'un par une formule et l'autre par
un relevé, et les voir ensemble dit s'il faut croire l'arithmétique.

L'IC vient de la validation, la dispersion de l'archive, les frais de **votre
SGI** — et c'est le seul paramètre qui vous appartient. Il varie fortement
d'un intermédiaire et d'un pays de l'UEMOA à l'autre, donc la réponse n'est
pas la même pour tout le monde. La commande vous demande vos frais
(`--frais`, `--impact`) plutôt que de supposer les siens.

**Le nombre le plus utile** est l'écart de score qu'un arbitrage doit
franchir pour se payer : `2 × frais / (IC × dispersion)`. Sur 44 valeurs
classées, l'échelle des scores va d'environ −2 à +2. Ce que ça donne :

| Frais par sens | Écart requis | Arbitrages qui se paient |
|---|---|---|
| 1,50 % (IC prudent) | aucun ne suffit | **0** |
| 1,50 % (IC ponctuel) | 3,06 | 1, net +0,08 % |
| 0,25 % | 0,51 | 4, net jusqu'à +2,58 % |

La sortie se termine par **dans quoi tombent les dix premières**, secteur par
secteur, avec l'écart à l'univers coté. Dix lignes dont quatre sont des
banques ne font pas un portefeuille réparti, et aucun autre chiffre ne le
disait.

**Par défaut, le conseil est de ne rien faire** — et ce n'est pas une absence
de réponse. Le classement distingue bien des valeurs, mais l'écart qu'il
mesure entre elles est plus petit que ce que coûte le fait d'y réagir. Sur
cette place, l'inaction est la décision la plus souvent correcte.

**Le défaut emploie la borne basse de l'intervalle de l'IC**, pas son
estimation ponctuelle. Un arbitrage se décide contre un coût *certain* :
parier sur +0,045 quand l'intervalle à 95 % contient zéro revient à engager
une dépense sûre contre un gain non établi. L'option `--ponctuel` bascule
sur l'estimation ponctuelle — et la commande recommande alors des
arbitrages que la preuve ne soutient pas.

Deux actions ne dépendent pas de cette arithmétique :

- **Constituer un portefeuille depuis zéro** : les frais ne sont payés qu'une
  fois, il n'y a pas d'aller-retour à amortir. Les premières du classement
  sont à acheter.
- **Une ligne sortie de l'univers classable** — devenue illiquide, ou plus
  cotée — est à vendre. Le motif n'est pas un gain attendu, c'est le risque
  de ne plus pouvoir en sortir.

Et ce que ce n'est pas : une arithmétique d'arbitrage, pas un conseil
d'investissement. La commande ne connaît ni votre fiscalité, ni votre
horizon, ni votre tolérance au risque, ni la part que ces titres
représentent chez vous.

### 8. Lisible par quelqu'un qui ne connaît rien

Une contrainte, pas une finition : **chaque écran de l'application doit se
comprendre sans rien savoir de la bourse.** Un tableau de bord que personne
ne peut lire ne protège personne.

- **Chaque onglet finit par sa légende** : ce que veulent dire ses
  couleurs, ses icônes et ses chiffres.
- **Un glossaire de 24 mots**, avec recherche, dans l'onglet 🎓 Comprendre,
  à côté d'un guide « acheter sa première action en 6 étapes ».
- **La couleur ne porte jamais seule une information** : vert ▲ et
  rouge ▼, ✅ 🟡 ⚠️ dans la fiche d'une action, ☀️ ⛅ 🌧️ pour la météo.
- **La prédiction ne se montre jamais sans son bilan ni sans les frais** :
  comparée à une pièce de monnaie, avec le nombre d'années où elle a eu
  raison, et le calcul qui montre que 3 % de frais effacent son avance.

### Ce que ça change pour vous

Sur un marché où toute stratégie qui tourne plus de quelques fois par an
est mangée par les frais, la conclusion raisonnable est **la détention
longue et diversifiée**, pas la sélection active. L'application en tire
les conséquences : elle ne propose pas de classement à suivre, montre la
prédiction avec son bilan et le coût des frais, et met les dividendes en
avant.

---

## Ce qu'il y a dans le dépôt

```
README.md                 la présentation pour tous
docs/technique.md         ce document
streamlit_app.py          l'application web (point d'entrée)
config.exemple.toml       configuration commentée, à copier si besoin
pyproject.toml            dépendances et métadonnées du paquet
requirements.txt          dépendances lues par Streamlit Community Cloud

data/                     L'ARCHIVE — c'est la base de données du projet
  cours.csv                 un cours par société et par séance, depuis 2015
  referentiel.csv           les sociétés : ticker, nom, secteur
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
  conseil.py                acheter, conserver, vendre — à vos frais
  backtest.py               rejeu de n'importe quel signal, et seuil de frais
  prediction.py             la prédiction : échantillon, validation, rendu
  apprentissage.py          son cœur appris : poids, ensemble, combinaison
  recherche.py              balayage systématique des prédicteurs
  dividende.py              détachements, et si le cours les reflète
  exogene.py                séries externes
  qualite.py                détection des anomalies d'archive
  pedagogie.py              montants, dates et pourcentages en français
  ingestion/
    brvm_org.py               la cote du jour
    sikafinance.py            l'historique
    dividendes.py             les calendriers de dividendes

tests/                    les tests, tous hors ligne
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

**Cinq onglets**, pensés pour qu'un débutant ait le maximum d'informations
avant d'acheter ou de vendre :

| Onglet | Ce qu'on y voit |
|---|---|
| 🏠 **Aujourd'hui** | La météo du marché, les plus fortes hausses et baisses, les secteurs, toutes les actions de la séance. |
| 🔎 **Une action** | Le prix et son évolution ; une fiche en six points (revente, agitation, pire chute, position sur l'année, dividendes, frais) ; un simulateur d'achat ; les dividendes ; la prévision du modèle pour le mois et pour le trimestre qui viennent. |
| 🔮 **Prédictions** | Le modèle de `prediction.py`, au choix pour le mois ou le trimestre qui vient : météo de chaque action, bilan hors échantillon contre une pièce de monnaie, avance de ses favorites (signalée quand elle n'est pas démontrée), et le piège des frais. |
| 💰 **Dividendes** | Rendements médians par exercice, les plus généreuses, les derniers détachements, un calculateur d'épargne. |
| 🎓 **Comprendre** | Guide pour débuter, règles du marché, glossaire avec recherche, couleurs et symboles. |

Les dividendes viennent de deux sources qui ne suivent pas la même
convention : le dividende **net** de sikafinance (`fondamentaux.csv`), qui
sert aux rendements et aux calculs, et le montant annoncé au détachement
par brvm.org (`dividendes.csv`). L'app étiquette chacun et ne les mélange
pas — voir `qualite.desaccords`.

### La météo du devin : le mois et le trimestre, pas la semaine

L'app prévoit pour **le mois qui vient (20 séances)** et **le trimestre qui
vient (60 séances)**, comptés à partir de la dernière clôture — pas le mois
du calendrier. Le modèle est celui de `prediction.py`, **réentraîné pour
chaque échéance** sur le rendement des 20 ou des 60 séances suivantes :
chacune a son bilan, son avance, son calibrage et sa météo, et une même
action peut être ☀️ à un mois et 🌧️ à un trimestre. La configuration garde
cinq séances pour la ligne de commande ; l'app n'y lit pas son échéance
(voir `HORIZONS` dans `streamlit_app.py`).

**Pourquoi pas la semaine, alors que le modèle y ordonne le mieux la cote ?**
Parce que l'horizon de `prediction.py` se choisit sur la prévision seule, et
celui de l'app sur ce que son lecteur en fera. Une météo de la semaine
invite à passer un ordre par semaine, et c'est la cadence que les frais
punissent le plus — le second tableau ci-dessous.

Ce que vaut le modèle à chaque échéance, sur l'archive arrêtée au 8 octobre
2026 (validation glissante, dix années de test ; l'avance est celle des dix
premières **achetables**, sur la durée de l'échéance) :

| Échéance | Bonnes réponses | Années au-dessus de 50 % | Avance des 10 favorites | t de l'avance |
|---|---|---|---|---|
| 5 séances (l'ancienne météo) | 52,4 % | 9 / 10 | +0,32 % par semaine | +5,4 |
| **20 séances, le mois** | **52,4 %** | **9 / 10** | **+0,63 % par mois** | **+2,9** |
| **60 séances, le trimestre** | **52,1 %** | **9 / 10** | **+0,89 % par trimestre** | **+1,2** |

La porte de production de `valider` (IC et avance positifs hors
échantillon) s'ouvre aux trois échéances, et les bonnes réponses ne bougent
presque pas. C'est l'avance qui se dilue : par an, elle passe de +16 % à
+8 % puis +4 %, et **au trimestre elle n'est plus démontrée** — l'archive ne
contient que 37 trimestres indépendants pour la juger, et l'écart reste dans
sa marge d'erreur. L'onglet le dit en clair chaque fois que
`mesure_avantage` rend `significatif` faux, quelle que soit l'échéance.

Le piège des frais, ensuite : rejeu du modèle **de l'échéance**, ses
favorites rachetées **à la même cadence**, prix seul, écart annuel contre
l'univers, en moyenne sur plusieurs calendriers décalés :

| Échéance et cadence | Calendriers | Frais nuls | 1,50 % par sens | Seuil de rentabilité, selon le calendrier |
|---|---|---|---|---|
| 5 séances | 5 | +9,9 % | −36,3 % | 0,18 à 0,35 % |
| **20 séances** | 7 | **+5,2 %** | **−14,5 %** | 0,06 à 0,80 % |
| **60 séances** | 6 | **+1,3 %** | **−5,7 %** | aucun (2 fois sur 6) à 0,85 % |

Aucune échéance ne paie ses frais ; le verdict de l'onglet est le même aux
trois, et seulement moins sévère quand on tourne moins. La ligne à cinq
séances rend sur l'archive du 8 octobre ce que le tableau de `config.py`
rendait sur celle du 28 septembre (+10,3 % et −36,1 %), au demi-point près.

Ces deux rendements sont les seuls chiffres de l'onglet écrits en dur, dans
`HORIZONS` : un rejeu coûte de une à six minutes. L'échéance passe par un
fichier de configuration, la cadence par `--pas` :

```bash
printf '[prediction]\nhorizon = 20\n' > h20.toml
BRVM_CONFIG=h20.toml python -m brvm backtester --signal modele --seuil-frais --hors-dividende --pas 20 --calendriers 7
printf '[prediction]\nhorizon = 60\n' > h60.toml
BRVM_CONFIG=h60.toml python -m brvm backtester --signal modele --seuil-frais --hors-dividende --pas 60 --calendriers 6
python -m brvm backtester --signal modele --seuil-frais --hors-dividende --pas 5 --calendriers 5
```

Tout le reste de l'app est recalculé sur l'archive du jour.

### L'onglet ouvert reste ouvert

Streamlit rejoue tout le script à chaque clic :

- **L'onglet et la société ne se perdent pas.** Ils sont retenus d'une
  relance à l'autre et écrits dans l'URL : `?onglet=predictions`, ou
  `?onglet=action&valeur=SNTS` pour partager une fiche.
- **L'échéance de la prévision tient aussi**, d'un onglet à l'autre : le
  mois ou le trimestre choisi dans 🔮 Prédictions reste choisi.
- **Seul l'onglet visible se calcule**, et les calculs lourds sont gardés
  en mémoire tant que l'archive ne change pas. Une prévision prend une
  quinzaine de secondes par échéance la première fois (la validation
  glissante du modèle) — une trentaine pour la fiche d'une action, qui
  montre les deux —, annoncée par un message d'attente ; les suivantes sont
  immédiates, pour tous les visiteurs.

### Les couleurs

Hausse en vert, baisse en rouge — mais **toujours avec une flèche ▲ ▼**,
pour qu'un lecteur qui confond les deux couleurs lise quand même le sens.
Le mode sombre a sa propre palette, et les animations se coupent quand le
système demande « moins de mouvement ».

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
python -m brvm predire       # probabilité de surperformance à cinq séances
python -m brvm rendement     # retour à la moyenne du rendement du dividende
python -m brvm rendement --ajustement
                             # le cours reflète-t-il le dividende détaché ?
python -m brvm backtester    # rejoue le classement dans le temps
python -m brvm conseiller --detenu SGBC BOAC --frais 1.0
                             # acheter, conserver ou vendre, à VOS frais
python -m brvm backtester --signal choc_volume --seuil-frais
                             # à partir de quels frais ce signal cesse de payer
python -m brvm backtester --signal modele --seuil-frais --hors-dividende --calendriers 6
                             # le modèle appris, avec frais, sur six calendriers
```

**Rejouer le modèle appris avec frais.** `--signal modele` rejoue les scores
hors échantillon de la validation glissante, où chaque date n'est notée que
par le modèle de sa propre découpe. Le rejeu commence à la première date
notée : avant, le modèle n'a rien vu, et c'est le composite qui aurait
décidé à sa place. `--calendriers N` fait la moyenne sur N calendriers dont
le départ glisse à l'intérieur d'un pas. C'est nécessaire, parce qu'au
trimestre un calendrier ne tire qu'une quarantaine de décisions, et que
décaler son départ fait passer le même modèle de **−4,0 % à +5,4 %** l'an
sans frais. Le tableau de « Et les frais, qui restent hors de portée » se
refait avec trois commandes, `--pas` choisissant la cadence :

```bash
python -m brvm backtester --signal modele --seuil-frais --hors-dividende --pas 5 --calendriers 5
python -m brvm backtester --signal modele --seuil-frais --hors-dividende --pas 20 --calendriers 7
python -m brvm backtester --signal modele --seuil-frais --hors-dividende --pas 60 --calendriers 6
```

Sur l'archive arrêtée au 28 septembre 2026, elles rendent **+10,3, +4,9 et
+0,7 %** d'écart annuel sans frais, puis **−36,1, −15,1 et −6,9 %** à 1,50 %
par sens : le tableau, au dixième près. Les chiffres bougeront un peu à chaque
séance versée. Comptez un peu plus d'une minute au trimestre et cinq à la
semaine ; `--niveaux 0 0.25 0.5 1 1.5` en retire un tiers sans changer aucun
seuil au centième près.

Le rendu dit aussi combien de décisions le modèle a réellement prises. Une
séance trop creuse est écartée de son échantillon, et la décision de ce
jour-là suit le composite : cela arrive **au plus deux fois sur 506** à la
semaine, une fois sur 127 au mois, jamais au trimestre.

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
ressusciter 38 séances fantômes — tri préservé, aucune clôture nulle ou
négative, et **aucune séance republiée**. Un seul contrôle qui tombe
annule le versement.

**Une séance douteuse n'arrête pas les autres.** Ce qui met en cause
l'incrément entier — en-têtes, lignes déjà présentes, lignes antérieures
sur une séance connue — bloque tout : ce sont des signaux de
dysfonctionnement. Une séance individuellement suspecte, elle, est
**écartée seule** et le reste est versé. Le tout ou rien s'est montré
ruineux : un artefact fautif vit trente jours, et il aurait bloqué chaque
versement suivant — la bonne séance du jour refusée avec lui.

La séance republiée mérite son nom : le 6 août 2026, rattrapé par
rapatriement, est revenu avec les 47 cours et les 47 volumes du 7 — la
même séance sous une autre date. Versée, elle a mis toutes les variations
de l'app à 0 %, et c'est un lecteur qui l'a vu. Le critère
vient de `sikafinance.seances_repetees`, mesuré sur ce marché : « deux
échanges égaux au franc près n'existent pas, c'est la même transaction
republiée ». Les volumes nuls, eux, se répètent normalement et ne
comptent pas.

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
| **Des cours de commodités QUOTIDIENS, et le taux BCEAO** | Les prix mensuels de la Banque mondiale ont été mesurés et n'améliorent pas la prédiction à cinq séances : un mois est trop lent pour une semaine. Le Brent quotidien l'a été (signal faible et régulier sur le secteur Énergie, sans effet sur le classement) ; le cacao, le sucre, le caoutchouc et l'huile de palme quotidiens restent à essayer, et aucune source joignable d'ici n'en fournit ; le chargement se fait à la main par `importer-exogenes`. |

Et deux **questions ouvertes**, l'une et l'autre sur le seul effet que le
balayage retient :

- Le **choc de volume** mesure-t-il un comportement de marché, ou
  simplement la proximité d'un événement d'entreprise — détachement de
  dividende, augmentation de capital, entrée d'un actionnaire ? Les deux
  produiraient la même signature. Le calendrier des détachements est en
  base ; celui des autres opérations ne l'est pas.
- Le **retournement à un mois**, qui survivait au balayage avant la
  correction de l'univers et arrive aujourd'hui juste sous le seuil,
  est-il un artefact de détachement ? Un dividende fait chuter le cours
  mécaniquement, et « baisse puis reprise » est exactement la forme du
  signal.

### Pourquoi il n'y a pas de modèle par secteur

**À ne pas confondre avec la comparaison à secteur égal**, que la section 4
décrit et que le projet fait désormais. Employer le secteur comme
**repère** — comparer chaque valeur à la moyenne des siennes — ne coûte
rien et enlève un biais. Employer le secteur comme **échantillon
d'apprentissage** est une autre affaire, et c'est celle-là qui reste
impossible : le secteur médian ne compte que **4 valeurs cotées par
séance**, le premier quartile 2. On ne règle pas un modèle sur deux
valeurs, et c'est exactement pourquoi la comparaison retranche une moyenne
au lieu de ranger à l'intérieur du secteur.

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
- **Agro-industrie** (SAPH, SOGB, Palmci, Sucrivoire) — on attendait ici
  le meilleur pouvoir prédictif, parce qu'il existe un moteur **extérieur**
  au marché : le prix du caoutchouc, de l'huile de palme, du sucre. Ces
  cours ont été trouvés (les prix mensuels de la Banque mondiale) et
  mesurés : ils n'améliorent pas le modèle de prix à cinq séances. Le seul
  lien visible — le dernier mois de l'huile de palme devant Palm CI et
  SOGB — vit dans la première moitié de l'archive et disparaît dans la
  seconde. Détail dans `src/brvm/exogene.py`.

Un détail qui a son importance : le prix du caoutchouc à une date donnée
est **le même pour les 47 sociétés**. Versé tel quel dans un modèle de
classement, il ne distingue aucune valeur et l'IC ne bougerait pas — on
conclurait à tort que les commodités n'expliquent rien. La variable utile
est son produit avec l'**exposition de la valeur** — le caoutchouc pour
SAPH et SOGB. Pas avec son secteur : le modèle compare chaque valeur à son
secteur, et une série versée à tout un secteur s'y annule. C'était la
forme d'origine, et elle n'aurait rien pu montrer.

---

## Tests, configuration, licence

### Tests

```bash
pytest -q                     # ou : python tests/test_brvm_org.py
```

**Tous les tests tournent hors ligne.** Un test qui dépend du réseau échoue pour
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
