"""Ligne de commande du projet.

    python -m brvm verifier              diagnostic des sélecteurs
    python -m brvm verifier page.html    idem, sur une page enregistrée
    python -m brvm ingerer               enregistre la séance publiée
    python -m brvm referentiel           met à jour ticker / nom / secteur
    python -m brvm etat                  ce que contient la base

Chaque commande rend 0 en cas de succès et 1 en cas d'échec, pour qu'un
cron ou une action GitHub sache qu'il s'est passé quelque chose sans avoir
à lire la sortie.
"""

from __future__ import annotations

import argparse
import sys

from . import db
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

    etat = commandes.add_parser("etat", help="afficher le contenu de la base")
    etat.set_defaults(fonction=_etat)

    return analyseur


def main(argv: list[str] | None = None) -> int:
    args = construire_analyseur().parse_args(argv)
    return args.fonction(args)


if __name__ == "__main__":
    sys.exit(main())
