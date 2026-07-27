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
