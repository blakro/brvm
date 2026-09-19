"""Traits calculés sur les séries de cours, en vue du scoring.

Rien ici ne décide d'acheter quoi que ce soit : ce module transforme une
table de cours en quelques nombres par valeur, et `scoring.py` les combine.

UN HISTORIQUE INSUFFISANT DONNE NaN, JAMAIS UNE APPROXIMATION. Calculer un
momentum « sur ce qu'on a » quand on a trois semaines produit un nombre qui
a l'air d'un momentum, se classe comme un momentum, et ne mesure rien. Les
fenêtres sont donc strictes : en deçà, la valeur sort du classement au lieu
d'y entrer au hasard.

UN JOUR SANS ÉCHANGE N'EST PAS UN HISTORIQUE MANQUANT, ET LES CONFONDRE
COÛTAIT LA MOITIÉ DU MARCHÉ
---------------------------------------------------------------------
Les deux phrases ci-dessus disent quand refuser de mesurer. Elles ne
disaient pas quoi faire d'une séance où le titre n'a simplement pas été
échangé — et le pivot des cours, lui, y mettait un trou.

Un trou dans une moyenne mobile de 100 séances suffit à la rendre
incalculable : `rolling(100)` exige par défaut cent valeurs CONSÉCUTIVES.
UNLC n'échange qu'une séance sur deux ; elle n'en a jamais cent d'affilée,
et n'avait donc jamais de tendance, jamais de rang, jamais de place dans
l'échantillon d'apprentissage. Mesuré sur l'archive : la tendance n'était
calculable que pour 16,2 valeurs par séance sur les 37,7 cotées. Après
correction, pour 41,8.

C'était un biais de sélection, et le pire qui soit ici — il retirait
exactement la moitié illiquide du marché, celle dont le comportement
diffère le plus. Deux corrections, l'une et l'autre nécessaires :

1. LE DERNIER COURS CONNU EST REPORTÉ, au plus `report_max_seances`
   séances. Sur une place qui cote par fixing, un titre non échangé garde
   la valeur de son dernier échange — c'est la convention de valorisation
   de n'importe quel portefeuille. Au-delà de la limite, le cours est
   périmé et la valeur ressort du classement. Le report ne remonte jamais
   le temps, si bien qu'une société introduite en 2021 n'a pas de cours en
   2019 ; et la limite suffit à faire disparaître une société radiée, sans
   qu'on ait eu besoin de savoir d'avance qu'elle allait l'être — voir
   `cours_reportes`, qui explique pourquoi la borne que l'on serait tenté
   d'ajouter à l'autre bout serait un regard en avant.

2. LES FENÊTRES EXIGENT UN NOMBRE D'OBSERVATIONS, PAS UNE SUITE
   ININTERROMPUE (`min_periods`). Une moyenne à 100 séances calculée sur
   60 cotations reste une moyenne à 100 séances ; l'exiger sur 100
   cotations consécutives ne mesurait pas mieux, cela mesurait moins
   souvent.

Ensemble, elles portent l'échantillon de prédiction de 40 131 à 100 961
lignes et l'univers mesuré de 25,9 à 37,1 valeurs par séance, et font
tomber l'écart-type de l'IC d'une période de test à l'autre de 0,152 à
0,104. C'est le gain de fiabilité le plus important du projet, et il ne
doit rien à l'apprentissage : il vient d'avoir cessé de jeter les données.

ET IL A UN PRIX AFFICHÉ, QU'IL SERAIT MALHONNÊTE DE TAIRE. L'IC du score
composite BAISSE avec la correction, de +0,063 à +0,032. Le chiffre
d'avant n'était pas mérité : il se mesurait sur les seules valeurs cotant
cent séances d'affilée, c'est-à-dire sur un univers que personne n'aurait
pu choisir à l'avance autrement que par le même accident. On a vérifié
qu'aucun filtre de liquidité explicite ne le reproduit — à effectif égal
(25,8 valeurs par séance, seuil à 500 000 FCFA) le composite rend +0,026.
Ce n'était donc pas « les valeurs liquides », c'était « celles qui cotent
sans interruption », et ce n'est la politique de personne.

Une mesure qui baisse en devenant juste est une mesure qui était fausse.

LA VOLATILITÉ FAIT EXCEPTION, ET C'EST IMPORTANT. Un cours reporté produit
un rendement nul, qui n'est pas un calme observé mais une absence
d'observation. Les compter écraserait l'écart-type des valeurs les moins
traitées — soit les faire passer pour les plus sages, exactement à
l'envers. La volatilité se mesure donc sur les seules séances RÉELLEMENT
échangées.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import charger

# Séances de bourse par an, pour annualiser la volatilité. La BRVM cote du
# lundi au vendredi hors jours fériés — 250 est l'ordre de grandeur usuel.
SEANCES_PAR_AN = 250


def _minimum(fenetre: int, part: float = 0.6) -> int:
    """Observations exigées dans une fenêtre de `fenetre` séances.

    Assez pour que la moyenne veuille dire quelque chose, pas assez pour
    exiger une suite ininterrompue — voir l'en-tête du module. La part de
    60 % est un compromis : à 100 %, on retombe sur le défaut de pandas et
    sur le biais de sélection qu'il cachait ; trop bas, une moyenne à cent
    séances calculée sur dix n'en serait plus une.
    """
    return max(2, int(round(fenetre * part)))


def serie(cours: pd.DataFrame, colonne: str = "cloture") -> pd.DataFrame:
    """Table de cours → matrice dates × tickers.

    Les dates sont au format ISO, donc l'ordre alphabétique est l'ordre
    chronologique ; inutile de convertir en datetime pour trier.
    """
    if cours.empty:
        return pd.DataFrame()
    table = cours.pivot_table(
        index="date", columns="ticker", values=colonne, aggfunc="last"
    )
    return table.sort_index()


def momentum(prix: pd.DataFrame, fenetre: int, saut: int) -> pd.Series:
    """Rendement sur `fenetre` séances, en sautant les `saut` dernières.

    LE SAUT N'EST PAS UN DÉTAIL DE CONVENTION. Le momentum à un an et le
    retournement à un mois sont deux effets opposés : une valeur qui vient
    de bondir de 20 % en trois semaines tend à rendre une partie de ce
    mouvement. Mesurer jusqu'à aujourd'hui mélange les deux et achète les
    hausses les plus fraîches, qui sont les plus fragiles. D'où la fenêtre
    de t-250 à t-20, et non de t-250 à t.
    """
    if len(prix) < fenetre + 1:
        return pd.Series(np.nan, index=prix.columns)
    debut = prix.iloc[-(fenetre + 1)]
    fin = prix.iloc[-(saut + 1)]
    return (fin / debut - 1).where(debut > 0)


def _moyenne_exigeante(tranche: pd.DataFrame, fenetre: int) -> pd.Series:
    """Moyenne d'une tranche, NaN en deçà du minimum d'observations.

    C'est la règle `min_periods` de la passe glissante, écrite ici pour que
    les deux chemins ne puissent pas diverger — voir `_minimum`.
    """
    minimum = _minimum(fenetre)
    return tranche.mean().where(tranche.notna().sum() >= minimum)


def tendance(prix: pd.DataFrame, courte: int, longue: int) -> pd.Series:
    """Écart entre moyenne mobile courte et longue, en proportion.

    Positif quand le cours récent domine le cours de fond. Redondant avec
    le momentum par construction, mais sur un horizon plus court : c'est ce
    qui distingue une hausse encore vivante d'une hausse qui s'essouffle.

    Attend des cours DÉJÀ REPORTÉS (voir `cours_reportes`) : comme la passe
    glissante, la fonction compte des observations, pas des séances
    consécutives.
    """
    moyenne_courte = _moyenne_exigeante(prix.iloc[-courte:], courte)
    moyenne_longue = _moyenne_exigeante(prix.iloc[-longue:], longue)
    return (moyenne_courte / moyenne_longue - 1).where(moyenne_longue > 0)


def volatilite(prix: pd.DataFrame, fenetre: int,
               echange: pd.DataFrame | None = None) -> pd.Series:
    """Écart-type annualisé des rendements quotidiens.

    Calculé en logarithmes : sur des séries qui peuvent doubler, les
    rendements arithmétiques rendent la hausse et la baisse asymétriques.

    `echange` — la matrice des séances réellement traitées — écarte les
    rendements nuls fabriqués par le report du dernier cours. Sans elle,
    les valeurs les moins échangées passeraient pour les plus calmes, soit
    l'inverse de la vérité. Voir l'en-tête du module.
    """
    if prix.empty:
        return pd.Series(np.nan, index=prix.columns)
    rendements = np.log(prix).diff()
    if echange is not None:
        rendements = rendements.where(echange.reindex_like(rendements))
    tranche = rendements.iloc[-fenetre:]
    minimum = _minimum(fenetre, 0.3)
    return (tranche.std() * np.sqrt(SEANCES_PAR_AN)).where(
        tranche.notna().sum() >= minimum)


def liquidite(cours: pd.DataFrame, fenetre: int) -> pd.Series:
    """Volume médian échangé, en FCFA.

    La médiane et non la moyenne : une seule transaction de bloc suffirait
    à faire passer pour liquide une valeur qui ne s'échange jamais.

    LES MANQUANTS VALENT ZÉRO, ET C'EST VOULU. Une séance sans ligne pour
    un ticker est une séance sans échange, pas une donnée absente. La
    compter comme inconnue relèverait la médiane des valeurs les moins
    traitées — exactement celles que le filtre doit écarter.
    """
    volumes = serie(cours, "volume_fcfa")
    if volumes.empty:
        return pd.Series(dtype=float)
    return volumes.iloc[-fenetre:].fillna(0).median()


def retournement(prix: pd.DataFrame, fenetre: int) -> pd.Series:
    """Rendement des `fenetre` dernières séances, SANS saut.

    L'exact opposé de `momentum`, et volontairement : ce que le momentum
    écarte comme trop frais pour être fiable est ici la mesure même. Une
    valeur qui vient de bondir tend à rendre une part de son mouvement,
    d'où un IC négatif attendu — et mesuré, -0,041 sur onze ans d'archive.
    Pris seul il ne se distingue pas du hasard (t -1,3) ; il est retenu
    parce que le retirer du modèle coûte presque autant que retirer le choc
    de volume.
    """
    if len(prix) < fenetre + 1:
        return pd.Series(np.nan, index=prix.columns)
    debut = prix.iloc[-(fenetre + 1)]
    return (prix.iloc[-1] / debut - 1).where(debut > 0)


def choc_volume(cours: pd.DataFrame, court: int, long: int) -> pd.Series:
    """Volume médian récent rapporté au volume médian de fond.

    Non pas « cette valeur s'échange beaucoup », que mesure déjà
    `liquidite` et qui ne prédit rien (t +0,7), mais « cette valeur
    s'échange soudain plus que d'habitude ».

    L'UN DES DEUX EFFETS QUI TIENNENT. Sur les 216 cases du balayage de
    `recherche.py`, deux seulement franchissent la correction de
    Benjamini-Hochberg : celui-ci et le choc éclair, qui est le même effet
    mesuré sur une semaine et qui le dépasse. Toutes deux à VINGT SÉANCES,
    l'horizon que `prediction` emploie depuis :

        choc éclair      IC +0,061   t +4,3
        choc de volume   IC +0,053   t +3,8

    Aux trois mois qu'employait `prediction` avant, celui-ci rend IC +0,064
    et t +2,3, et il est positif lors de onze des douze années de l'archive.

    L'effet est documenté ailleurs sous le nom de choc d'attention ; il
    n'est pas découvert ici, seulement retrouvé. Et il ne rapporte rien :
    exploité à son horizon d'un mois, il exige 48 % de rotation douze fois
    l'an et rend +6,2 % annuels contre +14,8 % pour la simple détention du
    même univers.
    """
    volumes = serie(cours, "volume_fcfa")
    if volumes.empty:
        return pd.Series(dtype=float)
    volumes = volumes.fillna(0)
    recent = volumes.iloc[-court:].median()
    fond = volumes.iloc[-long:].median()
    # Un FCFA au dénominateur : une valeur qui n'a rien échangé de l'année
    # donnerait sinon une division par zéro. Le rang centile dans la séance
    # efface l'échelle ensuite, si bien que la borne ne déplace aucun rang.
    return recent / (fond + 1.0)


def choc_eclair(cours: pd.DataFrame, eclair: int, long: int) -> pd.Series:
    """Le choc de volume sur une semaine au lieu d'un mois.

    Même rapport que `choc_volume`, même borne au dénominateur, fenêtre
    courte plus courte : l'attention se voit avant de se mesurer.

    LA PLUS FORTE CASE DU BALAYAGE, ET ELLE A PASSÉ LA CORRECTION. Ajouté
    d'abord pour mieux décrire le choc de volume, ce trait a ensuite été
    soumis au même test multiple que les autres — la règle est énoncée dans
    l'en-tête de `recherche._choc_volume` et elle vaut aussi pour les
    prédicteurs qu'on ajoute soi-même. Son entrée a porté la grille de 162 à
    216 cases, durcissant le seuil pour tout le monde, et il est passé quand
    même : IC +0,061 et t +4,3 à vingt séances sur tout le marché, première
    des 216. Le choc de volume, deuxième, rend t +3,8.

    Ses deux compagnons d'ajout ne passent pas — ampleur du choc t +2,6,
    intensité d'échange t +2,4 sur les financières. Ils restent dans le
    modèle parce qu'ils aident la combinaison, pas parce qu'ils se
    distinguent seuls du hasard, et c'est écrit pour qu'on ne leur prête pas
    une force qu'ils n'ont pas.
    """
    volumes = serie(cours, "volume_fcfa")
    if volumes.empty:
        return pd.Series(dtype=float)
    volumes = volumes.fillna(0)
    return volumes.iloc[-eclair:].median() / (volumes.iloc[-long:].median() + 1.0)


def ampleur_choc(cours: pd.DataFrame, fenetre: int, long: int) -> pd.Series:
    """Part des séances récentes dont le volume dépasse sa médiane de fond.

    L'AMPLEUR PLUTÔT QUE LA TAILLE. Une séance énorme et vingt séances un
    peu au-dessus donnent le même `choc_volume` ; elles ne racontent pas la
    même chose. Ce trait compte les séances, pas les francs.

    Chaque séance est comparée à la médiane de fond TELLE QU'ELLE ÉTAIT
    ce jour-là, et non à celle d'aujourd'hui : comparer le passé à une
    médiane calculée après coup ferait entrer l'avenir dans le trait.
    """
    volumes = serie(cours, "volume_fcfa")
    if volumes.empty:
        return pd.Series(dtype=float)
    volumes = volumes.fillna(0)
    fond = volumes.rolling(long, min_periods=1).median()
    depasse = (volumes > fond).where(fond.notna())
    tranche = depasse.iloc[-fenetre:]
    assez = tranche.notna().sum() >= _minimum(fenetre, 0.5)
    return tranche.mean().where(assez)


def intensite_echange(cours: pd.DataFrame, fenetre: int) -> pd.Series:
    """Part des séances récentes où la valeur a RÉELLEMENT été traitée.

    Une fréquence de cotation, non un niveau de volume — `liquidite` mesure
    déjà le second. Une valeur qui passe de trois séances par mois à vingt
    vient de se réveiller, et cela ne se lit dans aucun autre trait.
    """
    brut = serie(cours)
    if brut.empty:
        return pd.Series(dtype=float)
    echange = brut.notna().astype(float)
    tranche = echange.iloc[-fenetre:]
    assez = tranche.notna().sum() >= _minimum(fenetre, 0.5)
    return tranche.mean().where(assez)


DEFAUTS_FENETRES = {
    "fenetre_momentum": 250, "saut_momentum": 20,
    "fenetre_volatilite": 60, "fenetre_liquidite": 60,
    "moyenne_courte": 20, "moyenne_longue": 100,
    "fenetre_retournement": 20,
    "fenetre_choc_court": 20, "fenetre_choc_long": 250,
    "fenetre_choc_eclair": 5, "fenetre_attention": 20,
    "report_max_seances": 20,
}

# Traits de NOTATION : ceux que `scoring` combine en un classement, et dont
# les pondérations vivent dans la configuration. La liste est inchangée —
# y ajouter un trait changerait le classement de l'onglet Classement, ce
# qui n'est pas ce qu'on cherche ici.
TRAITS = ["momentum", "tendance", "volatilite", "liquidite"]

# Traits supplémentaires, calculés pour la PRÉDICTION seule. Ils ne sont
# pas là par goût de l'abondance : chacun a été mesuré sur les onze ans
# d'archive avant d'être retenu, et douze candidats ont été écartés.
#
#   choc_volume    IC +0,064, t +2,3, positif 11 années sur 12. C'est
#                  aussi l'une des deux cases des 216 du balayage de
#                  `recherche.py` à franchir la correction de
#                  Benjamini-Hochberg — à l'horizon d'un mois, où elle
#                  rend t +3,8 ; l'autre est le choc éclair, ci-dessous,
#                  qui la dépasse (t +4,3). Retiré du modèle, l'IC tombe de +0,044 à
#                  +0,011 et l'IR de 0,66 à 0,13.
#   retournement   IC -0,041, t -1,3 : pris seul, il ne se distingue pas
#                  du hasard. Il est pourtant retenu, parce qu'il porte
#                  bien davantage en présence des autres — retiré du
#                  modèle, l'IC tombe de +0,044 à +0,013 et l'IR de 0,66 à
#                  0,16, presque autant que pour le choc de volume.
#
# Les deux t ci-dessus emploient l'estimateur conservateur du projet
# (voir `apprentissage.mesure_ic`) ; le traitement usuel d'une série à
# dépendance bornée les doublerait à peu près.
#
# Pour mémoire, le principal rejeté : la distance au plus haut de 52
# semaines affichait IC +0,106 et t +2,8 — sur les 1 159 dates où elle
# était calculable. Rendue calculable partout par les corrections
# ci-dessus, elle tombe à -0,006 et t -0,2. Ce n'était pas un signal,
# c'était l'échantillon qu'elle sélectionnait.
TRAITS_PREDICTION = ["choc_volume", "retournement"]

# TRAITS D'ATTENTION. Le choc de volume est le seul signal du projet qui
# tienne ; ces trois-là ne sont pas de nouveaux paris, ce sont trois
# manières de mieux décrire CELUI-LÀ. On ne cherche pas ailleurs, on
# regarde mieux au seul endroit où il y a quelque chose.
#
#   choc_eclair       le choc sur une semaine plutôt qu'un mois. Le même
#                     rapport que `choc_volume`, une fenêtre courte plus
#                     tôt : l'attention se voit avant de se mesurer.
#   ampleur_choc      la PART des séances du mois où le volume dépasse sa
#                     médiane annuelle, et non de combien il la dépasse.
#                     Une seule séance énorme et vingt séances un peu
#                     au-dessus donnent le même `choc_volume` ; elles ne
#                     racontent pas la même chose, et c'est ce trait qui
#                     les sépare.
#   intensite_echange la part des séances du mois réellement traitées. La
#                     matrice `cotee` ne servait que de filtre ; une valeur
#                     qui passe de trois séances par mois à vingt vient de
#                     se réveiller, et cela ne se lit dans aucun autre
#                     trait — `liquidite` mesure un NIVEAU de volume, pas
#                     une fréquence de cotation.
#
# Mesuré sur l'archive, en ajout aux six autres : IC de la combinaison
# +0,0450 -> +0,0500 et IR 0,51 -> 0,57. Pris seuls ils ne valent rien ;
# c'est en présence du choc de volume qu'ils portent.
TRAITS_ATTENTION = ["choc_eclair", "ampleur_choc", "intensite_echange"]

# Ce que `calculer` et `traits_glissants` rendent, dans l'ordre.
TOUS_TRAITS = TRAITS + TRAITS_PREDICTION + TRAITS_ATTENTION


def _fenetres(reglages: dict | None) -> dict[str, int]:
    conf = (reglages or charger()).get("analyse", {})
    return {cle: int(conf.get(cle, defaut))
            for cle, defaut in DEFAUTS_FENETRES.items()}


def cours_reportes(prix: pd.DataFrame, limite: int) -> pd.DataFrame:
    """Dernier cours connu, reporté au plus `limite` séances.

    Deux bornes, et chacune ferme une manière de mentir :

    - `ffill` ne remonte jamais le temps. Un cours du 3 ne renseigne que
      les séances suivantes, jamais les précédentes : les séances d'avant
      la première cotation restent vides, et une société introduite en 2021
      n'a donc pas de cours en 2019. C'est aussi ce qui rend l'opération
      utilisable dans un calcul glissant sans y introduire de regard en
      avant.
    - `limit` arrête le report au bout de `limite` séances. Un titre qui
      n'a pas échangé depuis trois mois n'a pas un cours, il a un souvenir ;
      passé la limite il ressort du classement, comme avant. C'est aussi ce
      qui fait disparaître une société radiée, sans qu'on ait eu besoin de
      savoir qu'elle allait l'être.

    UNE TROISIÈME BORNE A ÉTÉ ESSAYÉE PUIS RETIRÉE, et son retrait vaut
    d'être dit. Masquer les séances postérieures à la DERNIÈRE cotation du
    titre — pour ne rien fabriquer après une radiation — suppose un
    `bfill`, c'est-à-dire de savoir aujourd'hui si le titre cotera encore
    demain. C'est un regard en avant, discret, dans la fonction même qui
    prépare tous les traits. La limite ci-dessus rend le même service sans
    consulter l'avenir : elle laisse simplement le titre s'éteindre.

    CONSÉQUENCE POUR LE CLASSEMENT, à connaître. Une valeur qui a cessé
    d'échanger depuis moins de `limite` séances garde un cours — son
    dernier — et reste donc notée par `scoring`, là où elle disparaissait
    avant. C'est le comportement voulu : sur cette place, ne pas avoir
    échangé mardi n'est pas un événement. `prediction`, lui, exige en plus
    une cotation du jour, parce qu'il ne mesure pas, il propose d'acheter.
    """
    if prix.empty:
        return prix
    seances = int(limite)
    # ZÉRO VEUT DIRE « AUCUN REPORT », ET PANDAS REFUSE DE L'ENTENDRE :
    # `ffill(limit=0)` lève « Limit must be greater than 0 » au lieu de ne
    # rien combler. Le réglage est légitime — c'est le comportement strict
    # d'avant la correction, que quelqu'un peut vouloir retrouver pour
    # comparer — donc c'est ici qu'il faut le traduire, et non interdire la
    # valeur. Les négatifs tombent dans le même cas : on ne reporte rien.
    if seances <= 0:
        return prix.copy()
    return prix.ffill(limit=seances)


def neutraliser_secteur(rangs: pd.Series, dates: pd.Series,
                        secteurs: pd.Series) -> pd.Series:
    """Rang centile moins le rang moyen de son secteur, ce jour-là.

    POURQUOI. Un rang centile calculé sur toute la cote mesure en partie
    « est-ce une banque ». Les Services Financiers pèsent 34,5 % de
    l'univers coté et 16 des 47 lignes du référentiel ; quand le secteur
    entier monte, ses valeurs montent dans le classement ensemble, sans
    qu'aucune n'ait rien montré. Mesuré sur l'archive : les dix premiers
    du classement de production sont à 43,9 % des Services Financiers
    contre 34,5 % dans l'univers, soit **+9,5 points de pari sectoriel**
    que l'utilisateur n'a pas choisi. Après neutralisation des sources
    apprises, +5,3 points — et non zéro, parce que le composite garde
    volontairement les rangs de marché (voir `prediction.PREFIXE_NEUTRE`).
    Neutraliser les trois sources ramènerait le pari à +1,4 point, au prix
    de l'apport du composite : c'est l'arbitrage qui a été tranché, et il
    l'a été sur l'IC de la combinaison, +0,067 contre +0,058.

    CE QUE ÇA CHANGE, et ce que ça ne change pas. Retirer la moyenne du
    secteur ne prétend pas que le secteur ne compte pas — il compte
    beaucoup, et sur cette place les banques versent les dividendes qui
    FONT le rendement total. Cela dit seulement qu'un pari sectoriel doit
    être choisi, pas hérité d'un classement.

    POURQUOI RETRANCHER LA MOYENNE PLUTÔT QUE RANGER DANS LE SECTEUR. Les
    deux mesurent pareil (IC +0,0517 contre +0,0521), et le départage est
    mécanique : le secteur médian ne compte que 4 valeurs cotées par
    séance, le premier quartile 2. Rangée dans son secteur, une valeur
    SEULE reçoit le rang 1,0 — le maximum, sur tous les traits à la fois,
    pour la seule raison qu'elle est seule. Retranchée de sa moyenne, elle
    reçoit 0,0, c'est-à-dire « rien à dire », qui est la vérité. Le cas
    pèse 0,2 % des lignes et ne déplace aucune mesure ; c'est la manière
    de se tromper qui a décidé, pas le chiffre.
    """
    cadre = pd.DataFrame({"v": np.asarray(rangs, dtype=float),
                          "d": np.asarray(dates),
                          "s": np.asarray(secteurs)})
    moyennes = cadre.groupby(["d", "s"])["v"].transform("mean")
    return pd.Series((cadre["v"] - moyennes).to_numpy(),
                     index=getattr(rangs, "index", None))


def traits_glissants(
    cours: pd.DataFrame, reglages: dict | None = None
) -> dict[str, pd.DataFrame]:
    """Tous les traits, à TOUTES les dates : {trait: matrice dates × tickers}.

    POURQUOI CETTE FONCTION EXISTE. Les traits étaient recalculés de zéro
    pour chaque date, avec un pivot complet à chaque tour. Mesuré sur des
    séries fabriquées : 0,96 s pour 150 séances, 4,37 s pour 250, 9,75 s
    pour 400 — une croissance quadratique qui donnait plusieurs minutes sur
    dix ans de cotation, à chaque chargement de l'onglet Prédiction et à
    chaque mouvement de curseur. Le coût devenait prohibitif exactement au
    moment où le projet réussit.

    Les mêmes quantités se calculent ici en une passe glissante sur la
    matrice entière. `calculer` n'est plus qu'une lecture de la dernière
    ligne, ce qui garantit que les deux chemins ne peuvent pas diverger.

    La matrice `cotee` accompagne les traits : elle dit, séance par séance,
    quelles valeurs ont RÉELLEMENT échangé. Les traits se calculent sur des
    cours reportés ; décider sur un cours reporté reviendrait en revanche à
    passer un ordre sur un prix que personne n'a traité, et c'est cette
    matrice qui permet de l'interdire en aval.
    """
    f = _fenetres(reglages)
    brut = serie(cours)
    if brut.empty:
        return {trait: pd.DataFrame() for trait in [*TOUS_TRAITS, "cloture",
                                                    "cotee"]}

    # Le report comble les séances sans échange ; `brut.notna()` garde la
    # trace de ce qui a vraiment été traité.
    prix = cours_reportes(brut, f["report_max_seances"])
    echange = brut.notna()

    # Momentum : cours en t-saut rapporté au cours en t-fenetre. `shift`
    # décale d'autant de LIGNES, ce qui correspond aux séances puisque la
    # matrice est indexée par date de cotation.
    debut = prix.shift(f["fenetre_momentum"])
    fin = prix.shift(f["saut_momentum"])
    mom = (fin / debut - 1).where(debut > 0)

    courte = prix.rolling(f["moyenne_courte"],
                          min_periods=_minimum(f["moyenne_courte"])).mean()
    longue = prix.rolling(f["moyenne_longue"],
                          min_periods=_minimum(f["moyenne_longue"])).mean()
    tend = (courte / longue - 1).where(longue > 0)

    # `rolling(n).std()` sur les log-rendements porte sur n écarts, soit les
    # n+1 cours de la version ponctuelle. Même estimateur (ddof=1).
    #
    # `.where(echange)` est la ligne qui empêche le report de mentir ici :
    # sans elle, chaque séance non traitée apporterait un rendement nul et
    # les valeurs les moins échangées passeraient pour les plus calmes.
    rendements = np.log(prix).diff().where(echange)
    vol = rendements.rolling(
        f["fenetre_volatilite"],
        min_periods=_minimum(f["fenetre_volatilite"], 0.3),
    ).std() * np.sqrt(SEANCES_PAR_AN)

    # `min_periods=1` reproduit `iloc[-fenetre:]`, qui prenait ce qui
    # existait quand l'historique était plus court que la fenêtre.
    volumes = serie(cours, "volume_fcfa").reindex(
        index=brut.index, columns=brut.columns
    ).fillna(0)
    liq = volumes.rolling(f["fenetre_liquidite"], min_periods=1).median()

    # RETOURNEMENT À COURT TERME. Le rendement du dernier mois, SANS saut —
    # c'est précisément ce que `momentum` évite de regarder, et pour la
    # raison inverse : ce que le momentum écarte comme fragile est ici la
    # mesure elle-même. Une valeur qui vient de bondir tend à rendre une
    # part de son mouvement, d'où un IC négatif attendu, et mesuré (-0,041
    # sur onze ans).
    ret = (prix / prix.shift(f["fenetre_retournement"]) - 1).where(
        prix.shift(f["fenetre_retournement"]) > 0)

    # CHOC DE VOLUME. Volume médian du dernier mois rapporté à celui de la
    # dernière année : non pas « cette valeur s'échange beaucoup », que
    # mesure déjà `liquidite` et qui ne prédit rien (t +0,7), mais « cette
    # valeur s'échange soudain plus que d'habitude ».
    #
    # C'EST LE SEUL TRAIT DU PROJET DONT LE SIGNAL TIENNE. IC +0,064, t
    # +2,3, positif lors de onze des douze années de l'archive — là où le
    # momentum et la tendance changent de signe d'une année à l'autre — et
    # l'une des deux cases des 216 du balayage de `recherche.py` à franchir
    # la correction de Benjamini-Hochberg — l'autre étant le choc éclair,
    # qui est le même effet mesuré sur une semaine et qui la dépasse. L'effet est documenté ailleurs sous
    # le nom de choc d'attention ; il n'est pas découvert ici, seulement
    # retrouvé.
    #
    # Le rapport est borné en bas par 1 FCFA au dénominateur : une valeur
    # qui n'a rien échangé de l'année donnerait sinon une division par
    # zéro. Le rang centile dans la séance efface ensuite l'échelle, si
    # bien que la borne ne déplace aucun classement.
    court = volumes.rolling(f["fenetre_choc_court"], min_periods=1).median()
    long_ = volumes.rolling(f["fenetre_choc_long"], min_periods=1).median()
    choc = court / (long_ + 1.0)

    # Les trois traits d'attention, voir `TRAITS_ATTENTION`. Ils partagent
    # le dénominateur de `choc_volume` — même borne à 1 FCFA, pour la même
    # raison — et ne coûtent qu'une passe glissante de plus.
    eclair = volumes.rolling(f["fenetre_choc_eclair"], min_periods=1).median()
    choc_eclair = eclair / (long_ + 1.0)

    # `ampleur` compte les séances au-dessus de la médiane annuelle. La
    # comparaison se fait séance par séance contre la médiane GLISSANTE,
    # donc sans jamais regarder devant.
    attention = f["fenetre_attention"]
    ampleur = (volumes > long_).where(long_.notna()).rolling(
        attention, min_periods=_minimum(attention, 0.5)).mean()

    # Fréquence de cotation, et non niveau de volume : `echange` est
    # booléen, sa moyenne glissante est une part de séances traitées.
    intensite = echange.astype(float).rolling(
        attention, min_periods=_minimum(attention, 0.5)).mean()

    return {"cloture": prix, "cotee": echange, "momentum": mom,
            "tendance": tend, "volatilite": vol, "liquidite": liq,
            "choc_volume": choc, "retournement": ret,
            "choc_eclair": choc_eclair, "ampleur_choc": ampleur,
            "intensite_echange": intensite}


def calculer(cours: pd.DataFrame, reglages: dict | None = None) -> pd.DataFrame:
    """Tous les traits, à la dernière date disponible, un ticker par ligne.

    La colonne `cotee` dit si la valeur a échangé lors de cette séance. Les
    traits d'une valeur non échangée restent calculés — son dernier cours
    connu est encore sa valorisation — mais `prediction` refuse de lui
    attribuer une probabilité : on ne prédit pas un titre qu'on ne peut pas
    acheter aujourd'hui.
    """
    matrices = traits_glissants(cours, reglages)
    if matrices["cloture"].empty:
        return pd.DataFrame(columns=["cloture", *TOUS_TRAITS, "cotee"])

    dates = matrices["cloture"].index
    traits = pd.DataFrame(
        {nom: matrice.iloc[-1] for nom, matrice in matrices.items()}
    )
    traits.index.name = "ticker"
    traits.attrs["date"] = str(dates[-1])
    traits.attrs["seances"] = len(dates)
    return traits[["cloture", *TOUS_TRAITS, "cotee"]]
