"""Prédiction de surperformance à horizon trimestriel, et sa validation.

CE QUE CE MODULE PRÉDIT, ET CE QU'IL NE PRÉDIT PAS
--------------------------------------------------
Il n'annonce pas un cours futur, et n'essaie pas de deviner si le marché
monte. Il répond à une question plus étroite et beaucoup plus atteignable :

    parmi les valeurs cotées, lesquelles surperformeront le marché sur
    les trois prochains mois ?

Ce cadrage n'est pas une esquive, ce sont les seules conditions où la
question est soluble ici.

D'abord parce que la BRVM cote par fixing, avec une limite de variation de
±7,5 % et des lignes qui ne s'échangent parfois que quelques fois par
semaine. Sur des cours ainsi figés, un modèle entraîné à prédire le
lendemain apprend « demain ≈ aujourd'hui », affiche un R² magnifique, et
produit un backtest brillant et inexécutable. Le signal exploitable est à
un à six mois, pas à la séance.

Ensuite parce que 47 valeurs sur des années font un panel utilisable en
CLASSEMENT, là où chaque valeur prise isolément est une série trop courte
et trop bruitée. On passe d'un problème de série temporelle mal posé à un
problème d'ordre, qui l'est.

QUATRE PIÈGES, ET COMMENT ILS SONT FERMÉS
-----------------------------------------
1. FUITE TEMPORELLE. Une découpe aléatoire entraînerait sur mardi pour
   prédire lundi. La validation est donc glissante : on entraîne sur le
   passé, on teste sur la période suivante, jamais l'inverse.

2. RECOUVREMENT DES ÉTIQUETTES. Avec un horizon de H séances, l'étiquette
   de la date t dépend des cours jusqu'à t+H. Les t situés dans les H
   séances qui précèdent la période de test connaissent donc déjà une part
   de son avenir. Ils sont purgés — sans quoi la précision monte sans que
   le modèle ait rien appris.

3. RÉFÉRENCE ABSENTE. Une précision seule ne veut rien dire. Chaque
   résultat est rendu avec la référence à battre et l'écart ; c'est
   l'écart, et lui seul, qui porte l'information.

4. TROP PEU DE PÉRIODES DE TEST POUR QUE LA MESURE TIENNE. C'est le piège
   ajouté, et il était ouvert. Avec quatre découpes, l'IC d'une période à
   l'autre allait de +0,29 à -0,28 : quatre tirages d'une variable dont
   l'écart-type dépasse la moyenne d'un ordre de grandeur. On concluait sur
   du bruit, et la conclusion changeait à chaque séance versée. Le défaut
   est passé à dix découpes, et la validation rend désormais la DISPERSION
   entre périodes — l'IR, la part de périodes positives, la pire — au lieu
   de la seule moyenne qui la cachait.

CE QUE VOUS DEVEZ EN ATTENDRE
-----------------------------
La référence n'est pas le hasard : c'est le score composite de
`scoring.py`, momentum et liquidité sans apprentissage. Sur ce marché, un
composite simple bat très souvent un modèle appris ; ce n'est plus le cas
ici, et il a fallu trois changements pour y arriver.

Mesuré sous un protocole unique — dix découpes, archive complète, erreur-
type conservatrice — avant et après :

                                       IC       t     IR   >0    pire
    AVANT  univers brut, 4 traits   -0,056   -1,1  -0,43  4/10  -0,240
    APRÈS  univers corrigé,
           6 traits, 3 sources      +0,045   +1,5  +0,51  7/10  -0,094

Ce qui a changé, par ordre d'importance :

1. LES DONNÉES. Une valeur qui n'échange pas tous les jours n'avait jamais
   de tendance calculable, donc jamais de place dans l'échantillon : 16,2
   valeurs notées par séance sur 37,7 cotées. C'était un biais de sélection
   contre la moitié illiquide du marché. Corrigé, l'échantillon passe de
   40 131 à 100 961 lignes — voir l'en-tête de `features.py`.

2. LES TRAITS. Un seul porte un signal qui tienne, le choc de volume, et ce
   n'est aucun de ceux que le projet mettait en avant. Ôtez-le et l'IC du
   modèle tombe de +0,044 à +0,011.

3. LA COMBINAISON. Trois sources à poids égaux — la régression, des poids
   par trait appris puis rétrécis, le composite de la configuration —
   plutôt qu'une seule. Les poids de combinaison APPRIS ont été essayés et
   rejetés, mesure à l'appui : voir `apprentissage.py`.

L'IC attendu d'un modèle honnête se situe entre 0,02 et 0,05 ; 0,10 est
excellent. Au-delà de 0,30, cherchez le bug avant d'ouvrir le champagne.

DEUX RÉSERVES, ET ELLES COMPTENT PLUS QUE LE TABLEAU CI-DESSUS
--------------------------------------------------------------
D'ABORD, +0,045 N'EST PAS SIGNIFICATIF. Le t vaut 1,5 avec l'erreur-type
conservatrice du module ; il faudrait 2. Le signe a changé, la dispersion
s'est réduite de moitié, sept périodes sur dix sont positives contre
quatre — tout cela est une amélioration réelle et mesurable, et rien de
tout cela ne permet d'affirmer que l'IC vrai est différent de zéro. Un seul
trait franchit le seuil pris isolément, le choc de volume, à t +2,5.

L'ÉTIQUETTE EST UN RENDEMENT DE COURS NU, ET CE N'EST PAS UN OUBLI
-----------------------------------------------------------------
Sur cette place le dividende fait 7 à 10 % l'an quand le cours en rend 2,8 :
prédire le cours seul revient à ignorer la moitié de ce qu'un porteur
touche, et à le faire systématiquement contre les valeurs de rendement. Le
backtest a été corrigé de ce défaut ; l'étiquette de prédiction, non — et
c'est délibéré.

Essayée, l'étiquette totale fait passer l'IC de la combinaison de +0,045
(t 1,5) à +0,079 (t 2,3), soit le seuil de signification franchi pour la
première fois du projet. Le chiffre ne vaut rien, pour deux raisons
mesurées :

1. LA COUVERTURE. 26 % des lignes n'ont aucun dividende connu et reçoivent
   donc zéro. Ce zéro n'est pas une société qui n'a rien versé : sur les
   seize années-sociétés non datées que les fondamentaux peuvent arbitrer,
   SEIZE versaient bien un dividende. C'est une donnée manquante déguisée en
   fait. Restreinte aux lignes réellement couvertes, l'amélioration retombe
   de +0,045 à +0,050 — t 1,52, non significatif.

2. LE COURS NE REFLÈTE PAS CE QU'IL DÉTACHE. En agrégat, deux séances après
   un détachement, le cours archivé n'a rendu que 46 % du dividende versé.
   Ajouter le dividende entier crédite donc la moitié restante, qui n'a
   jamais été touchée par personne. Un trait qui prédit « un détachement
   approche » prédit alors ce rendement fantôme : « jours depuis le dernier
   détachement » rend ainsi un IC de +0,098 et un t de +2,5, entièrement
   artificiel. Voir `dividende.ajustement`, et
   `python -m brvm rendement --ajustement`.

Les cinq traits tirés du calendrier — rendement, croissance, régularité,
temps depuis le détachement, saisonnalité — ont été mesurés contre
l'étiquette de cours : tous entre -0,018 et +0,006 d'IC, |t| au plus 0,5,
positifs quatre à cinq années sur onze. Aucun n'entre dans le modèle.

Le verrou n'est donc pas le modèle ni le trait, c'est l'archive : il manque
un calendrier de détachements complet ET un cours qui les reflète. Le jour
où `dividende.ajustement` rendra « utilisable », cette section sera à
refaire.

ENSUITE, UN IC DE 0,045 N'EST PAS DE L'ARGENT. Simulé sur l'archive avec
dix positions, un rééquilibrage trimestriel et 3 % de frais l'aller-retour,
ce classement ne bat PAS la simple détention équipondérée du même univers :
le rendement moyen par période est meilleur (+4,7 % contre +3,3 %) et la
rotation qu'il exige le mange en entier. Ce module mesure un ORDRE ;
`backtest.py` mesure ce qu'il en reste après le courtier, et c'est lui
qu'il faut croire avant de passer un ordre.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import apprentissage, exogene, features
from .apprentissage import ApprentissageIndisponible  # noqa: F401 — API publique
from .config import charger

# scikit-learn est la SEULE dépendance lourde du projet, et elle ne sert
# qu'au modèle appris. Tout le reste — l'échantillon, la purge, l'IC, les
# poids de fiabilité, la combinaison — est du pandas.
#
# L'importer au niveau du module la rendait obligatoire pour tout le monde :
# une absence dans l'environnement d'hébergement faisait tomber les six
# onglets du tableau de bord, dont cinq n'en ont aucun besoin. Elle est donc
# optionnelle, et son absence ne coûte qu'une des trois sources — les deux
# autres, et donc un classement, restent calculables.
APPRENTISSAGE_DISPONIBLE = apprentissage.DISPONIBLE

MOTIF_INDISPONIBLE = (
    "scikit-learn n'est pas installé dans cet environnement : la régression "
    "logistique est indisponible. Les deux autres sources — le score "
    "composite et les poids de fiabilité appris par trait — se calculent "
    "sans elle, et la combinaison continue de fonctionner avec ce qui "
    "reste. Pour rétablir la troisième : `pip install scikit-learn`."
)

# Traits utilisés par la prédiction : les quatre de la notation, plus les
# deux retenus après mesure sur onze ans d'archive. Volontairement peu
# nombreux : multiplier les entrées sur 47 valeurs est le moyen le plus
# rapide de mémoriser le passé au lieu de l'apprendre. Le détail de ce qui
# a été retenu et rejeté est dans `features.TRAITS_PREDICTION`.
TRAITS = list(features.TOUS_TRAITS)

# Les trois sources combinées, dans l'ordre où elles sont rendues.
SOURCES = ("modele", "fiabilite", "composite")

AVERTISSEMENTS = (
    "cible : surperformer le marché, pas monter",
    "validation glissante avec purge des étiquettes recouvrantes",
    "trois sources équipondérées : poids appris rejetés, faute de périodes",
    "IC exploitable : 0,02 à 0,05 ; au-delà de 0,30, cherchez la fuite",
    "l'écart mesuré ne survit pas aux 3 % de frais l'aller-retour",
)


def _rangs(colonne: pd.Series) -> pd.Series:
    """Rang centile dans la séance, comme dans `scoring`.

    Les niveaux bruts ne sont pas comparables d'une date à l'autre : une
    volatilité de 30 % est élevée en période calme et banale en crise. Le
    rang du jour, lui, garde le même sens partout.
    """
    return colonne.rank(pct=True)


def _joindre_exogenes(
    echantillon: pd.DataFrame,
    exogenes: pd.DataFrame | None,
    referentiel: pd.DataFrame | None,
    reglages: dict,
) -> tuple[pd.DataFrame, list[str]]:
    """Ajoute les colonnes exogènes × secteur, si elles existent.

    Renvoie l'échantillon et la liste des traits effectivement ajoutés — le
    modèle doit savoir sur quoi il apprend, et l'absence de séries en base
    est le cas normal aujourd'hui.
    """
    if exogenes is None or exogenes.empty or referentiel is None:
        return echantillon, []

    dates = sorted(echantillon["date"].unique())
    colonnes = exogene.traits(exogenes, dates, referentiel, reglages)
    if colonnes.empty:
        return echantillon, []

    ajoutes = [c for c in colonnes.columns if c.startswith("exo_")]
    fusion = echantillon.merge(colonnes, on=["date", "ticker"], how="left")
    for colonne in ajoutes:
        fusion[colonne] = fusion[colonne].fillna(0.0)
    return fusion, ajoutes


# L'échantillon coûte une dizaine de secondes sur onze ans d'archive, et
# `valider` puis `predire` le construisent tous deux à l'identique — le
# tableau de bord payait donc deux fois. Deux entrées suffisent : l'archive
# entière, et la tranche filtrée par les curseurs.
_MEMO: dict[tuple, pd.DataFrame] = {}
_MEMO_MAX = 2


def _empreinte(cours: pd.DataFrame, conf: dict) -> tuple:
    """Clé de mémoïsation : ce dont l'échantillon dépend, et rien d'autre.

    Les bornes de dates et le nombre de lignes suffisent à distinguer deux
    tranches de l'archive ; les réglages de fenêtres et l'horizon changent
    le calcul et doivent donc entrer dans la clé.
    """
    if cours.empty:
        return ("vide",)
    return (
        len(cours),
        str(cours["date"].iloc[0]),
        str(cours["date"].iloc[-1]),
        repr(sorted(conf.get("analyse", {}).items())),
        int(conf.get("prediction", {}).get("horizon", 60)),
    )


def construire_echantillon(
    cours: pd.DataFrame, reglages: dict | None = None
) -> pd.DataFrame:
    """Une ligne par (date, ticker) : traits connus en t, étiquette en t+H.

    L'étiquette vaut 1 si la valeur bat la médiane des rendements de la
    séance sur l'horizon, 0 sinon.

    UNE LIGNE N'EXISTE QUE SI LA VALEUR A ÉCHANGÉ CE JOUR-LÀ. Les traits se
    calculent sur des cours reportés — sans quoi la moitié illiquide du
    marché n'aurait jamais de tendance, voir l'en-tête de `features` — mais
    une décision prise sur un cours reporté serait un ordre passé à un prix
    que personne n'a traité. Le report sert à MESURER le passé, jamais à
    fabriquer une occasion d'acheter.
    """
    conf = reglages or charger()
    cle = _empreinte(cours, conf)
    if cle in _MEMO:
        return _MEMO[cle].copy()

    analyse = conf.get("analyse", {})
    horizon = int(conf.get("prediction", {}).get("horizon", 60))
    besoin = int(analyse.get("fenetre_momentum", 250)) + 1

    prix = features.serie(cours)
    dates = list(prix.index)
    if len(dates) < besoin + horizon + 1:
        return pd.DataFrame()

    # Une seule passe glissante pour toutes les dates, au lieu d'un recalcul
    # complet par date. La coupe temporelle reste stricte : chaque trait
    # d'une date n'est fabriqué que de cours antérieurs ou égaux, par
    # construction des fenêtres glissantes — voir features.traits_glissants.
    matrices = features.traits_glissants(cours, conf)

    # UNE SEULE TABLE PLUTÔT QUE DEUX MILLE SEPT CENTS. La boucle bâtissait
    # un `DataFrame` par séance, puis les concaténait : seize secondes, et
    # payées deux fois par l'app puisque `valider` et `predire` construisent
    # chacun le même échantillon. Les traits, le rendement futur et le rang
    # dans la séance se calculent d'un bloc, la séance devenant une clé de
    # regroupement — la coupe temporelle est inchangée, c'est toujours
    # `traits_glissants` qui la garantit.
    fenetre = dates[besoin - 1:len(dates) - horizon]

    # Les cours reportés portent aussi l'étiquette : un titre non échangé en
    # t+H garde la valeur de son dernier échange, qui est ce qu'un porteur
    # constaterait sur son relevé. Mesurer le rendement à un cours absent
    # reviendrait à écarter l'observation, et à réintroduire par la cible le
    # biais de sélection que le report vient de fermer.
    reportes = matrices["cloture"]
    futur = (reportes.shift(-horizon) / reportes - 1).replace(
        [np.inf, -np.inf], np.nan)

    colonnes = {nom: matrices[nom].reindex(fenetre).stack(future_stack=True)
                for nom in TRAITS}
    colonnes["rendement_futur"] = futur.reindex(fenetre).stack(
        future_stack=True)
    colonnes["cotee"] = matrices["cotee"].reindex(fenetre).stack(
        future_stack=True)
    table = pd.concat(colonnes, axis=1)

    # La liquidité ne peut pas manquer — elle vaut zéro faute d'échange —
    # mais les cinq autres traits, si. Le rendement futur non plus ne peut
    # pas manquer : sans lui il n'y a pas d'étiquette.
    exigees = [t for t in TRAITS if t != "liquidite"] + ["rendement_futur"]
    table = table[table["cotee"].fillna(False).astype(bool)]
    table = table.dropna(subset=exigees)
    if table.empty:
        return pd.DataFrame()

    table.index.names = ["date", "ticker"]
    table = table.reset_index().drop(columns="cotee")

    # Moins de quatre valeurs cotées, et la médiane de la séance ne sépare
    # plus rien : la séance est écartée, comme dans la boucle d'origine.
    seance = table.groupby("date")["rendement_futur"]
    table = table[seance.transform("size") >= 4]
    if table.empty:
        return pd.DataFrame()

    seance = table.groupby("date")
    bloc = pd.DataFrame({t: seance[t].rank(pct=True) for t in TRAITS})
    bloc["cible"] = (table["rendement_futur"]
                     > seance["rendement_futur"].transform("median")
                     ).astype(int)
    # Le rendement réalisé est conservé tel quel : c'est lui qui sert à
    # l'IC, qui mesure l'ordre prédit et non une frontière binaire.
    bloc["rendement_futur"] = table["rendement_futur"]
    bloc["date"] = table["date"]
    bloc["ticker"] = table["ticker"]
    bloc = bloc.reset_index(drop=True)

    if len(_MEMO) >= _MEMO_MAX:
        _MEMO.clear()
    _MEMO[cle] = bloc
    return bloc.copy()


def _ic(scores: pd.Series, rendements: pd.Series) -> float:
    """Information Coefficient : corrélation de rang de Spearman.

    LA MÉTRIQUE, ET NON LA PRÉCISION NI LE RMSE. Ce qu'on demande au modèle
    est de bien ORDONNER les valeurs, pas de deviner un cours : le RMSE
    récompenserait un modèle qui recopie le dernier prix, et une précision
    binaire jette l'écart entre « à peine devant » et « loin devant ».

    Ordres de grandeur, sur les marchés étudiés : un IC moyen de 0,02 à
    0,05 est déjà exploitable, 0,10 est excellent. Au-delà de 0,30, cherchez
    la fuite.
    """
    if len(scores) < 3 or scores.nunique() < 2 or rendements.nunique() < 2:
        return float("nan")
    return float(scores.rank().corr(rendements.rank()))


def _score_composite(bloc: pd.DataFrame, poids: dict) -> pd.Series:
    """La référence à battre : somme pondérée des rangs, sans apprentissage."""
    return apprentissage.score_composite(bloc, poids)


def _ic_par_seance(bloc: pd.DataFrame, colonne: str) -> float:
    """IC moyen d'un score, mesuré dans chaque séance puis moyenné.

    Agrégé d'un coup sur toutes les dates, il mélangerait les écarts entre
    dates avec les écarts entre valeurs — et mesurerait surtout le marché.
    """
    ics = apprentissage.ic_par_date(bloc, colonne)
    return float(ics.mean()) if len(ics) else float("nan")


def mesurer_ic(bloc: pd.DataFrame, colonne: str, horizon: int) -> dict:
    """IC moyen ET l'incertitude qui va avec. Les deux, jamais l'un sans l'autre.

    POURQUOI CETTE FONCTION EXISTE. Un IC moyenné sur toutes les dates
    d'un historique quotidien paraît reposer sur des milliers
    d'observations. Il n'en est rien : avec un horizon de 60 séances,
    l'étiquette du lundi recouvre celle du mardi à 59/60. Deux dates
    voisines racontent la même histoire.

    Compter ces dates comme indépendantes multiplie le t par racine de
    l'horizon — environ huit ici. C'est exactement l'erreur qui a fait
    passer la volatilité pour un signal exploitable (t = -10,2) alors
    qu'elle ne se distingue pas du hasard (t = -1,4).

    L'erreur-type est donc calculée sur le nombre de périodes RÉELLEMENT
    disjointes, `dates / horizon`. C'est conservateur — le recouvrement
    n'annule pas toute l'information d'une date sur l'autre — et c'est le
    bon côté duquel se tromper quand on cherche un signal qui n'existe
    probablement pas.
    """
    mesure = apprentissage.mesure_ic(
        apprentissage.ic_par_date(bloc, colonne), horizon)
    return {
        "ic": mesure["ic"],
        "erreur_type": mesure["erreur_type"],
        "t": mesure["t"],
        "dates": mesure["dates"],
        # Le nom d'origine est conservé : c'est celui que lisent l'app, la
        # ligne de commande et les tests.
        "dates_independantes": mesure["blocs"],
        "significatif": mesure["significatif"],
    }


def _stabilite(ics: list[float]) -> dict:
    """Ce que la moyenne des périodes cache : sa propre dispersion.

    L'IR — IC moyen sur écart-type entre périodes — est la mesure de
    fiabilité que l'ancienne validation ne rendait pas. Deux stratégies au
    même IC moyen ne se valent pas si l'une le réalise à chaque période et
    l'autre une fois sur deux, et c'est justement la différence entre les
    architectures comparées dans `apprentissage.py`.
    """
    valeurs = np.asarray([v for v in ics if np.isfinite(v)], dtype=float)
    if len(valeurs) == 0:
        return {"ic": float("nan"), "ir": float("nan"), "ecart_type": float("nan"),
                "periodes": 0, "periodes_positives": 0, "part_positives": float("nan"),
                "pire": float("nan"), "meilleure": float("nan")}
    ecart = float(valeurs.std(ddof=1)) if len(valeurs) > 1 else float("nan")
    return {
        "ic": float(valeurs.mean()),
        "ir": float(valeurs.mean() / ecart) if ecart and ecart > 0 else float("nan"),
        "ecart_type": ecart,
        "periodes": len(valeurs),
        "periodes_positives": int((valeurs > 0).sum()),
        "part_positives": float((valeurs > 0).mean()),
        "pire": float(valeurs.min()),
        "meilleure": float(valeurs.max()),
    }


def _scores_des_sources(
    train: pd.DataFrame,
    test: pd.DataFrame,
    traits: list[str],
    poids_config: dict,
    horizon: int,
    exigence: float,
    membres: int,
) -> tuple[dict[str, pd.Series], dict]:
    """Les trois sources, apprises sur `train`, appliquées sur `test`.

    Rien de ce qui suit ne regarde `test` autrement qu'en lui appliquant un
    objet déjà figé : les poids de fiabilité comme les coefficients de la
    régression sortent du seul `train`, dont les étiquettes recouvrantes
    ont déjà été purgées par l'appelant.
    """
    poids_fiab = apprentissage.poids_fiabilite(train, traits, horizon, exigence)
    sources = {
        "fiabilite": apprentissage.score_fiabilite(test, poids_fiab),
        "composite": apprentissage.score_composite(test, poids_config),
    }
    detail = {"poids_fiabilite": poids_fiab, "coefficients": {}}

    if APPRENTISSAGE_DISPONIBLE:
        ensemble = apprentissage.Ensemble(traits, horizon, membres=membres)
        ensemble.entrainer(train)
        sources["modele"] = ensemble.probabilites(test)
        detail["coefficients"] = ensemble.coefficients()
    return sources, detail


def valider(
    cours: pd.DataFrame,
    reglages: dict | None = None,
    exogenes: pd.DataFrame | None = None,
    referentiel: pd.DataFrame | None = None,
) -> dict:
    """Validation glissante, purgée. Renvoie mesures, dispersion et détail.

    Ce que la fonction rend, et pourquoi chaque pièce y est :

        periodes        une ligne par période de test, avec l'IC de chaque
                        source — c'est là qu'on voit la dispersion
        sources         par source : IC, IR, périodes positives, pire
                        période, et le t sur blocs disjoints
        stabilite       la même chose pour la combinaison retenue
        retenue         ce qui part en production, et pourquoi
        calibrage       rang combiné → probabilité, appris hors échantillon
    """
    conf = reglages or charger()
    pred = conf.get("prediction", {})
    poids_config = conf.get("ponderations", {})
    horizon = int(pred.get("horizon", 60))
    decoupes = int(pred.get("decoupes", 10))
    minimum = int(pred.get("lignes_minimum", 400))
    exigence = float(pred.get("exigence_preuve", 4.0))
    membres = int(pred.get("membres_sac", 8))

    echantillon = construire_echantillon(cours, conf)
    echantillon, exo = _joindre_exogenes(echantillon, exogenes, referentiel, conf)
    traits = TRAITS + exo
    vide = {
        "periodes": pd.DataFrame(),
        "traits": traits,
        "lignes": len(echantillon),
        "lignes_minimum": minimum,
        "horizon": horizon,
        "motif": None,
        "sources": {},
        "stabilite": _stabilite([]),
        "retenue": "composite",
        "calibrage": apprentissage.Calibrage(),
        "avertissements": AVERTISSEMENTS,
    }
    if len(echantillon) < minimum:
        return vide

    dates = sorted(echantillon["date"].unique())
    if len(dates) < decoupes + 2:
        return vide

    frontieres = np.array_split(np.array(dates), decoupes + 1)
    resultats: list[dict] = []
    tests: list[pd.DataFrame] = []
    dernier_detail: dict = {"poids_fiabilite": {}, "coefficients": {}}

    for rang in range(1, len(frontieres)):
        test_dates = set(frontieres[rang])
        debut_test = min(frontieres[rang])

        # Purge : les dates d'entraînement dont l'étiquette déborde sur la
        # période de test sont retirées. Sans cela, le modèle connaît déjà
        # une partie de ce qu'on lui demande de prédire.
        entrainables = [d for d in dates if d < debut_test]
        if len(entrainables) <= horizon:
            continue
        gardees = set(entrainables[:-horizon])

        train = echantillon[echantillon["date"].isin(gardees)]
        test = echantillon[echantillon["date"].isin(test_dates)]
        if train.empty or test.empty or train["cible"].nunique() < 2:
            continue
        if len(train) < minimum // 2:
            continue

        test = test.copy()
        sources, dernier_detail = _scores_des_sources(
            train, test, traits, poids_config, horizon, exigence, membres)
        for nom, serie in sources.items():
            test[f"score_{nom}"] = serie
        test["score_combinaison"] = apprentissage.combiner(sources)

        ligne = {
            "periode": f"{min(frontieres[rang])} → {max(frontieres[rang])}",
            "lignes_entrainement": len(train),
            "lignes_test": len(test),
            "ic_combinaison": _ic_par_seance(test, "score_combinaison"),
        }
        for nom in SOURCES:
            colonne = f"score_{nom}"
            ligne[f"ic_{nom}"] = (_ic_par_seance(test, colonne)
                                  if colonne in test.columns else float("nan"))
        # La précision binaire est conservée parce qu'elle est lisible, et
        # rendue avec l'IC parce que seule elle trompe : un modèle qui a
        # raison à 51 % sur les paris serrés et tort sur les écarts nets
        # affiche une bonne précision et perd de l'argent.
        prevu = (test["score_combinaison"].rank(pct=True) >= 0.5).astype(int)
        ligne["precision"] = float((prevu == test["cible"]).mean())
        resultats.append(ligne)
        tests.append(test)

    if not resultats:
        return vide

    periodes = pd.DataFrame(resultats)
    tout = pd.concat(tests, ignore_index=True)

    # Par source : la moyenne, sa dispersion entre périodes, et le t sur
    # blocs disjoints de l'ensemble des périodes réunies. La moyenne de dix
    # moyennes ne dit rien de sa propre précision, d'où les deux.
    detail_sources: dict[str, dict] = {}
    for nom in ("combinaison", *SOURCES):
        colonne = f"ic_{nom}"
        if colonne not in periodes.columns:
            continue
        stab = _stabilite(list(periodes[colonne]))
        if not np.isfinite(stab["ic"]):
            continue
        detail_sources[nom] = {
            **stab, "mesure": mesurer_ic(tout, f"score_{nom}", horizon)}

    stabilite = detail_sources.get("combinaison", _stabilite([]))

    # LA DÉCISION DE PRODUCTION, ET ELLE EST ÉCRITE ICI PLUTÔT QUE LAISSÉE
    # À L'UTILISATEUR. La combinaison part en production tant qu'elle
    # montre un IC hors échantillon positif ; sinon c'est le composite,
    # qui n'estime rien et ne peut donc pas surajuster. Un onglet qui
    # affiche des probabilités issues d'un score dont l'IC mesuré est
    # négatif ne présente pas une prévision, il présente un bug.
    retenue = "combinaison" if stabilite["ic"] > 0 else "composite"

    # Le calibrage s'apprend sur les prédictions HORS ÉCHANTILLON de toutes
    # les périodes réunies — le seul endroit du calcul où la relation entre
    # rang et fréquence de surperformance soit observable honnêtement.
    calibrage = apprentissage.Calibrage().apprendre(
        tout[f"score_{retenue}"].rank(pct=True), tout["cible"])

    ic = float(periodes["ic_combinaison"].mean())
    ic_composite = float(periodes["ic_composite"].mean())
    return {
        "periodes": periodes,
        "traits": traits,
        "lignes": len(echantillon),
        "lignes_minimum": minimum,
        "horizon": horizon,
        "motif": None if APPRENTISSAGE_DISPONIBLE else MOTIF_INDISPONIBLE,
        # `ic` désigne ce qui part en production, c'est-à-dire la
        # combinaison ; les noms d'origine sont conservés pour l'app et la
        # ligne de commande.
        "ic": ic,
        "ic_composite": ic_composite,
        "ecart": ic - ic_composite,
        "precision": float(periodes["precision"].mean()),
        "mesure": mesurer_ic(tout, "score_combinaison", horizon),
        "mesure_composite": mesurer_ic(tout, "score_composite", horizon),
        "sources": detail_sources,
        "stabilite": stabilite,
        "retenue": retenue,
        "calibrage": calibrage,
        "poids_fiabilite": dernier_detail["poids_fiabilite"],
        "coefficients": dernier_detail["coefficients"],
        # Les traits un par un : c'est là qu'on voit sur quoi le classement
        # repose réellement, et le constat est sévère.
        "traits_mesures": {
            trait: mesurer_ic(tout, trait, horizon)
            for trait in traits if trait in tout.columns
        },
        "avertissements": AVERTISSEMENTS,
    }


def predire(
    cours: pd.DataFrame,
    reglages: dict | None = None,
    exogenes: pd.DataFrame | None = None,
    referentiel: pd.DataFrame | None = None,
    validation: dict | None = None,
) -> pd.DataFrame:
    """Probabilité de surperformer le marché, par valeur, à la dernière date.

    Une ligne par valeur cotée lors de la dernière séance, avec :

        probabilite     calibrée hors échantillon quand `validation` est
                        fournie, sinon le rang combiné tel quel
        incertitude     deux écarts-types entre les membres du sac — de
                        combien la probabilité bougerait si l'historique
                        avait été un autre tirage de périodes
        rang_combine    la position dans le classement, qui est ce que le
                        module sait vraiment produire
        et une colonne par source, pour voir laquelle porte la valeur

    PASSEZ-LUI LA VALIDATION. Sans elle, la fonction rend le rang combiné
    en guise de probabilité, ce qui donne un 100 % en tête de classement et
    un 0 % en queue — deux nombres que l'IC mesuré n'autorise pas. Avec
    elle, le calibrage resserre l'échelle autour de 50 %, ce qui est laid et
    vrai.
    """
    conf = reglages or charger()
    pred = conf.get("prediction", {})
    poids_config = conf.get("ponderations", {})
    horizon = int(pred.get("horizon", 60))
    minimum = int(pred.get("lignes_minimum", 400))
    exigence = float(pred.get("exigence_preuve", 4.0))
    membres = int(pred.get("membres_sac", 8))

    colonnes_vides = ["ticker", "probabilite", "incertitude", "rang_combine"]
    echantillon = construire_echantillon(cours, conf)
    echantillon, exo = _joindre_exogenes(echantillon, exogenes, referentiel, conf)
    traits = TRAITS + exo
    if len(echantillon) < minimum or echantillon["cible"].nunique() < 2:
        return pd.DataFrame(columns=colonnes_vides)

    # Les traits de la dernière séance, rangés dans cette séance comme dans
    # l'échantillon. `cotee` écarte les valeurs qui n'ont pas échangé : leur
    # cours reporté suffit à les mesurer, pas à les acheter.
    courant = features.calculer(cours, conf)
    if courant.empty:
        return pd.DataFrame(columns=colonnes_vides)
    exigees = [t for t in TRAITS if t != "liquidite"]
    courant = courant[courant["cotee"].fillna(False).astype(bool)]
    courant = courant.dropna(subset=[t for t in exigees if t in courant.columns])
    if courant.empty:
        return pd.DataFrame(columns=colonnes_vides)

    bloc = pd.DataFrame({t: _rangs(courant[t]) for t in TRAITS},
                        index=courant.index)
    # Colonnes exogènes de la date courante : mêmes noms, valeur du jour,
    # zéro hors du secteur visé.
    if exo:
        derniere = echantillon[echantillon["date"] == echantillon["date"].max()]
        for colonne in exo:
            par_ticker = derniere.set_index("ticker")[colonne]
            bloc[colonne] = bloc.index.map(par_ticker).fillna(0.0)

    poids_fiab = apprentissage.poids_fiabilite(
        echantillon, traits, horizon, exigence)
    sources = {
        "fiabilite": apprentissage.score_fiabilite(bloc, poids_fiab),
        "composite": apprentissage.score_composite(bloc, poids_config),
    }
    incertitude = pd.Series(np.nan, index=bloc.index)
    if APPRENTISSAGE_DISPONIBLE:
        ensemble = apprentissage.Ensemble(traits, horizon, membres=membres)
        ensemble.entrainer(echantillon)
        sources["modele"] = ensemble.probabilites(bloc)
        incertitude = ensemble.dispersion(bloc)

    retenue = (validation or {}).get("retenue", "combinaison")
    score = (apprentissage.combiner(sources) if retenue == "combinaison"
             else sources["composite"])
    if score.empty:
        return pd.DataFrame(columns=colonnes_vides)

    rang = score.rank(pct=True)
    calibrage = (validation or {}).get("calibrage")
    if calibrage is not None and getattr(calibrage, "disponible", False):
        probabilite = calibrage.appliquer(rang)
    else:
        probabilite = rang

    resultat = pd.DataFrame({
        "ticker": bloc.index,
        "probabilite": probabilite.to_numpy(),
        "incertitude": 2 * incertitude.to_numpy(),
        "rang_combine": rang.to_numpy(),
    })
    for nom in SOURCES:
        if nom in sources:
            resultat[f"rang_{nom}"] = sources[nom].rank(pct=True).to_numpy()
    resultat["calibree"] = bool(
        calibrage is not None and getattr(calibrage, "disponible", False))
    return resultat.sort_values(
        "probabilite", ascending=False).reset_index(drop=True)


def _avec_incertitude(mesure: dict) -> str:
    """« +0,006 ± 0,043 à 95 % (t=+0,3, non significatif) ».

    Un IC nu se retient et se cite ; son incertitude, non. Les coller
    ensemble est le seul moyen d'empêcher le premier de voyager seul.

    Le « à 95 % » n'est pas de la coquetterie : ce qui suit le ± vaut deux
    erreurs types, et un lecteur qui le prend pour une seule divise par
    deux la marge d'erreur qu'il croit lire.
    """
    if mesure["dates"] == 0 or mesure["erreur_type"] != mesure["erreur_type"]:
        return f"{mesure['ic']:+.3f} (incertitude non calculable)"
    verdict = "significatif" if mesure["significatif"] else "non significatif"
    return (f"{mesure['ic']:+.3f} ± {2 * mesure['erreur_type']:.3f} à 95 % "
            f"(t={mesure['t']:+.1f}, {verdict})")


LIBELLES_SOURCES = {
    "combinaison": "combinaison (retenue)",
    "modele": "régression logistique",
    "fiabilite": "poids de fiabilité appris",
    "composite": "composite de la configuration",
}


def expliquer(validation: dict) -> str:
    """Rendu texte. La référence n'est jamais séparée de la précision."""
    if validation["periodes"].empty:
        if validation.get("motif") and validation["lignes"] == 0:
            return validation["motif"]
        return (
            f"Pas assez de données pour valider : {validation['lignes']} "
            f"observations, {validation['lignes_minimum']} au minimum. "
            "Chaque séance ajoute une quarantaine de lignes, mais il faut "
            "d'abord un an de cotation avant que la première soit "
            "calculable — le momentum se mesure sur cette durée."
        )

    m, c = validation["mesure"], validation["mesure_composite"]
    stab = validation["stabilite"]
    lignes = []
    if validation.get("motif"):
        lignes += [validation["motif"], ""]
    lignes += [
        f"Horizon : {validation['horizon']} séances (~"
        f"{validation['horizon'] // 20} mois). {validation['lignes']} "
        f"observations, {len(validation['periodes'])} périodes de test.",
        "",
        f"  IC de la combinaison   {_avec_incertitude(m)}",
        f"  IC du score composite  {_avec_incertitude(c)}",
        f"  écart                  {validation['ecart']:+.3f}",
        f"  (précision binaire     {validation['precision']:.1%})",
        "",
    ]

    # LA DISPERSION, QUI EST LE VRAI SUJET. Un IC moyen sans elle laissait
    # croire à une mesure stable là où les périodes allaient de +0,29 à
    # -0,28.
    lignes += [
        "Ce que la moyenne cache — dispersion d'une période à l'autre :",
        "",
        f"  {'source':<26} {'IC':>7} {'IR':>6} {'périodes >0':>12} {'pire':>7}",
        f"  {'-' * 26} {'-' * 7} {'-' * 6} {'-' * 12} {'-' * 7}",
    ]
    for nom, mes in validation["sources"].items():
        lignes.append(
            f"  {LIBELLES_SOURCES.get(nom, nom):<26} {mes['ic']:>+7.3f} "
            f"{mes['ir']:>+6.2f} "
            f"{mes['periodes_positives']:>5} / {mes['periodes']:<4} "
            f"{mes['pire']:>+7.3f}")
    lignes += [
        "",
        "L'IR — IC moyen divisé par son écart-type entre périodes — est la "
        "mesure de fiabilité : deux sources au même IC ne se valent pas si "
        "l'une le réalise à chaque période et l'autre une fois sur deux.",
        "",
        f"L'intervalle des IC ci-dessus couvre deux erreurs-types, calculées "
        f"sur {m['dates_independantes']} périodes disjointes et non sur les "
        f"{m['dates']} dates de test : avec un horizon de "
        f"{validation['horizon']} séances, deux dates voisines racontent "
        "la même histoire.",
        "",
    ]

    poids = validation.get("poids_fiabilite") or {}
    if poids:
        lignes.append("Poids appris par trait, rétrécis par la force de la preuve :")
        for trait, valeur in sorted(poids.items(), key=lambda kv: -abs(kv[1])):
            marque = "  (mis à zéro)" if abs(valeur) < 1e-4 else ""
            lignes.append(f"  {trait:<14} {valeur:+.4f}{marque}")
        lignes.append("")

    mesures = validation.get("traits_mesures") or {}
    if mesures:
        lignes.append("Ce que vaut chaque trait, pris séparément :")
        for trait, mes in mesures.items():
            lignes.append(f"  {trait:<14} {_avec_incertitude(mes)}")
        if not any(mes["significatif"] for mes in mesures.values()):
            lignes += [
                "",
                "AUCUN TRAIT NE SE DISTINGUE DU HASARD sur les seules "
                "périodes de test. Le classement reste une description du "
                "marché — qui a monté, qui s'échange — mais rien ici "
                "n'autorise à en attendre un rendement.",
            ]
        lignes.append("")

    if validation["retenue"] == "composite":
        lignes.append(
            "LA COMBINAISON N'A PAS D'IC POSITIF HORS ÉCHANTILLON : c'est le "
            "score composite qui part en production, faute de mieux. Il "
            "n'estime rien, donc il ne peut pas surajuster."
        )
    elif validation["ic"] > 0.30:
        lignes.append(
            "IC anormalement élevé pour ce problème : cherchez une fuite "
            "avant d'y croire. Un IC exploitable se situe entre 0,02 et 0,05."
        )
    elif np.isfinite(stab["ir"]):
        lignes.append(
            f"La combinaison part en production : IC {stab['ic']:+.3f}, IR "
            f"{stab['ir']:+.2f}, positive sur {stab['periodes_positives']} "
            f"des {stab['periodes']} périodes de test. "
            "CELA NE LA REND PAS RENTABLE : à 3 % l'aller-retour, un écart "
            "d'IC de cette taille ne survit pas à la rotation qu'il exige — "
            "voir l'onglet Backtest, et l'en-tête de ce module."
        )
    lignes += [""] + [f"  - {a}" for a in validation["avertissements"]]
    return "\n".join(lignes)
