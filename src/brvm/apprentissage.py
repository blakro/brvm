"""Le cœur appris de la prédiction : poids, ensemble, combinaison, calibrage.

`prediction.py` pose la question et juge la réponse ; ce module fabrique la
réponse. La séparation n'est pas décorative — elle permet de mesurer chaque
brique contre les autres, et c'est en les mesurant qu'on a découvert que
quatre des recettes usuelles de la fiabilité — l'ensemble, l'empilement, la
sélection de traits, les modèles à arbres — ne fonctionnent pas ici, et
pourquoi.

CE QUI A ÉTÉ MESURÉ, ET CE QUI A ÉTÉ JETÉ
-----------------------------------------
Tous les chiffres du tableau ci-dessous viennent du MÊME protocole :
validation glissante à dix découpes sur l'archive complète (2015-2026,
47 valeurs, environ 101 000 observations), étiquettes recouvrantes purgées,
erreur-type conservatrice de `mesure_ic`, **à l'horizon de soixante séances
qui était alors celui du projet**. Citer deux protocoles reviendrait à
choisir le plus flatteur sans le dire — d'où la mention de l'horizon, qui
vaut aujourd'hui cinq séances et déplace tous ces chiffres.

L'IR est l'IC moyen divisé par son écart-type d'une période à l'autre :
c'est LUI qui mesure la fiabilité, là où l'IC seul mesure l'ampleur.

    alors    trois sources équipondérées        IC +0,045  IR 0,51  7/10
    RETENU   régression logistique seule        IC +0,044  IR 0,66  7/10
    ---
    rejeté   moyenne des 8 membres du sac       IC +0,037  IR 0,59  7/10
    rejeté   sac sur profondeurs d'historique   IC +0,036  IR 0,42  7/10
    rejeté   empilement à poids appris          IC +0,036  IR 0,51  6/10
    rejeté   crête adaptative par la preuve     IC +0,037  IR 0,46  6/10
    rejeté   poids de fiabilité seuls           IC +0,028  IR 0,32  6/10
    rejeté   composite de la configuration      IC +0,032  IR 0,30  5/10

SUR L'IC, ELLES NE SE DÉPARTAGENT PAS — ET CE N'ÉTAIT PAS LA BONNE MESURE.
+0,045 contre +0,044, l'IR penchant dans l'autre sens : sur dix périodes,
l'écart entre un IR de 0,51 et un de 0,66 n'est pas mesurable. La
combinaison a donc été livrée d'abord, pour trois raisons indépendantes de
ces décimales : meilleur IC, jamais la pire des trois sources quand l'une se
trompe (période 2022-09 : régression -0,009, fiabilité -0,054, composite
+0,238, combinaison +0,085), et un classement rendu même sans scikit-learn.

CE QUI A RENVERSÉ LE VERDICT : LA MESURE, PAS LES DÉCIMALES. L'IC note
l'ordre de toute la cote ; un porteur n'achète que le haut, et seulement ce
qui est assez échangé pour qu'un ordre passe. Jugées sur l'avantage des dix
premières valeurs ACHETABLES — voir `avantage_par_date` — les deux ne sont
plus du tout à égalité, et la régression seule gagne aux trois horizons
essayés, sur la première moitié de l'archive comme sur la seconde :

    horizon   régression seule   moyennée avec les poids de fiabilité
         10           +10,95 %                             +9,93 %
         20            +7,72 %                             +5,79 %
         40            +4,13 %                             +2,09 %

Le composite, lui, a un avantage du haut de liste NÉGATIF (-0,10 % par
période) pour un IC positif : il ordonne honorablement le ventre du marché
et dégrade les dix lignes qu'on achète.

Les deux vertus qui avaient fait pencher pour la combinaison sont
conservées autrement. `prediction.SOURCES_COMBINEES` est devenue un ORDRE de
préférence et non une moyenne : sans scikit-learn, les poids de fiabilité
prennent la suite et rendent encore un classement appris (+13,5 % annualisés
contre +15,5 % pour la régression, à l'horizon livré). Et la protection contre la période où une source se
trompe est désormais assurée par la porte de production de `valider`, qui
refuse le modèle si son haut de liste a perdu hors échantillon — une
garantie mesurée plutôt qu'un effet de moyenne.

1. L'EMPILEMENT À POIDS APPRIS ÉCHOUE, ET L'ÉCHEC EST INSTRUCTIF. Estimer
   par validation imbriquée le poids à donner à chaque source — la méthode
   correcte, celle qu'on enseigne — rend IC +0,036 contre +0,045 pour trois
   poids égaux décidés d'avance. La raison tient en un nombre : onze ans à
   l'horizon de soixante séances font QUARANTE-DEUX périodes réellement
   indépendantes. On n'apprend pas des poids de combinaison sur quarante-
   deux points ; on y apprend le bruit de la fenêtre d'entraînement. Quand
   la preuve est mince, répartir bat choisir.

2. LE SAC N'AMÉLIORE PAS LA PRÉCISION. Moyenner ses huit membres rend
   +0,037 là où le membre unique entraîné sur tout rend +0,044 : non
   seulement le sac n'aide pas, il coûte. Six coefficients sur cent mille
   lignes, c'est déjà un estimateur à faible variance, et il n'y avait pas
   de variance à réduire.

   Le sac est pourtant conservé. PAS POUR LA PRÉCISION — pour
   l'incertitude : la dispersion entre ses membres est le seul moyen
   honnête de dire qu'une probabilité de 53 % vaut « 53 % ± 3 » et non
   « 53 % ». Un chiffre sans sa marge se cite tout seul, et c'est ainsi
   qu'il finit par tromper. La probabilité affichée reste celle du membre
   central, mesurée ci-dessus ; le sac ne fournit que la barre d'erreur.

3. SÉLECTIONNER LES TRAITS SUR LA PREUVE D'ENTRAÎNEMENT ÉCHOUE AUSSI, ET
   C'EST LE PIÈGE LE PLUS TENTANT DU PROJET. En retirant après coup les
   trois traits qui n'ont rien porté — momentum, tendance, liquidité — on
   lit IC +0,076 et IR 0,96, le double du modèle livré. Ce nombre n'existe
   pas : il suppose de connaître d'avance lesquels retirer.

   Toutes les façons honnêtes de faire ce choix ont été essayées, et
   aucune n'y arrive. La crête adaptative — standardiser les traits puis
   les mettre à l'échelle de leur preuve mesurée sur la seule fenêtre
   d'entraînement — rend entre +0,033 et +0,037 selon l'exigence, soit
   MOINS que la régression qui ne sélectionne rien. Les facteurs estimés
   sur l'entraînement ne désignent pas les bons traits assez souvent :
   au dernier pli ils donnent 0,47 au choc de volume mais aussi 0,42 à la
   volatilité et 0,19 au momentum.

   Retenir : +0,076 est ce que le recul offre, +0,044 ce que l'honnêteté
   permet, et l'écart entre les deux est la mesure exacte de ce qu'un
   backtest gagne à tricher.

4. LES POIDS DE FIABILITÉ, EUX, FONCTIONNENT — À CONDITION D'ÊTRE
   RÉTRÉCIS, et à condition de servir de SOURCE et non de sélecteur. Voir
   `poids_fiabilite`.

NI FORÊT, NI GRADIENT BOOSTING — ET C'EST MESURÉ, PAS ARGUMENTÉ
---------------------------------------------------------------
Cette section affirmait qu'un modèle souple surajusterait ici. Un argument
n'est pas une mesure, et celui-là est le plus facile à contester : « vous
n'avez pas essayé ». Essayé, donc, sous le protocole ci-dessus, du plus
bridé au plus libre :

    régression logistique (livrée)      IC +0,0437   IR 0,66   7/10
    ---
    GBM défauts                         IC +0,0309   IR 0,46   6/10
    GBM modéré                          IC +0,0302   IR 0,52   7/10
    GBM libre                           IC +0,0295   IR 0,45   6/10
    GBM bridé                           IC +0,0280   IR 0,45   6/10
    GBM très bridé                      IC +0,0276   IR 0,35   6/10
    forêt bridée                        IC +0,0299   IR 0,37   6/10
    forêt modérée                       IC +0,0265   IR 0,37   6/10
    forêt libre                         IC +0,0197   IR 0,32   6/10

Aucune des huit configurations n'approche la régression, ni en IC ni en IR.
La conclusion ne demande même pas de se méfier du choix d'hyperparamètres :
quand la MEILLEURE case d'un balayage perd de 29 %, il n'y a pas de case à
cueillir. Et la forêt la moins bridée est la plus mauvaise des huit, ce qui
est la signature du surajustement plutôt que du hasard.

POURQUOI, ET C'EST LA PARTIE UTILE. Un arbre n'apporte rien sur une
transformation monotone — les traits sont déjà des rangs centiles, qui en
sont une. Son seul avantage possible est de capter ce qu'une somme pondérée
ne peut pas : une interaction (« le choc de volume ne paie que quand la
volatilité est basse ») ou une non-monotonie. On a donc cherché ces effets
directement, en les donnant à la régression sous forme lisible :

    traits seuls (livré)                IC +0,0437   IR 0,66
    + 15 produits croisés               IC +0,0456   IR 0,62
    + carrés (non-monotonie)            IC +0,0448   IR 0,76
    + croisés ET carrés                 IC +0,0484   IR 0,69

Tout tient dans une bande de 0,005, contre une erreur-type de 0,03. Il n'y
a pas d'interaction à trouver : l'arbre n'est pas battu parce qu'il est mal
réglé, il est battu parce qu'il paie une variance pour chercher quelque
chose qui n'est pas là.

RESTAIT UNE AVENUE : un modèle médiocre seul peut valoir dans un mélange
s'il se trompe ailleurs que les autres. La condition est remplie — la
corrélation de rang entre le GBM et la régression n'est que de 0,37 — et
pourtant l'ajouter en quatrième source ne change rien :

    3 sources (livrée)                  IC +0,0453   IR 0,51   pire -0,094
    4 sources, avec GBM                 IC +0,0451   IR 0,53   pire -0,070

La pire période s'adoucit de deux points et demi, et c'est le seul gain
candidat. Il repose sur UN nombre tiré de dix périodes, là où l'IC ne bouge
pas et l'IR bouge dans le bruit. Ce n'est pas assez pour ajouter une
dépendance, quatre secondes de calcul par ajustement et un mode de panne.

Et la puissance n'a jamais été ce qui manquait : la même régression
logistique, sur l'univers non corrigé et les quatre traits d'origine, rend
un IC de -0,056. Ce n'est pas son manque de souplesse qui l'en empêchait,
ce sont ses données et ses entrées. Le risque ici n'est pas de manquer de
puissance, il est d'en avoir trop.

NI PROPHET, NI LA MOYENNE MOBILE QU'IL CACHAIT
----------------------------------------------
La question revient dès qu'on parle de prévision de cours : « et Prophet ? ».
Mesuré, à l'horizon livré de cinq séances. Prophet 1.4 à ses réglages par
défaut, ajusté valeur par valeur sur le logarithme des 750 dernières
clôtures ÉCHANGÉES jusqu'à t — jamais au-delà —, saisonnalités hebdomadaire
et annuelle, projeté à t+5.
Une date sur cinq, pour que les étiquettes ne se recouvrent pas : 506 dates,
19 398 ajustements, trente et une minutes sur quatre cœurs. Chaque score est
comparé au modèle livré sur les MÊMES lignes hors échantillon de `valider`.

COMME PRÉVISION DE COURS, IL FAIT PIRE QUE NE RIEN PRÉVOIR. Son erreur
absolue à cinq séances dépasse de 79 % celle de « le cours ne bouge pas »,
et il ne devine le sens que 53,1 % du temps. Il projette une tendance et
des saisons sur des cours de fixing dont 12 % ne bougent pas du tout en une
semaine.

COMME CLASSEMENT, UN SEUL DE SES MORCEAUX PORTE QUELQUE CHOSE :

                                        IC    avantage des 10 premières
    modèle livré                    +0,076    +13,0 % l'an
    Prophet, prévision complète     +0,073    +12,5 %
    Prophet, tendance seule         +0,000     -6,0 %
    Prophet, saisonnalité seule     +0,009     +0,2 %
    Prophet, écart cours - courbe   +0,088    +16,2 %
    écart à la moyenne 20 séances   +0,102    +19,6 %

La tendance et la saison, qui sont la raison d'être de Prophet, ne valent
rien ici — la saison confirme au passage ce que `prediction` avait mesuré
sur le calendrier. Le morceau utile est l'écart entre le cours et la courbe
ajustée, c'est-à-dire un retour vers la moyenne, et une moyenne mobile d'une
ligne de pandas le capte MIEUX, en millisecondes. Donnés comme traits à la
régression, sur les mêmes dates :

                                      IC    haut de liste
    livré                         +0,078       +10,2 %
    + Prophet                     +0,086       +14,3 %
    + moyenne mobile 20           +0,102       +16,5 %
    + moyenne mobile + Prophet    +0,100       +18,3 %

(Le modèle n'apprend ici que sur ces dates, une sur cinq : les niveaux ne se
comparent qu'à l'intérieur du tableau. C'est l'archive complète, plus bas,
qui juge la moyenne mobile elle-même.)

La moyenne mobile présente, Prophet n'ajoute rien de mesurable : écart
apparié de -0,001 d'IC (t -0,5) et de +1,8 point au haut de liste (t +1,1).
Ce qu'il voit encore au-delà de quatre moyennes mobiles et des traits du
modèle vaut un IC de +0,018. Ce n'est pas de quoi payer une dépendance
lourde, et une validation qui demanderait près de 97 000 ajustements là où
l'app tient en quinze secondes.

LA MOYENNE MOBILE, ELLE, VA PLUS LOIN — ET TOMBE AU CONTRÔLE QUE PASSE LE
MODÈLE LIVRÉ. Tout ce qui suit est jugé sur le COURS SEUL, comme la section
« Le modèle de prix » du README : ni frais, ni dividende, ni rejeu.

1. LE TEST MULTIPLE. Ajoutée à la grille de `recherche.py` (390 cases),
   « cours rapporté à sa moyenne de 20 séances » en devient la case la
   PLUS forte : IC -0,078 et t -9,6 à cinq séances sur tout le marché,
   devant le choc éclair (+7,2). Onze de ses trente cases franchissent la
   correction, et aucune survivante existante ne perd sa place. Elle est
   corrélée à -0,78 avec le retournement à un mois : c'est le même effet,
   mesuré en pesant davantage les toutes dernières séances.

2. LE PROTOCOLE DE PRODUCTION. Dixième trait de la régression, dix
   découpes, archive complète, écarts appariés à la version livrée :

                            livré    + moyenne 20    écart apparié
        IC                 +0,077        +0,098      +0,021  t +4,2
        IR                   1,86          1,83
        pire période       +0,018        +0,005
        haut de liste     +16,1 %       +18,2 %      +2,1 pts  t +0,8
          1re moitié      +12,4 %       +16,0 %
          2nde moitié     +18,9 %       +19,9 %

   L'ordre de toute la cote s'améliore nettement. Le haut de liste, lui,
   gagne deux points que rien ne distingue du hasard, sans que l'IR ni la
   pire période ne suivent. La règle des moitiés du projet l'aurait pourtant
   laissé passer — elle choisit 20 séances sur la première (16,0 contre 12,6
   à 10 séances et 10,8 à 5) et la seconde confirme d'un point. C'est le
   contrôle suivant qui tranche.

   Deux autres contrôles de la section « Le modèle de prix » ne l'arrêtent
   pas. Sur les seules sorties réellement traitées, l'écart tient (IC
   +0,079 -> +0,101). Par tercile de niveau de cours il reste positif
   partout, mais décroît avec le cours (+0,037, +0,028, +0,015) : il est le
   plus fort là où un pas de cotation pèse le plus.

3. L'ENTRÉE DÉCALÉE — le contrôle dont le README dit qu'« un effet de
   rebond de fourchette se serait effondré dès la première » séance. Même
   méthode que son tableau : pour chaque délai k, le modèle est RÉENTRAÎNÉ
   sur le rendement de t+k à t+k+5.

                      t+0       t+1       t+2       t+3
        livré      +16,1 %   +12,3 %    +9,6 %    +7,5 %
        + moyenne  +18,2 %   +11,6 %    +8,7 %    +4,8 %
        écart IC   +0,021    +0,005    +0,005    +0,003
            (t)      +4,2      +1,8      +1,6      +0,9

   Le modèle livré passe ce contrôle : son avantage survit à trois séances
   de retard. Le supplément de la moyenne mobile, lui, s'effondre dès la
   première — les trois quarts de son gain d'IC disparaissent, le reste
   n'est plus significatif, et le haut de liste passe sous celui du modèle
   livré. Ce qu'elle ajoute se joue dans la séance qui suit la clôture :
   c'est la signature que ce contrôle existe pour détecter — un fixing qui
   déborde et se résorbe au suivant — plutôt qu'un mouvement de cours
   durable.

Elle n'entre donc ni dans le modèle ni dans la grille de `recherche.py`,
dont la règle vise les traits qu'emploie la prédiction. La mesure est
consignée ici pour qu'on ne la refasse pas — ou, si on la refait, pour
qu'on la passe à l'entrée décalée dès le premier essai.

TREIZE AUTRES ESSAIS, ET UN PLAFOND
-----------------------------------
Ensuite, treize variantes du modèle de PRIX, déclarées avant d'être
mesurées, par trois tours. Le banc d'essai réécrit la validation de
`prediction.valider` et en reproduit les chiffres à l'identique (IC
+0,0771, haut de liste +16,1 %) : seul ce qu'on y change diffère. Écarts
appariés à la version livrée, haut de liste en points par an :

                                           écart d'IC      haut de liste
                                                  (t)        (t)  1re  2nde
    L'ÉTIQUETTE
    lissée sur 5, 10 et 20 séances      -0,0002 (-0,1)  -0,2 (-0,1) +0,9 -0,9
    extrêmes seuls (30 % de chaque côté) +0,0012 (+0,6)  -0,1 (-0,1) +2,1 -1,8
    continue, par régression ridge       +0,0010 (+0,6)  -0,2 (-0,1) +1,1 -1,1
    sorties réellement traitées seules   -0,0003 (-0,2)  +0,2 (+0,2) +0,4 -0,1
    L'APPRENTISSAGE
    récence, demi-vie de deux ans        -0,0004 (-0,2)  -1,4 (-1,0) -0,0 -2,5
    trois modèles, à 5, 10 et 20 séances -0,0008 (-0,4)  -0,1 (-0,1) +0,9 -0,9
    deux niveaux, secteur et marché      +0,0012 (+0,3)  -1,4 (-0,7) -2,0 -1,0
    score moyenné sur cinq séances       -0,0297 (-6,5)  -6,0 (-2,6) -3,5 -7,9
    DE L'INFORMATION NOUVELLE
    pression acheteuse (volume signé)    +0,0005 (+0,2)  +0,2 (+0,1) +2,4 -1,4
      la même + extrêmes seuls           +0,0014 (+0,4)  +0,2 (+0,1) +3,3 -2,2
    butées (variation d'au moins 7 %)    +0,0001 (+0,0)  +0,4 (+0,5) +1,0 -0,0
    position de la clôture dans le jour  +0,0037 (+1,6)  +0,2 (+0,1) +0,8 -0,3
    attention qui monte ou retombe       -0,0000 (-0,1)  -0,0 (-0,0) +1,0 -0,8

(Les butées sont comptées à 7 % et non 7,5 : l'arrondi au pas de cotation
empêche souvent d'atteindre la limite exacte.)

AUCUN |t| N'ATTEINT 2, sauf pour une perte. Et les dix variantes qui
gagnent sur la première moitié perdent toutes sur la seconde. Ce n'est pas
une malédiction, c'est de l'arithmétique : quand l'écart total est nul, un
gain sur une moitié impose une perte sur l'autre. La règle des moitiés les
arrête toutes, et c'est précisément son rôle.

Trois constats, plus utiles que le tableau :

1. LA LIMITE DE ±7,5 % NE PRODUIT PAS DE CONTINUATION. Sur d'autres places
   à limite de prix, une valeur qui touche la butée a tendance à
   poursuivre ; ici elle se RETOURNE (IC seul -0,026), comme une clôture
   en haut de la fourchette du jour (-0,056). Le trait de retournement du
   modèle porte déjà cette information : ajoutée, elle ne déplace rien.

2. L'INFORMATION DU MODÈLE EST FRAÎCHE. Moyenner son score sur cinq
   séances coûte près de 40 % de l'IC. Ce que le modèle sait, il le sait le jour
   même ; c'est aussi pourquoi l'entrée décalée lui coûte.

3. LE PLAFOND EST DANS LES DONNÉES, PAS DANS LE MODÈLE. Étiquette,
   pondération, forme du modèle, structure, et quatre traits tirés du
   cours, du volume et de la fourchette : rien ne bouge. Avec neuf traits
   déjà construits sur ces mêmes séries, le prochain gain, s'il existe,
   viendra d'une source que l'archive n'a pas encore.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# scikit-learn reste optionnelle, et le module s'importe sans elle — voir
# l'en-tête de `prediction.py`. Tout ce qui suit sauf `Ensemble` est du
# pandas, y compris les poids de fiabilité : l'absence de la bibliothèque
# coûte la régression logistique, pas la combinaison.
try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    DISPONIBLE = True
except ImportError:  # pragma: no cover — dépend de l'environnement
    DISPONIBLE = False


# --- mesure ---------------------------------------------------------------

def ic_par_date(bloc: pd.DataFrame, colonne: str,
                cible: str = "rendement_futur") -> pd.Series:
    """IC de Spearman séance par séance, vectorisé.

    La version naïve — `groupby("date").apply(corr)` — coûtait quarante
    secondes par comparaison de stratégies, ce qui suffisait à décourager
    de mesurer. Or c'est en mesurant qu'on a jeté l'empilement et le sac ;
    une mesure trop lente pour être répétée est une mesure qu'on ne fait
    pas.

    Le calcul est le même : rangs dans la séance, puis corrélation de
    Pearson sur ces rangs — soit Spearman, exprimé en sommes que pandas
    agrège d'un bloc.
    """
    besoin = ["date", colonne, cible]
    if bloc.empty or any(c not in bloc.columns for c in besoin):
        return pd.Series(dtype=float)
    d = bloc[besoin].dropna()
    if d.empty:
        return pd.Series(dtype=float)

    par_date = d.groupby("date")
    x = par_date[colonne].rank()
    y = par_date[cible].rank()
    dx = x - x.groupby(d["date"]).transform("mean")
    dy = y - y.groupby(d["date"]).transform("mean")
    numerateur = (dx * dy).groupby(d["date"]).sum()
    denominateur = np.sqrt((dx * dx).groupby(d["date"]).sum()
                           * (dy * dy).groupby(d["date"]).sum())
    # Moins de trois valeurs cotées : une corrélation de rang n'y veut rien
    # dire, et vaudrait mécaniquement ±1.
    return (numerateur / denominateur.replace(0.0, np.nan)).where(
        par_date.size() >= 3).dropna()


def mesure_ic(ics: pd.Series, horizon: int) -> dict:
    """IC moyen, erreur-type conservatrice, t, verdict.

    L'erreur-type ne se calcule pas sur le nombre de dates mais sur le
    nombre de périodes RÉELLEMENT disjointes, `dates / horizon` : à
    l'horizon de vingt séances que le projet emploie, l'étiquette du lundi
    recouvre celle du mardi à 19/20. C'est le piège qui avait fait passer un IC de -0,07 pour un t de
    -10,2 alors qu'il vaut -1,4.

    DEUX ESTIMATEURS SONT POSSIBLES, ET LE PLUS PRUDENT EST RETENU. On peut
    diviser par racine de K (le nombre de blocs) soit l'écart-type des IC
    QUOTIDIENS, soit celui des MOYENNES par bloc. Le second est le
    traitement usuel d'une série à dépendance bornée, et il est moins
    exigeant : mesuré sur l'archive, l'écart-type quotidien du choc de
    volume vaut 0,190 et celui de ses moyennes par bloc 0,102, si bien que
    le t passe de +2,2 à +4,2 selon l'estimateur choisi.

    C'est le premier qui est retenu, comme depuis l'origine du module. Le
    recouvrement des étiquettes n'annule pas toute l'information d'une date
    sur l'autre, mais on cherche ici un signal qui n'existe probablement
    pas — et quand on cherche ce qui n'existe probablement pas, mieux vaut
    se tromper du côté qui n'annonce rien. Un lecteur qui préfère l'autre
    estimateur peut doubler tous les t de ce module ; aucune conclusion du
    projet n'en dépend, et celles qui en dépendraient seraient justement
    celles qu'il ne faut pas tirer.
    """
    vide = {"ic": float("nan"), "erreur_type": float("nan"), "t": float("nan"),
            "dates": 0, "blocs": 0, "significatif": False}
    valeurs = np.asarray(pd.Series(ics).dropna(), dtype=float)
    if len(valeurs) == 0:
        return vide
    moyenne = float(valeurs.mean())
    blocs = max(1, int(np.ceil(len(valeurs) / max(1, horizon))))
    if len(valeurs) < 2 or blocs < 2:
        return {**vide, "ic": moyenne, "dates": len(valeurs), "blocs": blocs}

    erreur = float(valeurs.std(ddof=1) / np.sqrt(blocs))
    t = float(moyenne / erreur) if erreur > 0 else float("nan")
    return {
        "ic": moyenne,
        "erreur_type": erreur,
        "t": t,
        "dates": len(valeurs),
        "blocs": blocs,
        # Deux erreurs-types : le seuil usuel, et il n'est pas atteint par
        # grand-chose sur ce marché.
        "significatif": bool(erreur > 0 and abs(t) > 2),
    }


def avantage_par_date(bloc: pd.DataFrame, colonne: str,
                      positions: int = 10,
                      liquidite_min: float | None = None) -> pd.Series:
    """Par séance : rendement moyen des `positions` premiers moins la séance.

    POURQUOI CE SECOND CHIFFRE EXISTE À CÔTÉ DE L'IC. L'IC note l'ordre de
    TOUTE la cote ; un utilisateur n'achète que le haut. Les deux peuvent
    aller en sens contraire, et pas en théorie — mesuré sur cette archive,
    à l'horizon de production et sans neutralisation sectorielle :

        IC de la combinaison            +0,045  (positif)
        avantage des 10 premiers        -0,67 % (négatif)

    Un classement peut donc mieux ranger le ventre du marché — ce qui lève
    l'IC — en rangeant plus mal les dix valeurs qui sont les seules que
    quiconque achètera. Un tableau de bord qui n'affiche que l'IC présente
    alors une amélioration là où l'utilisateur perd de l'argent.

    Le repère est la moyenne de la séance et non la médiane : c'est ce que
    rapporterait l'univers acheté à poids égaux, c'est-à-dire l'alternative
    réelle à suivre le classement.

    `liquidite_min` RESTREINT AUX VALEURS ACHETABLES, et ce n'est pas un
    détail de présentation. Mesuré sur l'archive, 40 % des lignes de
    l'échantillon n'atteignent pas le seuil de volume que `scoring` exige, et
    l'avantage du haut de liste y est près du double de ce qu'il est sur les
    lignes négociables : +13,8 % contre +7,7 % annualisés à vingt séances.
    Un chiffre qui compte les valeurs qu'on ne peut pas acheter annonce un
    gain que personne ne touchera. Le classement et le repère se calculent
    alors tous deux sur les seules lignes retenues, comme le fait le
    backtest.
    """
    if bloc.empty or colonne not in bloc.columns:
        return pd.Series(dtype=float)
    if liquidite_min is not None and "liquidite_fcfa" in bloc.columns:
        bloc = bloc[bloc["liquidite_fcfa"] >= float(liquidite_min)]
        if bloc.empty:
            return pd.Series(dtype=float)
    n = max(1, int(positions))

    # VECTORISÉ, ET CE N'EST PAS DE LA COQUETTERIE. La version en boucle
    # `for date, tranche in bloc.groupby("date")` coûtait 4 secondes par
    # appel sur onze ans d'archive, et `valider` en fait dix — quatre
    # sources fois deux seuils, plus la source retenue. Elle portait donc à
    # elle seule 41 des 46 secondes de la validation, que l'app paie à
    # chaque calcul. C'est exactement le coût que l'en-tête de
    # `features.traits_glissants` raconte avoir déjà payé une fois.
    #
    # Le classement décroissant en `method="first"` reproduit `nlargest`,
    # qui départage les ex æquo par l'ordre d'apparition ; les scores
    # manquants reçoivent un rang manquant et tombent donc hors du haut de
    # liste, comme `nlargest` les écartait.
    scores = bloc[colonne]
    rangs = scores.groupby(bloc["date"]).rank(ascending=False, method="first")
    rendement = bloc["rendement_futur"]
    par_date = rendement.groupby(bloc["date"])
    haut = rendement.where(rangs <= n).groupby(bloc["date"]).mean()

    # Il faut de quoi distinguer un haut de liste d'un univers : avec douze
    # valeurs cotées, « les dix premières » est presque l'univers entier et
    # l'écart ne veut plus rien dire.
    assez = scores.notna().groupby(bloc["date"]).sum() >= n + 2
    ecart = (haut - par_date.mean())[assez]
    return ecart.dropna().astype(float).sort_index()


def mesure_avantage(bloc: pd.DataFrame, colonne: str, horizon: int,
                    positions: int = 10,
                    liquidite_min: float | None = None) -> dict:
    """`avantage_par_date` agrégé, même estimateur prudent que `mesure_ic`.

    Les clés reprennent celles de `mesure_ic` à ceci près que `ic` s'appelle
    `avantage` et se lit en rendement, non en corrélation : c'est un écart
    de rendement sur la durée de détention, directement comparable aux
    frais d'un aller-retour.
    """
    brut = mesure_ic(
        avantage_par_date(bloc, colonne, positions, liquidite_min), horizon)
    avantage = brut.pop("ic")
    return {**brut, "avantage": avantage, "positions": int(positions),
            "liquidite_min": (None if liquidite_min is None
                              else float(liquidite_min))}


# --- sources de score -----------------------------------------------------

def score_composite(bloc: pd.DataFrame, poids: dict) -> pd.Series:
    """La référence sans apprentissage : somme pondérée des rangs.

    Ce sont les poids écrits dans la configuration, ceux de `scoring.py`.
    Rien n'y est estimé, donc rien n'y surajuste — et sur ce marché c'est
    une qualité rare : mesuré seul, le composite rend IC +0,053 et IR
    0,63, soit davantage que la régression libre.
    """
    utiles = {t: p for t, p in poids.items() if t in bloc.columns}
    if not utiles:
        return pd.Series(0.5, index=bloc.index)
    total = sum(abs(p) for p in utiles.values()) or 1.0
    return sum(p * bloc[t] for t, p in utiles.items()) / total


def poids_fiabilite(echantillon: pd.DataFrame, traits: list[str],
                    horizon: int, exigence: float = 4.0) -> dict[str, float]:
    """Poids de chaque trait = son IC, rétréci par la force de sa preuve.

    LE PROBLÈME QU'ILS RÉSOLVENT. Une régression logistique donne un
    coefficient à chaque trait, y compris à ceux qui ne portent rien. Sur
    cette archive, le momentum et la tendance changent de signe d'une année
    à l'autre ; la régression leur attribue pourtant le poids que leur donne
    la fenêtre d'entraînement, et le porte en production.

    LA RÈGLE. Pour chaque trait on mesure son IC sur la fenêtre
    d'entraînement, et le t de cet IC sur blocs disjoints. Le poids vaut

        w = IC × t² / (t² + exigence)

    C'est un rétrécissement à la James-Stein. Un trait sans preuve (t ≈ 0)
    reçoit un poids nul quelle que soit la taille de son IC ; un trait
    avéré (t grand) garde le sien. Le facteur vaut la moitié quand t² égale
    `exigence` — à 4, la moitié du poids est accordée à t = 2, soit
    exactement le seuil usuel de signification.

    CE QUE ÇA DONNE, sur l'échantillon complet :

        choc_volume    +0,0358      retournement   -0,0122
        volatilite     -0,0105      momentum       +0,0013
        tendance       +0,0003      liquidite      -0,0001

    Le rétrécissement a fait son travail : le momentum, la tendance et la
    liquidité sont à zéro à la troisième décimale, et le poids s'est
    concentré sur le seul trait dont la preuve tienne. Ce sont précisément
    les traits que le projet mettait en avant depuis le début qui
    disparaissent. C'est désagréable à lire et c'est le but.

    (Les poids affichés par la validation diffèrent de ceux-ci : ils sont
    estimés sur la seule fenêtre d'entraînement du dernier pli, qui est
    plus courte. C'est voulu — un poids calculé sur l'échantillon entier
    connaîtrait la période de test.)

    `exigence` ne demande pas de réglage fin : balayée de 0,25 à 9 sur
    l'archive, elle déplace l'IC de la combinaison de +0,0440 à +0,0455.
    La valeur 4 est retenue parce qu'elle a un sens — demi-poids au seuil
    usuel t = 2 — et non parce qu'elle maximise quoi que ce soit.
    """
    poids: dict[str, float] = {}
    for trait in traits:
        if trait not in echantillon.columns:
            poids[trait] = 0.0
            continue
        mesure = mesure_ic(ic_par_date(echantillon, trait), horizon)
        t = mesure["t"]
        if not np.isfinite(t) or mesure["blocs"] < 2:
            poids[trait] = 0.0
            continue
        poids[trait] = float(mesure["ic"] * t * t / (t * t + exigence))
    return poids


def score_fiabilite(bloc: pd.DataFrame, poids: dict[str, float]) -> pd.Series:
    """Somme des rangs pondérée par les poids de `poids_fiabilite`."""
    utiles = {t: p for t, p in poids.items()
              if t in bloc.columns and abs(p) > 1e-12}
    total = sum(abs(p) for p in utiles.values())
    if total < 1e-12:
        # Aucun trait n'a fait sa preuve : la source se tait plutôt que de
        # rendre un classement arbitraire. Un score constant a un IC non
        # défini, et `combiner` l'écarte.
        return pd.Series(np.nan, index=bloc.index)
    return sum(p * bloc[t] for t, p in utiles.items()) / total


# --- le modèle appris -----------------------------------------------------

class ApprentissageIndisponible(RuntimeError):
    """Levée quand on demande un modèle sans que scikit-learn soit là."""


class Ensemble:
    """Sac de régressions logistiques, rééchantillonnées PAR BLOCS DE DATES.

    L'unité de rééchantillonnage est la période de `horizon` séances, pas
    la ligne. Tirer des lignes au hasard reviendrait à tirer soixante fois
    la même information — l'étiquette du lundi et celle du mardi racontent
    la même histoire — et donnerait des membres quasi identiques, donc une
    dispersion nulle et une fausse certitude. En tirant des blocs, deux
    membres voient des régimes de marché différents, et leur désaccord dit
    quelque chose.

    Rappel de l'en-tête : le sac ne gagne PAS en précision (IC 0,0515
    contre 0,0515 pour une régression unique). Il est là pour la
    dispersion, qui devient la marge d'erreur affichée à côté de chaque
    probabilité. Le membre entraîné sur l'échantillon complet, lui, fournit
    la probabilité centrale — celle qu'on cite.
    """

    def __init__(self, traits: list[str], horizon: int, membres: int = 8,
                 regularisation: float = 0.1, graine: int = 0):
        if not DISPONIBLE:  # pragma: no cover — dépend de l'environnement
            raise ApprentissageIndisponible(
                "scikit-learn n'est pas installé dans cet environnement.")
        self.traits = list(traits)
        self.horizon = int(horizon)
        self.membres = int(membres)
        self.regularisation = float(regularisation)
        self.graine = int(graine)
        self.central = None
        self.sac: list = []

    def _neuf(self):
        # Régularisation forte et modèle linéaire : voir l'en-tête du
        # module. `max_iter` généreux parce qu'un avertissement de
        # convergence dans une app Streamlit n'est lu par personne.
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(C=self.regularisation, max_iter=2000),
        )

    def entrainer(self, echantillon: pd.DataFrame) -> "Ensemble":
        utiles = [t for t in self.traits if t in echantillon.columns]
        appris = echantillon.dropna(subset=utiles + ["cible"])
        if appris.empty or appris["cible"].nunique() < 2:
            self.central, self.sac = None, []
            return self
        self.traits = utiles
        self.central = self._neuf().fit(appris[utiles], appris["cible"])

        dates = np.array(sorted(appris["date"].unique()))
        blocs = np.array_split(dates, max(2, len(dates) // max(1, self.horizon)))
        rng = np.random.default_rng(self.graine)
        self.sac = []
        for _ in range(self.membres):
            tirage = rng.integers(0, len(blocs), len(blocs))
            gardees = set(np.concatenate([blocs[i] for i in tirage]))
            part = appris[appris["date"].isin(gardees)]
            if len(part) < 200 or part["cible"].nunique() < 2:
                continue
            self.sac.append(self._neuf().fit(part[utiles], part["cible"]))
        return self

    def probabilites(self, bloc: pd.DataFrame) -> pd.Series:
        """Probabilité centrale, celle du membre entraîné sur tout."""
        if self.central is None or bloc.empty:
            return pd.Series(np.nan, index=bloc.index)
        return pd.Series(
            self.central.predict_proba(bloc[self.traits])[:, 1],
            index=bloc.index)

    def dispersion(self, bloc: pd.DataFrame) -> pd.Series:
        """Écart-type des membres du sac, valeur par valeur.

        C'est une incertitude D'ESTIMATION — de combien la probabilité
        bougerait si l'historique avait été un autre tirage de périodes.
        Elle ne dit rien de l'incertitude du marché lui-même, qui est
        infiniment plus grande : une probabilité de 68 % ± 3 reste une
        probabilité de 68 %, c'est-à-dire presque un pile ou face.
        """
        if len(self.sac) < 2 or bloc.empty:
            return pd.Series(np.nan, index=bloc.index)
        tirages = np.column_stack(
            [m.predict_proba(bloc[self.traits])[:, 1] for m in self.sac])
        return pd.Series(tirages.std(axis=1, ddof=1), index=bloc.index)

    def coefficients(self) -> dict[str, float]:
        """Poids appris par le membre central, sur traits standardisés."""
        if self.central is None:
            return {}
        return dict(zip(self.traits,
                        self.central[-1].coef_[0].astype(float)))


# --- combinaison ----------------------------------------------------------

def combiner(sources: dict[str, pd.Series]) -> pd.Series:
    """Moyenne des RANGS des sources disponibles, à poids égaux.

    DEUX DÉCISIONS, TOUTES DEUX MESURÉES.

    Les rangs et non les valeurs : une probabilité vit dans [0,4 ; 0,6] et
    un score composite dans [0 ; 1]. Moyenner les valeurs brutes laisserait
    la source la plus étalée décider seule, sans que rien ne le montre.

    Les poids égaux et non appris : c'est le résultat le plus contre-
    intuitif du module. Une validation imbriquée qui estime le poids de
    chaque source rend un IR de 0,46 ; trois poids égaux, 0,81. Quarante-
    quatre périodes indépendantes ne suffisent pas à apprendre trois
    poids, et l'essayer coûte plus que ça ne rapporte.

    Une source qui se tait — `score_fiabilite` quand aucun trait n'a fait
    sa preuve, le modèle quand scikit-learn manque — est simplement absente
    du calcul. La combinaison dégrade, elle ne tombe pas.
    """
    utiles = {nom: serie for nom, serie in sources.items()
              if serie is not None and serie.notna().any()}
    if not utiles:
        return pd.Series(dtype=float)
    rangs = [serie.rank(pct=True) for serie in utiles.values()]
    return sum(rangs) / len(rangs)


class Calibrage:
    """Rang combiné → probabilité de surperformer, apprise HORS ÉCHANTILLON.

    POURQUOI CE N'EST PAS UN DÉTAIL. Le rang combiné est un nombre entre 0
    et 1 ; l'afficher tel quel comme « probabilité » serait un mensonge de
    présentation. La première valeur du classement aurait une probabilité
    de 100 % de surperformer, la dernière de 0 %, alors que l'IC mesuré
    autorise à peine à les séparer.

    Le calibrage apprend la relation vraie — combien de fois, réellement,
    une valeur de rang combiné 0,9 a-t-elle battu la médiane — sur les
    prédictions HORS ÉCHANTILLON de la validation glissante, jamais sur
    l'entraînement. D'où des probabilités resserrées autour de 50 %, entre
    45 % et 55 % le plus souvent. C'est laid sur un graphique et c'est la
    vérité : l'IC mesuré ne permet pas mieux.

    Sans scikit-learn, ou faute d'assez d'observations hors échantillon, le
    calibrage se déclare absent et `prediction` affiche le rang en le
    nommant rang.
    """

    def __init__(self):
        self.modele = None
        self.observations = 0

    def apprendre(self, scores: pd.Series, cibles: pd.Series) -> "Calibrage":
        if not DISPONIBLE:
            return self
        table = pd.DataFrame({"s": scores, "y": cibles}).dropna()
        if len(table) < 200 or table["y"].nunique() < 2:
            return self
        self.modele = LogisticRegression(C=1e6, max_iter=1000).fit(
            table[["s"]], table["y"])
        self.observations = len(table)
        return self

    @property
    def disponible(self) -> bool:
        return self.modele is not None

    def appliquer(self, scores: pd.Series) -> pd.Series:
        if self.modele is None:
            return pd.Series(np.nan, index=scores.index)
        propres = scores.fillna(scores.median())
        return pd.Series(
            self.modele.predict_proba(propres.to_frame("s"))[:, 1],
            index=scores.index)
