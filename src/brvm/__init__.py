"""Cours de la Bourse Régionale des Valeurs Mobilières : collecte et analyse.

Deux sources, deux natures. brvm.org publie la cote du jour et fait
autorité sur la clôture ; sikafinance publie l'historique depuis 2015 avec
l'OHLC, et quatre exercices de dividendes. La primauté entre elles se joue
colonne par colonne — voir `db.fusionner_cours`.

L'archive CSV versionnée est la source de vérité ; la base SQLite s'en
reconstruit et n'est jamais versionnée.
"""

__version__ = "0.2.0"
