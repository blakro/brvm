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
    "backtest": {
        "positions": 10,
        # ~un mois de séances entre deux rééquilibrages.
        "pas_rebalancement": 20,
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
