"""Ligne de commande du projet.

    python -m brvm verifier              diagnostic des sélecteurs
    python -m brvm verifier page.html    idem, sur une page enregistrée
    python -m brvm ingerer               enregistre la séance publiée
    python -m brvm referentiel           met à jour ticker / nom / secteur
    python -m brvm noter                 classe les valeurs
    python -m brvm backtester            rejoue le classement dans le temps
    python -m brvm exporter              base → CSV versionnés
    python -m brvm importer              CSV versionnés → base
    python -m brvm etat                  ce que contient la base

Chaque commande rend 0 en cas de succès et 1 en cas d'échec, pour qu'un
cron ou une action GitHub sache qu'il s'est passé quelque chose sans avoir
à lire la sortie.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import backtest, db, dividende, exogene, features, prediction, scoring
from .ingestion import brvm_org


def _verifier(args) -> int:
    resultat = brvm_org.verifier(args.source)
    largeur = max(len(cle) for cle in resultat)
    for cle, valeur in resultat.items():
        print(f"{cle:<{largeur}}  {valeur}")
    return 0 if resultat.get("ok") else 1


def _ingerer(args) -> int:
    try:
        lignes = brvm_org.ingerer_jour()
    except brvm_org.SourceIllisible as erreur:
        # Refus attendu — séance en cours, page illisible. Le message dit
        # quoi faire, il n'y a rien à ajouter.
        print(f"ingestion refusée : {erreur}", file=sys.stderr)
        return 1
    print(f"{lignes} lignes de cote enregistrées")
    return 0


def _referentiel(args) -> int:
    ref = brvm_org.referentiel()
    origine = "brvm.org"
    if ref.empty:
        ref = brvm_org.referentiel_amorce()
        origine = "amorce locale"
    if ref.empty:
        print("référentiel introuvable, y compris l'amorce", file=sys.stderr)
        return 1

    db.enregistrer(ref, "referentiel")
    classees = int(ref["secteur"].notna().sum())
    print(f"{len(ref)} sociétés enregistrées depuis {origine}, "
          f"{classees} avec secteur")
    return 0


def _noter(args) -> int:
    cours = db.lire("cours")
    if cours.empty:
        print("aucun cours en base — lancez « brvm ingerer »", file=sys.stderr)
        return 1

    traits = features.calculer(cours)
    referentiel = db.lire("referentiel")
    classement = scoring.noter(traits, referentiel)

    print(f"Séance du {traits.attrs.get('date', '?')} — "
          f"{traits.attrs.get('seances', 0)} séances en base")
    print(scoring.expliquer(classement, args.nombre))
    return 0 if not classement.empty else 1


def _backtester(args) -> int:
    cours = db.lire("cours")
    if cours.empty:
        print("aucun cours en base — lancez « brvm ingerer »", file=sys.stderr)
        return 1

    resultat = backtest.backtester(cours, db.lire("referentiel"))
    print(backtest.expliquer(resultat))
    if args.journal and not resultat["etapes"].empty:
        print("\nJournal des rééquilibrages :")
        print(resultat["etapes"].to_string(index=False))
    return 0 if not resultat["etapes"].empty else 1


def _predire(args) -> int:
    cours = db.lire("cours")
    if cours.empty:
        print("aucun cours en base — lancez « brvm ingerer »", file=sys.stderr)
        return 1

    validation = prediction.valider(cours)
    print(prediction.expliquer(validation))

    classement = prediction.predire(cours)
    if classement.empty:
        return 1

    referentiel = db.lire("referentiel")
    if not referentiel.empty:
        classement = classement.merge(referentiel, on="ticker", how="left")
    print("\nProbabilité de surperformer le marché :")
    print(classement.head(args.nombre).to_string(index=False))
    return 0


def _importer_csv(args) -> int:
    """Charge un CSV externe dans une table du schéma.

    Les dividendes, les fondamentaux et les séries de commodités ne sont
    scrapés par aucun module du projet : aucune source ne l'autorise ou ne
    l'expose simplement. Ce chemin permet de les fournir à la main, ce qui
    rend les modèles utilisables sans attendre un scraper.
    """
    chemin = Path(args.fichier)
    if not chemin.exists():
        print(f"fichier introuvable : {chemin}", file=sys.stderr)
        return 1

    donnees = pd.read_csv(chemin, dtype=str)
    attendues = db._colonnes_declarees(args.table)
    manquantes = [c for c in attendues if c not in donnees.columns]
    if manquantes:
        print(f"colonnes manquantes dans {chemin.name} : {manquantes}\n"
              f"attendu : {attendues}", file=sys.stderr)
        return 1

    for colonne in ("montant", "valeur"):
        if colonne in donnees.columns:
            donnees[colonne] = pd.to_numeric(donnees[colonne], errors="coerce")

    lignes = db.enregistrer(donnees, args.table)
    print(f"{lignes} lignes chargées dans « {args.table} »")
    if args.table == "exogenes":
        print(exogene.couverture(db.lire("exogenes")).to_string(index=False))
    return 0


def _rendement(args) -> int:
    cours = db.lire("cours")
    dividendes = db.lire("dividendes")
    if cours.empty:
        print("aucun cours en base", file=sys.stderr)
        return 1

    referentiel = db.lire("referentiel")
    secteurs = args.secteurs or ["Télécommunications", "Services Publics"]
    tickers = None
    if not referentiel.empty:
        tickers = list(referentiel[referentiel["secteur"].isin(secteurs)]["ticker"])

    tableau = dividende.signal(cours, dividendes, tickers)
    print(dividende.expliquer(tableau))
    return 0 if not tableau.empty else 1


def _exporter(args) -> int:
    for table in ("cours", "referentiel"):
        lignes = db.exporter(table)
        print(f"{lignes:>6} lignes → {db.chemin_archive(table)}")
    return 0


def _importer(args) -> int:
    for table in ("cours", "referentiel"):
        lignes = db.importer(table)
        print(f"{lignes:>6} lignes ← {db.chemin_archive(table)}")
    return 0


def _etat(args) -> int:
    for table, lignes in db.resume().items():
        print(f"{table:<18} {lignes:>7}")

    journal = db.lire("journal_ingestion")
    if not journal.empty:
        print("\nDernières ingestions :")
        for ligne in journal.tail(5).itertuples():
            print(f"  {ligne.horodatage}  {ligne.source:<12} {ligne.statut:<8} "
                  f"{ligne.lignes:>4}  {ligne.message[:60]}")
    return 0


def construire_analyseur() -> argparse.ArgumentParser:
    analyseur = argparse.ArgumentParser(
        prog="brvm", description="Ingestion des cours de la BRVM."
    )
    commandes = analyseur.add_subparsers(dest="commande", required=True)

    verifier = commandes.add_parser(
        "verifier", help="diagnostiquer les sélecteurs sans rien écrire"
    )
    verifier.add_argument(
        "source", nargs="?", default=None,
        help="page enregistrée à analyser ; par défaut, le site est interrogé",
    )
    verifier.set_defaults(fonction=_verifier)

    ingerer = commandes.add_parser("ingerer", help="enregistrer la séance publiée")
    ingerer.set_defaults(fonction=_ingerer)

    referentiel = commandes.add_parser(
        "referentiel", help="mettre à jour la liste des sociétés cotées"
    )
    referentiel.set_defaults(fonction=_referentiel)

    noter = commandes.add_parser(
        "noter", help="classer les valeurs (momentum filtré par liquidité)"
    )
    noter.add_argument("-n", "--nombre", type=int, default=10,
                       help="nombre de lignes affichées (10 par défaut)")
    noter.set_defaults(fonction=_noter)

    backtester = commandes.add_parser(
        "backtester", help="rejouer le classement dans le temps"
    )
    backtester.add_argument("--journal", action="store_true",
                            help="détailler chaque rééquilibrage")
    backtester.set_defaults(fonction=_backtester)

    predire = commandes.add_parser(
        "predire", help="probabilité de surperformance, et sa validation"
    )
    predire.add_argument("-n", "--nombre", type=int, default=15,
                         help="nombre de lignes affichées (15 par défaut)")
    predire.set_defaults(fonction=_predire)

    for table, aide in (
        ("dividendes", "détachements : ticker, date_detachement, montant, exercice"),
        ("fondamentaux", "ticker, date, indicateur, valeur"),
        ("exogenes", "séries externes : date, serie, valeur"),
    ):
        sous = commandes.add_parser(f"importer-{table}", help=f"CSV → {aide}")
        sous.add_argument("fichier", help="chemin du CSV à charger")
        sous.set_defaults(fonction=_importer_csv, table=table)

    rendement = commandes.add_parser(
        "rendement", help="retour à la moyenne du rendement du dividende"
    )
    rendement.add_argument("--secteurs", nargs="*", default=None,
                           help="secteurs analysés (télécoms et services "
                                "publics par défaut)")
    rendement.set_defaults(fonction=_rendement)

    exporter = commandes.add_parser(
        "exporter", help="base → CSV versionnés de data/"
    )
    exporter.set_defaults(fonction=_exporter)

    importer = commandes.add_parser(
        "importer", help="CSV de data/ → base"
    )
    importer.set_defaults(fonction=_importer)

    etat = commandes.add_parser("etat", help="afficher le contenu de la base")
    etat.set_defaults(fonction=_etat)

    return analyseur


def main(argv: list[str] | None = None) -> int:
    args = construire_analyseur().parse_args(argv)
    return args.fonction(args)


if __name__ == "__main__":
    sys.exit(main())
