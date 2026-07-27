"""Persistance SQLite. Une seule fonction d'écriture : `enregistrer`.

SQLite parce que la BRVM cote 47 valeurs : après dix ans de séances
quotidiennes, la table `cours` compte environ 120 000 lignes. Un fichier
unique, sans serveur, se sauvegarde par une copie et se lit depuis
n'importe quel outil.

DEUX PARTIS PRIS
----------------

1. LES SCHÉMAS SONT DÉCLARÉS ICI, PAS DÉDUITS DES DONNÉES. `to_sql` de
   pandas crée des colonnes d'après le type deviné du DataFrame : une
   colonne entièrement vide arrive en TEXT un jour et en REAL le
   lendemain, et la clé primaire n'existe jamais. Les tables ci-dessous
   sont créées une fois, avec leurs types et leurs clés.

2. RÉÉCRIRE UNE SÉANCE EST SANS DANGER. `cours` a pour clé (date, ticker)
   et l'écriture est un INSERT OR REPLACE. Relancer l'ingestion du même
   jour corrige la ligne au lieu de la dupliquer — ce qui arrive dès qu'on
   réingère après avoir corrigé un sélecteur.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .config import chemin_base

# Clé = nom de table. Valeur = (DDL, colonnes dans l'ordre du DDL).
#
# `journal_ingestion` n'a volontairement pas de clé primaire : c'est un
# journal, deux lignes identiques à la même seconde sont deux événements.
SCHEMAS: dict[str, str] = {
    "cours": """
        CREATE TABLE IF NOT EXISTS cours (
            date          TEXT NOT NULL,
            ticker        TEXT NOT NULL,
            ouverture     REAL,
            haut          REAL,
            bas           REAL,
            cloture       REAL NOT NULL,
            volume_titres REAL,
            volume_fcfa   REAL,
            PRIMARY KEY (date, ticker)
        )
    """,
    "referentiel": """
        CREATE TABLE IF NOT EXISTS referentiel (
            ticker  TEXT PRIMARY KEY,
            nom     TEXT NOT NULL,
            secteur TEXT
        )
    """,
    "journal_ingestion": """
        CREATE TABLE IF NOT EXISTS journal_ingestion (
            horodatage TEXT NOT NULL,
            source     TEXT NOT NULL,
            lignes     INTEGER,
            statut     TEXT,
            message    TEXT
        )
    """,
}

INDEX = [
    # Le backtest lit une série par ticker ; sans cet index chaque lecture
    # parcourt toute la table.
    "CREATE INDEX IF NOT EXISTS idx_cours_ticker ON cours (ticker, date)",
]


class SchemaInconnu(KeyError):
    """Écriture demandée dans une table qui n'est pas déclarée ici."""


def connexion(chemin: str | Path | None = None) -> sqlite3.Connection:
    """Connexion à la base, répertoire créé et schéma en place.

    Idempotent : toutes les instructions sont des CREATE ... IF NOT EXISTS,
    donc chaque appel peut être le premier.
    """
    fichier = Path(chemin) if chemin is not None else chemin_base()
    fichier.parent.mkdir(parents=True, exist_ok=True)

    cnx = sqlite3.connect(fichier)
    # Journalisation WAL : le tableau de bord peut lire pendant que le cron
    # écrit, au lieu de se heurter à « database is locked ».
    cnx.execute("PRAGMA journal_mode=WAL")
    for ddl in SCHEMAS.values():
        cnx.execute(ddl)
    for ddl in INDEX:
        cnx.execute(ddl)
    cnx.commit()
    return cnx


def _colonnes(cnx: sqlite3.Connection, table: str) -> list[str]:
    return [ligne[1] for ligne in cnx.execute(f"PRAGMA table_info({table})")]


def enregistrer(df: pd.DataFrame, table: str, chemin: str | Path | None = None) -> int:
    """Écrit `df` dans `table` et renvoie le nombre de lignes écrites.

    Les colonnes absentes du DataFrame sont écrites à NULL, les colonnes en
    trop sont ignorées : l'appelant n'a pas à connaître le schéma exact, et
    ajouter une colonne au scraper ne casse pas l'écriture avant la
    migration de la table.
    """
    if table not in SCHEMAS:
        raise SchemaInconnu(
            f"table « {table} » inconnue — déclarez son schéma dans "
            "src/brvm/db.py plutôt que de la laisser créer à la volée."
        )
    if df is None or df.empty:
        return 0

    cnx = connexion(chemin)
    try:
        colonnes = _colonnes(cnx, table)
        retenues = [c for c in colonnes if c in df.columns]
        if not retenues:
            raise SchemaInconnu(
                f"aucune colonne de {list(df.columns)} ne correspond à "
                f"{table} {colonnes}"
            )

        donnees = df.reindex(columns=colonnes)
        # NaN de pandas → NULL de SQLite. Sans cela, sqlite3 refuse
        # d'insérer un float('nan') dans une colonne REAL contrainte.
        donnees = donnees.astype(object).where(pd.notna(donnees), None)

        marques = ", ".join("?" * len(colonnes))
        cnx.executemany(
            f"INSERT OR REPLACE INTO {table} ({', '.join(colonnes)}) "
            f"VALUES ({marques})",
            donnees.itertuples(index=False, name=None),
        )
        cnx.commit()
        return len(donnees)
    finally:
        cnx.close()


def lire(table: str, chemin: str | Path | None = None) -> pd.DataFrame:
    """Table entière, dans un DataFrame. Vide si la table est vide."""
    if table not in SCHEMAS:
        raise SchemaInconnu(f"table « {table} » inconnue")
    cnx = connexion(chemin)
    try:
        return pd.read_sql_query(f"SELECT * FROM {table}", cnx)
    finally:
        cnx.close()


def resume(chemin: str | Path | None = None) -> dict[str, int]:
    """Nombre de lignes par table — ce que l'onglet « Données » affiche."""
    cnx = connexion(chemin)
    try:
        return {
            table: cnx.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in SCHEMAS
        }
    finally:
        cnx.close()
