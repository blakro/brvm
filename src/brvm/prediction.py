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

TROIS PIÈGES, ET COMMENT ILS SONT FERMÉS
----------------------------------------
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

CE QUE VOUS DEVEZ EN ATTENDRE
-----------------------------
La référence n'est pas le hasard : c'est le score composite de
`scoring.py`, momentum et liquidité sans apprentissage. Sur ce marché, un
composite simple bat très souvent un modèle appris — et s'il gagne ici, LE
COMPOSITE EST CE QUI DOIT PARTIR EN PRODUCTION. L'apprentissage n'ajouterait
qu'un risque de surajustement et une dépendance de plus.

L'IC attendu d'un modèle honnête se situe entre 0,02 et 0,05 ; 0,10 est
excellent. Au-delà de 0,30, cherchez le bug avant d'ouvrir le champagne.

Enfin, un écart positif ne suffit pas à gagner de l'argent : le courtage
SGI, la rétrocession BRVM, les frais DC/BR et les taxes font 2,5 à 3,5 %
l'aller-retour. Le signal doit survivre à cela — c'est ce que mesure
`backtest.py`, pas ce module.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import exogene, features
from .config import charger

# Traits utilisés. Volontairement peu nombreux et déjà éprouvés ailleurs
# dans le projet : multiplier les entrées sur 47 valeurs est le moyen le
# plus rapide de mémoriser le passé au lieu de l'apprendre.
TRAITS = ["momentum", "tendance", "volatilite", "liquidite"]

AVERTISSEMENTS = (
    "cible : surperformer le marché, pas monter",
    "validation glissante avec purge des étiquettes recouvrantes",
    "référence : le score composite sans apprentissage, qui gagne souvent",
    "IC exploitable : 0,02 à 0,05 ; au-delà de 0,30, cherchez la fuite",
    "frais non comptés ici : 2,5 à 3,5 % l'aller-retour sur ce marché",
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


def construire_echantillon(
    cours: pd.DataFrame, reglages: dict | None = None
) -> pd.DataFrame:
    """Une ligne par (date, ticker) : traits connus en t, étiquette en t+H.

    L'étiquette vaut 1 si la valeur bat la médiane des rendements de la
    séance sur l'horizon, 0 sinon.
    """
    conf = reglages or charger()
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

    lignes = []
    for i in range(besoin - 1, len(dates) - horizon):
        date = dates[i]
        traits = pd.DataFrame(
            {nom: matrices[nom].loc[date] for nom in TRAITS}
        ).dropna(subset=["momentum", "tendance", "volatilite"])
        if traits.empty:
            continue

        futur = prix.iloc[i + horizon] / prix.iloc[i] - 1
        futur = futur.replace([np.inf, -np.inf], np.nan).reindex(traits.index)
        valides = futur.dropna()
        if len(valides) < 4:
            continue

        bloc = pd.DataFrame({t: _rangs(traits.loc[valides.index, t])
                             for t in TRAITS})
        bloc["cible"] = (valides > valides.median()).astype(int)
        # Le rendement réalisé est conservé tel quel : c'est lui qui sert à
        # l'IC, qui mesure l'ordre prédit et non une frontière binaire.
        bloc["rendement_futur"] = valides.to_numpy()
        bloc["date"] = date
        bloc["ticker"] = valides.index
        lignes.append(bloc)

    if not lignes:
        return pd.DataFrame()
    return pd.concat(lignes, ignore_index=True)


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
    """La référence à battre : somme pondérée des rangs, sans apprentissage.

    C'est le score de `scoring.py`, recalculé ici sur les mêmes traits. Sur
    ce marché, un composite simple bat très souvent un modèle appris ; s'il
    le bat encore ici, c'est lui qui doit partir en production, et le
    module de prédiction n'est qu'une vérification coûteuse.
    """
    utiles = {t: p for t, p in poids.items() if t in bloc.columns}
    if not utiles:
        return pd.Series(0.0, index=bloc.index)
    total = sum(abs(p) for p in utiles.values()) or 1.0
    return sum(p * bloc[t] for t, p in utiles.items()) / total


def _modele():
    """Régression logistique standardisée, volontairement bridée.

    Pas de forêt ni de gradient boosting : sur quelques milliers de lignes
    issues de 47 valeurs corrélées entre elles, un modèle souple apprend le
    bruit et le restitue comme un signal. La régularisation est laissée
    forte (C petit) pour la même raison.
    """
    return make_pipeline(
        StandardScaler(),
        LogisticRegression(C=0.1, max_iter=1000),
    )


def valider(
    cours: pd.DataFrame,
    reglages: dict | None = None,
    exogenes: pd.DataFrame | None = None,
    referentiel: pd.DataFrame | None = None,
) -> dict:
    """Validation glissante, purgée. Renvoie mesures et détail par période."""
    conf = reglages or charger()
    pred = conf.get("prediction", {})
    poids = conf.get("ponderations", {})
    horizon = int(pred.get("horizon", 60))
    decoupes = int(pred.get("decoupes", 4))
    minimum = int(pred.get("lignes_minimum", 400))

    echantillon = construire_echantillon(cours, conf)
    echantillon, exo = _joindre_exogenes(echantillon, exogenes, referentiel, conf)
    traits = TRAITS + exo
    vide = {
        "periodes": pd.DataFrame(),
        "traits": traits,
        "lignes": len(echantillon),
        "lignes_minimum": minimum,
        "horizon": horizon,
        "avertissements": AVERTISSEMENTS,
    }
    if len(echantillon) < minimum:
        return vide

    dates = sorted(echantillon["date"].unique())
    if len(dates) < decoupes + 2:
        return vide

    frontieres = np.array_split(np.array(dates), decoupes + 1)
    resultats = []
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

        modele = _modele()
        modele.fit(train[traits], train["cible"])
        test = test.copy()
        test["score_modele"] = modele.predict_proba(test[traits])[:, 1]
        test["score_composite"] = _score_composite(test, poids)

        # L'IC se calcule séance par séance puis se moyenne : agrégé d'un
        # coup, il mélangerait les écarts entre dates avec les écarts entre
        # valeurs, et mesurerait surtout le marché.
        par_seance = test.groupby("date")
        ic_modele = par_seance.apply(
            lambda g: _ic(g["score_modele"], g["rendement_futur"]),
            include_groups=False,
        ).mean()
        ic_composite = par_seance.apply(
            lambda g: _ic(g["score_composite"], g["rendement_futur"]),
            include_groups=False,
        ).mean()

        prevu = (test["score_modele"] >= 0.5).astype(int)
        resultats.append({
            "periode": f"{min(frontieres[rang])} → {max(frontieres[rang])}",
            "lignes_entrainement": len(train),
            "lignes_test": len(test),
            "ic_modele": float(ic_modele),
            "ic_composite": float(ic_composite),
            "precision": float((prevu == test["cible"]).mean()),
        })

    if not resultats:
        return vide

    periodes = pd.DataFrame(resultats)
    ic = float(periodes["ic_modele"].mean())
    ic_composite = float(periodes["ic_composite"].mean())
    return {
        "periodes": periodes,
        "traits": traits,
        "lignes": len(echantillon),
        "horizon": horizon,
        "ic": ic,
        "ic_composite": ic_composite,
        "ecart": ic - ic_composite,
        "precision": float(periodes["precision"].mean()),
        "avertissements": AVERTISSEMENTS,
    }


def predire(
    cours: pd.DataFrame,
    reglages: dict | None = None,
    exogenes: pd.DataFrame | None = None,
    referentiel: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Probabilité de battre la médiane, par valeur, à la dernière date.

    Entraîné sur tout l'historique disponible. Renvoie un tableau vide si
    l'échantillon est trop maigre — une probabilité tirée de deux cents
    lignes serait un nombre, pas une prévision.
    """
    conf = reglages or charger()
    pred = conf.get("prediction", {})
    minimum = int(pred.get("lignes_minimum", 400))

    echantillon = construire_echantillon(cours, conf)
    echantillon, exo = _joindre_exogenes(echantillon, exogenes, referentiel, conf)
    traits_utiles = TRAITS + exo
    if len(echantillon) < minimum or echantillon["cible"].nunique() < 2:
        return pd.DataFrame(columns=["ticker", "probabilite"])

    modele = _modele()
    modele.fit(echantillon[traits_utiles], echantillon["cible"])

    traits = features.calculer(cours, conf).dropna(
        subset=["momentum", "tendance", "volatilite"]
    )
    if traits.empty:
        return pd.DataFrame(columns=["ticker", "probabilite"])

    courant = pd.DataFrame({t: _rangs(traits[t]) for t in TRAITS})
    # Les colonnes exogènes de la date courante : mêmes noms, valeur du
    # jour, zéro hors du secteur visé.
    for colonne in exo:
        derniere = echantillon[echantillon["date"] == echantillon["date"].max()]
        par_ticker = derniere.set_index("ticker")[colonne]
        courant[colonne] = courant.index.map(par_ticker).fillna(0.0)
    resultat = pd.DataFrame({
        "ticker": traits.index,
        "probabilite": modele.predict_proba(courant[traits_utiles])[:, 1],
    })
    return resultat.sort_values("probabilite", ascending=False).reset_index(drop=True)


def expliquer(validation: dict) -> str:
    """Rendu texte. La référence n'est jamais séparée de la précision."""
    if validation["periodes"].empty:
        return (
            f"Pas assez de données pour valider : {validation['lignes']} "
            f"observations, {validation['lignes_minimum']} au minimum. "
            "Chaque séance ajoute une quarantaine de lignes, mais il faut "
            "d'abord un an de cotation avant que la première soit "
            "calculable — le momentum se mesure sur cette durée."
        )

    lignes = [
        f"Horizon : {validation['horizon']} séances (~"
        f"{validation['horizon'] // 20} mois). {validation['lignes']} "
        f"observations, {len(validation['periodes'])} périodes de test.",
        "",
        f"  IC du modèle           {validation['ic']:+.3f}",
        f"  IC du score composite  {validation['ic_composite']:+.3f}",
        f"  écart                  {validation['ecart']:+.3f}",
        f"  (précision binaire     {validation['precision']:.1%})",
        "",
    ]
    if validation["ecart"] <= 0:
        lignes.append(
            "LE MODÈLE NE BAT PAS LE SCORE COMPOSITE. C'est le cas le plus "
            "fréquent sur ce marché, et ce n'est pas un échec du code : "
            "c'est le composite qui doit partir en production, l'apprentissage "
            "n'ajoutant qu'un risque de surajustement."
        )
    elif validation["ic"] > 0.30:
        lignes.append(
            "IC anormalement élevé pour ce problème : cherchez une fuite "
            "avant d'y croire. Un IC exploitable se situe entre 0,02 et 0,05."
        )
    else:
        lignes.append(
            "Le modèle devance le composite. Cela ne le rend pas rentable "
            "pour autant : à 2,5–3,5 % l'aller-retour, l'écart doit survivre "
            "aux frais avant de valoir quoi que ce soit — voir l'onglet "
            "Backtest."
        )
    lignes += [""] + [f"  - {a}" for a in validation["avertissements"]]
    return "\n".join(lignes)
