"""Configuration du projet : racine sur le disque et réglages.

Un fichier de configuration est facultatif. Tous les réglages ont un défaut
utilisable, parce qu'un projet qui refuse de démarrer sans `config.toml`
oblige à recopier un exemple avant de pouvoir seulement lancer le
diagnostic — et c'est le diagnostic qu'on veut lancer en premier quand
quelque chose ne va pas.

TOML plutôt que YAML : `tomllib` est dans la bibliothèque standard depuis
Python 3.11, là où YAML ajouterait une dépendance pour lire une vingtaine
de lignes.

Deux variables d'environnement priment sur le fichier :

    BRVM_CONFIG   chemin d'un autre fichier de configuration
    BRVM_BASE     chemin de la base SQLite

`BRVM_BASE` existe pour les tests et les exécutions jetables : sans elle,
une suite de tests qui appelle `ingerer_jour()` écrirait dans la base du
projet.
"""

from __future__ import annotations

import os
import tomllib
from copy import deepcopy
from pathlib import Path

# src/brvm/config.py → src/brvm → src → racine du dépôt.
RACINE = Path(__file__).resolve().parents[2]

DEFAUTS: dict[str, dict] = {
    "ingestion": {
        # Un agent identifiable : si le scraping gêne brvm.org, autant
        # qu'ils sachent qui appeler plutôt que de bloquer une plage d'IP.
        "user_agent": "brvm-conseil/0.1 (+https://github.com/blakro/brvm)",
        # Politesse entre deux requêtes. La cote tient en une requête et le
        # secteur en sept ; ralentir de 1,5 s ne coûte rien ici.
        "delai_entre_requetes_s": 1.5,
        # Heure à partir de laquelle une séance du jour est considérée
        # close. Sert de garde-fou dans `ingerer_jour` : avant elle, la
        # colonne « Cours Clôture » de brvm.org porte le dernier cours
        # traité, pas la clôture.
        "heure_cloture_seance": "15:00",
    },
    "base": {
        "chemin": "data/brvm.db",
        # Source de vérité versionnée. La base SQLite en est dérivée et se
        # reconstruit par `brvm importer` : c'est le CSV qui est sauvegardé
        # par git, pas le binaire.
        "archive_cours": "data/cours.csv",
        "archive_referentiel": "data/referentiel.csv",
        "archive_dividendes": "data/dividendes.csv",
        "archive_fondamentaux": "data/fondamentaux.csv",
        "archive_exogenes": "data/exogenes.csv",
    },
    "analyse": {
        # Seuil de liquidité, en FCFA de volume médian quotidien. Une
        # valeur qui ne s'échange pas ne se vend pas non plus : la scorer
        # reviendrait à recommander une position dont on ne sortira pas.
        #
        # À CALIBRER. 1 million de FCFA (~1 500 €) est un ordre de grandeur
        # bas, choisi pour ne presque rien écarter tant que la série est
        # courte. Le relever demande de savoir combien de valeurs restent
        # éligibles sur plusieurs mois — donc d'attendre les données.
        "volume_median_min_fcfa": 1_000_000,
        # Momentum « 12-1 » : rendement sur un an, en sautant le dernier
        # mois. Le saut n'est pas un détail — voir features.momentum.
        "fenetre_momentum": 250,
        "saut_momentum": 20,
        "fenetre_volatilite": 60,
        "fenetre_liquidite": 60,
        "moyenne_courte": 20,
        "moyenne_longue": 100,
        # En deçà, un secteur est trop peu peuplé pour que comparer ses
        # membres entre eux ait un sens : « Services Publics » compte deux
        # sociétés. Ceux-là sont notés face au marché entier.
        "min_par_secteur": 5,
    },
    "prediction": {
        # Horizon en séances — environ une semaine de cotation.
        #
        # PAS UN HORIZON JOURNALIER, ET C'EST STRUCTUREL. La BRVM cote par
        # fixing, avec une limite de variation de ±7,5 % et des lignes qui
        # ne s'échangent parfois que quelques fois par semaine. Sur des
        # cours ainsi figés, un modèle apprend « demain ≈ aujourd'hui », en
        # tire un R² magnifique, et produit un backtest brillant et
        # inexécutable. Le signal exploitable est à un à six mois.
        #
        # CINQ SÉANCES. Mesuré sur le rendement de COURS seul, sur les
        # seules valeurs négociables (médiane de volume au moins 1 M FCFA),
        # avec le modèle livré et les deux moitiés d'archive pour juges :
        #
        #   horizon      IC      IR   périodes+   avantage/an   1re moit.  2nde
        #         5  +0,0768  +1,84      10/10      +15,50 %     +16,5 %  +14,5 %
        #        10  +0,0705  +1,40       8/10      +10,95 %     +11,4 %  +10,5 %
        #        20  +0,0738  +1,51       9/10       +7,72 %      +9,1 %   +6,3 %
        #        40  +0,0483  +0,99       8/10       +4,13 %      +5,3 %   +2,9 %
        #        60  +0,0599  +0,88       9/10       +3,61 %      +4,2 %   +3,1 %
        #
        # Cinq séances gagne sur TOUTES les colonnes comparables entre
        # horizons — l'IC par période, l'IR, le nombre de périodes positives,
        # et l'équilibre entre les deux moitiés. Le `t` n'en fait pas partie :
        # il croît en racine de l'inverse de l'horizon, puisque l'erreur-type
        # se calcule sur `dates / horizon` blocs disjoints. À cinq séances il
        # y a quatre fois plus de blocs qu'à vingt, donc quatre fois plus de
        # puissance à effet égal.
        #
        # PAS JOURNALIER POUR AUTANT, et la raison est structurelle. La BRVM
        # cote par fixing avec une limite de ±7,5 % et des lignes qui ne
        # s'échangent parfois que quelques fois par semaine. Sur des cours
        # ainsi figés, un modèle entraîné sur le lendemain apprend « demain ≈
        # aujourd'hui », en tire un R² magnifique et produit un backtest
        # brillant et inexécutable.
        #
        # DEUX CONTRÔLES DÉCIDENT QUE CINQ N'EST PAS CE PIÈGE-LÀ.
        #
        # Le délai d'exécution d'abord : on ne peut pas acheter au cours qui
        # a servi à décider, il est connu après la clôture. Avantage annualisé
        # selon la séance d'entrée :
        #
        #   horizon    t+0       t+1       t+2       t+3
        #         5  +15,50 %  +12,05 %   +9,20 %   +7,12 %
        #        20   +7,72 %   +6,94 %   +6,17 %   +5,20 %
        #
        # Cinq séances avec TROIS séances de retard égale encore vingt séances
        # sans retard. Un effet de rebond de fourchette se serait effondré dès
        # la première.
        #
        # Les cours reportés ensuite : 5,3 % des étiquettes en reposent sur
        # un, et restreindre la mesure aux cours réellement traités en t+H ne
        # change rien (+15,40 % contre +15,50 %). Ce n'est donc pas un
        # artefact de cours figé.
        #
        # CE QUI A ÉTÉ CORRIGÉ EN CHEMIN. L'horizon a d'abord été fixé à
        # vingt, en partie parce que le balayage de `recherche.py` désignait
        # le choc de volume « à vingt séances » : deux analyses indépendantes,
        # disait-on, pointaient le même horizon. Or la grille du balayage
        # était (20, 60, 120) — vingt était le plus court horizon qu'on lui
        # autorisait, et il ne pouvait pas en désigner un autre. L'argument
        # était circulaire. La grille contient désormais 5 et 10, et le
        # balayage place ses cases les plus fortes à cinq séances.
        #
        # À NE PAS CONFONDRE AVEC `pas_rebalancement`, qui dit à quelle
        # fréquence on ACHÈTE et que les frais commandent — voir plus bas.
        # Prévoir à une semaine n'oblige pas à tourner toutes les semaines.
        "horizon": 5,
        # Périodes de test successives de la validation glissante.
        #
        # DIX ET NON QUATRE, ET C'ÉTAIT UN DÉFAUT DE MESURE. Avec quatre
        # découpes, l'IC d'une période à l'autre allait de +0,29 à -0,28 sur
        # l'archive : on concluait sur quatre tirages d'une variable dont
        # l'écart-type dépasse la moyenne d'un ordre de grandeur, et la
        # conclusion changeait à chaque séance versée. Dix découpes ne
        # rendent pas la mesure précise — rien ne peut — mais elles rendent
        # sa DISPERSION visible, et c'est elle qu'il faut lire.
        "decoupes": 10,
        # En deçà, on ne valide ni ne prédit.
        "lignes_minimum": 400,
        # Exigence de preuve du rétrécissement des poids par trait : le poids
        # d'un trait vaut son IC × t²/(t² + exigence). À 4, un trait au seuil
        # usuel de signification (t = 2) garde la moitié de son poids, et un
        # trait sans preuve n'en garde rien. Voir apprentissage.poids_fiabilite.
        "exigence_preuve": 4.0,
        # Membres du sac de régressions. Il ne sert PAS à la précision —
        # mesuré, il ne la change pas d'un millième — mais à chiffrer
        # l'incertitude de chaque probabilité par la dispersion entre
        # membres. Huit suffisent à un écart-type lisible ; au-delà on paie
        # du temps de calcul pour une décimale.
        "membres_sac": 8,
    },
    "exogenes": {
        # Variation mesurée sur ~3 mois, décalée de ~2 mois.
        #
        # Le décalage n'est pas un réglage fin : une hausse du caoutchouc
        # n'atteint pas le cours de la SAPH le lendemain, elle passe
        # d'abord dans les marges puis dans des résultats publiés
        # trimestriellement. Un à trois mois est l'hypothèse de travail, à
        # revoir quand il y aura de quoi la tester.
        "fenetre_variation": 60,
        "retard": 40,
        # Série → secteur qu'elle concerne. Une série absente de la base est
        # simplement ignorée ; ce tableau décrit l'intention, pas l'état.
        #
        # Les noms de séries sont libres : ce sont ceux qu'on emploiera en
        # important les CSV. Aucune source n'est joignable depuis ce projet,
        # les données doivent donc être fournies (voir README).
        "correspondance": {
            "caoutchouc_tsr20": "Consommation de Base",
            "huile_palme_cpo": "Consommation de Base",
            "sucre": "Consommation de Base",
            "eur_usd": "Consommation de Base",
            "taux_bceao": "Services Financiers",
        },
    },
    "backtest": {
        "positions": 10,
        # ~un trimestre entre deux rééquilibrages.
        #
        # LES FRAIS COMMANDENT CETTE VALEUR, PAS LA FINESSE DU SIGNAL. Le
        # courtage SGI va de 0,5 % à 1,2 % selon l'intermédiaire, plus une
        # rétrocession BRVM de 0,2 %, les frais DC/BR et les taxes : de 2,5
        # à 3,5 % l'aller-retour. Un rééquilibrage mensuel les paie douze
        # fois l'an, soit plus de trente points de performance à rattraper
        # avant de gagner un centime. Quatre fois par an est déjà
        # ambitieux ; c'est le plancher qu'impose ce marché.
        #
        # SOIXANTE ALORS QUE LE MODÈLE PRÉDIT À VINGT, ET C'EST MESURÉ, PAS
        # UN OUBLI. Prédire à un mois n'oblige pas à tourner tous les mois :
        # le signal du mois se conserve, les frais du mois non. Rejeu du
        # modèle livré sur le COURS SEUL, écart annuel contre l'univers :
        #
        #     pas    frais nuls   0,25 %   1,50 %   seuil
        #       5        +9,3 %    -1,3 %  -42,5 %   0,22 %
        #      20        +3,3 %    -0,8 %  -19,0 %   0,20 %
        #      60        +8,0 %    +6,5 %   -0,5 %   1,40 %
        #
        # LE SIGNAL SE CONSERVE BIEN AU-DELÀ DE SON HORIZON DE MESURE, et
        # c'est le résultat le plus utile du tableau. Prédit à cinq séances,
        # détenu soixante, il garde l'essentiel de son avantage tout en
        # payant la rotation douze fois moins souvent : son seuil de
        # rentabilité est de 1,40 % par sens contre 0,22 % si l'on tourne à
        # la semaine. C'est ce seuil qui décide, parce que c'est lui qu'on
        # compare au devis d'une SGI — et il est passé de 0,54 % à 1,40 %
        # avec le raccourcissement de l'horizon de prédiction, soit à portée
        # des 1,50 % facturés.
        #
        # (Sur soixante rééquilibrages, ces chiffres ne sont pas fins. C'est
        # l'ordre de grandeur qui tranche, pas la décimale.)
        "pas_rebalancement": 60,
        # On décide sur la clôture de t et on achète à celle de t+1. Se
        # servir du même cours pour décider et pour exécuter suppose de
        # passer un ordre à un cours déjà connu : c'est le regard en avant
        # le plus courant, et il embellit les résultats sans bruit.
        "delai_execution": 1,
        # ORDRES DE GRANDEUR, À VÉRIFIER AUPRÈS DE VOTRE SGI. Les
        # commissions de la BRVM se comptent en pourcents, pas en points de
        # base comme sur les places développées — un backtest qui les
        # ignore est une fiction, d'autant plus qu'un portefeuille
        # rééquilibré tous les mois les paie douze fois par an.
        "frais_pourcent": 1.0,
        # Écart entre le cours affiché et le cours réellement obtenu, sur
        # des lignes qui ne s'échangent parfois pas tous les jours.
        "impact_pourcent": 0.5,
        # Zone tampon : une ligne détenue est conservée tant qu'elle reste
        # dans les `positions × tampon` premiers, au lieu d'être vendue dès
        # qu'elle quitte les `positions` premiers. À 1, pas de tampon.
        #
        # LE DÉFAUT RESTE 1, ET C'EST UN RÉSULTAT, PAS UNE OMISSION. Le
        # tampon réduit bien la rotation — de 64 % à 17 % à 3,0 — mais
        # l'avantage baisse avec elle, et aucun réglage n'est positif hors
        # échantillon : celui que la première moitié de l'archive désigne
        # (3,0) est parmi les pires sur la seconde. Le détail chiffré est
        # dans `backtest.backtester`, à l'endroit où le tampon s'applique.
        # Le réglage existe pour qu'on puisse refaire la mesure.
        "tampon": 1.0,
    },
    # Contribution de chaque trait au score. Le signe compte : la
    # volatilité pénalise.
    #
    # CES POIDS SONT UN POINT DE DÉPART, PAS UNE STRATÉGIE VALIDÉE. Ils
    # traduisent un parti pris ordinaire — suivre la tendance, préférer le
    # calme — et n'ont été calibrés sur rien : la base ne contient pas
    # encore d'historique à backtester.
    "ponderations": {
        "momentum": 0.5,
        "tendance": 0.3,
        "volatilite": -0.2,
    },
}


def _fichier() -> Path:
    return Path(os.environ.get("BRVM_CONFIG") or RACINE / "config.toml")


def charger() -> dict:
    """Réglages effectifs : défauts, écrasés section par section.

    La fusion est faite clé à clé et non section à section : déclarer un
    seul réglage d'`ingestion` dans le fichier ne doit pas faire perdre les
    autres.
    """
    reglages = deepcopy(DEFAUTS)

    fichier = _fichier()
    if fichier.exists():
        with fichier.open("rb") as flux:
            lu = tomllib.load(flux)
        for section, valeurs in lu.items():
            if isinstance(valeurs, dict):
                reglages.setdefault(section, {}).update(valeurs)
            else:
                reglages[section] = valeurs

    return reglages


def chemin_base() -> Path:
    """Chemin de la base SQLite, absolu.

    `BRVM_BASE` l'emporte sur la configuration, qui l'emporte sur le
    défaut. Un chemin relatif est résolu depuis la racine du dépôt, pas
    depuis le répertoire courant : le cron ne s'exécute pas forcément
    depuis la racine, et une base créée au hasard des répertoires est une
    base perdue.
    """
    brut = os.environ.get("BRVM_BASE") or charger()["base"]["chemin"]
    chemin = Path(brut).expanduser()
    return chemin if chemin.is_absolute() else RACINE / chemin
