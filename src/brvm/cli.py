"""Ligne de commande du projet.

    python -m brvm verifier              diagnostic des sélecteurs
    python -m brvm verifier page.html    idem, sur une page enregistrée
    python -m brvm ingerer               enregistre la séance publiée
    python -m brvm referentiel           met à jour ticker / nom / secteur
    python -m brvm sonder                un appel réel, pour trancher
    python -m brvm rapatrier             historique sikafinance → archive
    python -m brvm noter                 classe les valeurs
    python -m brvm rechercher            quel prédicteur marche, et où
    python -m brvm backtester            rejoue le classement dans le temps
    python -m brvm exporter              base → CSV versionnés
    python -m brvm importer              CSV versionnés → base
    python -m brvm veille                l'archive s'enrichit-elle encore ?
    python -m brvm etat                  ce que contient la base

Chaque commande rend 0 en cas de succès et 1 en cas d'échec, pour qu'un
cron ou une action GitHub sache qu'il s'est passé quelque chose sans avoir
à lire la sortie.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import (backtest, db, dividende, exogene, features, prediction,
               recherche, scoring)
from .ingestion import brvm_org, dividendes as source_dividendes, sikafinance


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


def _sonder_dividendes(args) -> int:
    """Interroge les trois sources de dividendes et décrit ce qu'elles rendent.

    Aucune n'a jamais été atteinte depuis l'environnement de développement :
    le balisage de leurs tableaux est inconnu, et les sélecteurs de
    `ingestion.dividendes` sont des hypothèses. Ce journal est ce qui les
    transforme en faits.
    """
    rapport = source_dividendes.sonder(args.date)
    for nom, detail in rapport.items():
        print(f"\n=== {nom} ({detail['nature']}) ===")
        print(f"  {detail['url']}")
        if "echec" in detail:
            print(f"  ÉCHEC : {detail['echec']}")
            continue
        print(f"  {detail['octets']} octets, {detail['tableaux']} tableaux")
        for i, (entete, forme) in enumerate(
                zip(detail["entetes"], detail["dimensions"])):
            print(f"  tableau {i} {forme} : {entete}")
        for i, lignes in enumerate(detail["premieres_lignes"]):
            for ligne in lignes:
                print(f"    [{i}] {ligne}")
        print(f"  lecture : {detail['lu']}")
        for ligne in detail.get("extrait", []):
            print(f"    {ligne}")

    lisibles = sum("echec" not in d and not str(d.get("lu", "")).startswith("illisible")
                   for d in rapport.values())
    print(f"\n{lisibles} source(s) sur {len(rapport)} lues correctement.")
    return 0 if lisibles else 1


def _sonder(args) -> int:
    """Un seul appel réel, et tout ce qu'il permet de trancher.

    L'API de sikafinance n'est joignable ni depuis l'environnement de
    développement ni depuis les tests : deux questions restent donc
    ouvertes jusqu'au premier appel — ce que mesure la colonne `Volume`,
    et si l'OHLC est cohérent. Les lancer sur 1 269 requêtes sans les
    avoir tranchées reviendrait à remplir l'archive au hasard.
    """
    ticker = args.ticker
    print(f"Sonde sur {ticker}, du {args.debut} au {args.fin}. "
          "Rien ne sera écrit.\n")

    if args.source is None:
        try:
            suffixes = sikafinance.symboles()
            print(f"Menu de l'accueil : {len(suffixes)} actions, "
                  f"{ticker} → {sikafinance.symbole(ticker, suffixes)}")
            pays = sorted(set(suffixes.values()))
            print(f"Suffixes rencontrés : {', '.join(pays)}\n")
        except Exception as erreur:  # noqa: BLE001
            suffixes = None
            print(f"Menu illisible ({type(erreur).__name__} — {erreur}) ; "
                  f"suffixe par défaut « {sikafinance.SUFFIXE_DEFAUT} »\n",
                  file=sys.stderr)
    else:
        suffixes = None

    try:
        table = sikafinance.historique(ticker, args.debut, args.fin,
                                       source=args.source, suffixes=suffixes)
    except Exception as erreur:  # noqa: BLE001
        print(f"échec : {type(erreur).__name__} — {erreur}", file=sys.stderr)
        return 1

    if table.empty:
        print("réponse vide : ni erreur ni donnée. Vérifiez le symbole et "
              "la période avant de conclure.", file=sys.stderr)
        return 1

    print(f"{len(table)} séances, {table['date'].min()} → "
          f"{table['date'].max()}")
    print(f"colonnes rendues : {', '.join(table.columns)}\n")
    print(table.head(12).to_string(index=False))

    print("\n1. Que mesure « Volume » ?")
    print(f"   {sikafinance.temoin(table)}")

    print("\n2. « plus bas » <= clôture <= « plus haut » ?")
    fautives = sikafinance.ohlc_incoherent(table)
    if not fautives:
        print("   cohérent sur toutes les séances rendues — l'API est "
              "meilleure que la page, l'OHLC peut entrer en base.")
    else:
        print(f"   {len(fautives)} séances sur {len(table)} incohérentes, "
              "comme dans le HTML. Ces colonnes restent dehors.")
        for ligne in fautives[:5]:
            print(f"   {ligne}")

    print("\n3. Séances republiées ?")
    repetees = sikafinance.seances_repetees(table)
    print(f"   {len(repetees)} séance(s) au volume identique à la veille")
    for ligne in repetees[:5]:
        print(f"   {ligne}")

    ecarts = sikafinance.coherence(table)
    if ecarts:
        print(f"\n4. {len(ecarts)} variations incohérentes avec la clôture")
        for ligne in ecarts[:5]:
            print(f"   {ligne}")

    print("\nSi ces trois réponses vous conviennent, relancez le "
          "rapatriement complet.")
    return 0


def _rechercher(args) -> int:
    """Balayage prédicteurs × segments × horizons, correction comprise."""
    cours = db.lire("cours")
    if cours.empty:
        print("aucun cours en base — lancez « brvm rapatrier »", file=sys.stderr)
        return 1

    table = recherche.balayer(cours, db.lire("referentiel"))
    retour = recherche.retour_a_la_moyenne(cours) if args.valeurs else None
    print(recherche.expliquer(table, retour))

    if args.csv:
        table.to_csv(args.csv, index=False)
        print(f"\n{len(table)} lignes → {args.csv}")
    # Rien de retenu n'est un échec de recherche, pas une panne : le code
    # de sortie reste 0, et c'est le texte qui porte le verdict.
    return 0


def _rapatrier(args) -> int:
    """Historique sikafinance → archive des cours.

    Trois refus explicites plutôt qu'un rapatriement à moitié bon :
    une incohérence de colonnes rejette la valeur concernée, pas tout le
    lot ; une valeur injoignable est signalée et le reste continue ; et
    rien n'est écrit tant qu'une valeur au moins n'a rien donné de
    contrôlé. Un millier de requêtes ne se relance pas à la légère.
    """
    referentiel = db.charger_archive("referentiel")
    demandes = args.tickers or sorted(referentiel["ticker"].dropna().unique())
    if not demandes:
        print("aucun ticker : renseignez le référentiel d'abord",
              file=sys.stderr)
        return 1

    # Le suffixe pays fait partie de l'identifiant et ne se devine pas :
    # la BRVM cote des émetteurs de huit pays. Lu une fois pour toutes.
    suffixes = None
    if args.source is None:
        try:
            suffixes = sikafinance.symboles()
        except Exception as erreur:  # noqa: BLE001
            print(f"menu des symboles illisible ({erreur}) ; suffixe par "
                  f"défaut « {sikafinance.SUFFIXE_DEFAUT} »", file=sys.stderr)

    connu = db.charger_archive("cours")
    recoltes, refus, signales = [], [], []
    for ticker in demandes:
        try:
            table = sikafinance.historique(
                ticker, args.debut, args.fin, source=args.source,
                suffixes=suffixes, pause=args.pause)
        except Exception as erreur:  # noqa: BLE001 — réseau, HTML, tout
            refus.append(f"{ticker} : {type(erreur).__name__} — {erreur}")
            continue

        ecarts = sikafinance.coherence(table)
        if ecarts:
            refus.append(
                f"{ticker} : {len(ecarts)} variations incohérentes, valeur "
                f"écartée (première : {ecarts[0]})")
            continue
        signales += [f"{ticker} — {m}" for m in
                     sikafinance.seances_repetees(table)]
        recoltes.append(sikafinance.retenir(
            table,
            f"volume_{args.volume}" if args.volume else sikafinance.VOLUME_API))
        print(f"  {ticker:<7} {len(table):>5} séances "
              f"{table['date'].min()} → {table['date'].max()}")

    if not recoltes:
        print("rien de contrôlé : archive inchangée", file=sys.stderr)
        for ligne in refus:
            print(f"  {ligne}", file=sys.stderr)
        return 1

    nouveau = pd.concat(recoltes, ignore_index=True)
    # La séance publiée par brvm.org fait foi sur les dates qu'elle
    # couvre : elle vient de la source primaire. L'historique ne fait que
    # combler ce qu'elle n'a pas encore vu.
    fusion = (pd.concat([nouveau, connu], ignore_index=True)
              .drop_duplicates(subset=["date", "ticker"], keep="last")
              .sort_values(["date", "ticker"]))
    ajoutees = len(fusion) - len(connu)

    if args.simulation:
        print(f"\nsimulation : {ajoutees} lignes seraient ajoutées "
              f"({len(connu)} → {len(fusion)})")
    else:
        chemin = db.chemin_archive("cours")
        chemin.parent.mkdir(parents=True, exist_ok=True)
        fusion.to_csv(chemin, index=False)
        print(f"\n{ajoutees} lignes ajoutées ({len(connu)} → {len(fusion)}), "
              f"{fusion['date'].nunique()} séances en archive")

    if signales:
        print(f"\n{len(signales)} séances au volume identique à la veille — "
              "vraisemblablement republiées, à examiner :", file=sys.stderr)
        for ligne in signales[:20]:
            print(f"  {ligne}", file=sys.stderr)
    if refus:
        print(f"\n{len(refus)} valeurs écartées :", file=sys.stderr)
        for ligne in refus:
            print(f"  {ligne}", file=sys.stderr)
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

    cours = db.lire("cours")
    date_seance = str(cours["date"].max()) if not cours.empty else args.date

    # Fusion, jamais remplacement : une société radiée garde sa ligne et sa
    # dernière date de présence. Sans cela, elle disparaîtrait du passé
    # qu'elle a pourtant vécu.
    connu = db.dater_depuis_les_cours(db.lire("referentiel"), cours)
    fusion, changements = db.fusionner_referentiel(connu, ref, date_seance)
    db.enregistrer(fusion, "referentiel")

    classees = int(fusion["secteur"].notna().sum())
    print(f"{len(fusion)} sociétés au référentiel ({len(ref)} vues aujourd'hui "
          f"depuis {origine}), {classees} avec secteur")
    for changement in changements:
        print(f"  {changement}")
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


def _veille(args) -> int:
    """L'archive s'est-elle enrichie récemment ? 0 si oui, 1 sinon.

    `ingestion.yml` ne rougit pas quand une exécution échoue : jour férié,
    séance non close, site en maintenance sont des cas normaux, et rougir
    chaque jour chômé apprendrait à ignorer les alertes. Le revers de ce
    choix est qu'une panne durable ne se voit pas non plus — le pipeline
    peut être mort depuis trois semaines sans que rien ne le dise.

    Cette commande est le complément manquant : elle ne regarde pas si la
    dernière exécution a réussi, mais si la DONNÉE avance. C'est la seule
    question qui compte, et elle a une réponse même quand personne n'a
    regardé les journaux.
    """
    archive = db.charger_archive("cours")
    if archive.empty:
        print("archive vide : aucune séance n'a jamais été enregistrée",
              file=sys.stderr)
        return 1

    derniere = str(archive["date"].max())
    aujourdhui = datetime.now().date()
    ecoules = len(pd.bdate_range(
        pd.Timestamp(derniere).date() + pd.Timedelta(days=1), aujourdhui
    ))

    print(f"dernière séance en archive : {derniere}")
    print(f"jours ouvrés écoulés depuis : {ecoules}")
    print(f"séances au total : {archive['date'].nunique()}")

    if ecoules > args.tolerance:
        print(
            f"\nARCHIVE FIGÉE : {ecoules} jours ouvrés sans nouvelle séance, "
            f"seuil {args.tolerance}. Causes probables, par ordre de "
            "fréquence : l'action ne s'exécute pas (branche par défaut, "
            "workflow désactivé après 60 jours d'inactivité du dépôt), le "
            "runner n'atteint pas brvm.org, ou les sélecteurs ont cassé — "
            "lancez « brvm verifier » pour trancher entre les deux derniers.",
            file=sys.stderr,
        )
        return 1

    print("\nL'archive avance.")
    return 0


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
    referentiel.add_argument(
        "--date", default=datetime.now().strftime("%Y-%m-%d"),
        help="date de présence à enregistrer si la base n'a pas de cours",
    )
    referentiel.set_defaults(fonction=_referentiel)

    rapatrier = commandes.add_parser(
        "rapatrier",
        help="historique sikafinance → archive des cours",
        description="Rapatrie l'historique séance par séance. Le site ne "
                    "sert que trois mois à la fois : la période demandée "
                    "est découpée, une pause sépare les requêtes.",
    )
    rapatrier.add_argument("--debut", required=True, help="AAAA-MM-JJ")
    rapatrier.add_argument("--fin", required=True, help="AAAA-MM-JJ")
    rapatrier.add_argument("--tickers", nargs="*", default=None,
                           help="par défaut, tout le référentiel")
    rapatrier.add_argument("--source", default=None,
                           help="page enregistrée, au lieu du réseau")
    rapatrier.add_argument("--pause", type=float, default=0.5,
                           help="secondes entre deux requêtes (défaut 0,5)")
    rapatrier.add_argument("--volume", choices=["titres", "fcfa"],
                           default=None,
                           help="forcer ce que compte le « Volume » de "
                                "l'API ; par défaut des titres, ce que la "
                                "sonde a établi")
    rapatrier.add_argument("--simulation", action="store_true",
                           help="compter sans écrire")
    rapatrier.set_defaults(fonction=_rapatrier)

    rechercher = commandes.add_parser(
        "rechercher",
        help="quel prédicteur marche, sur quel segment, à quel horizon",
        description="Balaie prédicteurs × segments × horizons et corrige "
                    "le test multiple. Sans cette correction, la question "
                    "« quel est le meilleur modèle ? » a toujours une "
                    "réponse, y compris quand elle devrait être « aucun ».",
    )
    rechercher.add_argument("--valeurs", action="store_true",
                            help="ajouter le retour à la moyenne valeur par valeur")
    rechercher.add_argument("--csv", default=None, help="exporter la grille")
    rechercher.set_defaults(fonction=_rechercher)

    sonder = commandes.add_parser(
        "sonder",
        help="un appel réel, pour trancher ce qui ne peut l'être hors ligne",
        description="Interroge l'API sur une seule valeur et rend compte : "
                    "ce que mesure « Volume », si l'OHLC est cohérent, si "
                    "des séances sont republiées. N'écrit rien.",
    )
    sonder.add_argument("--ticker", default="SDSC")
    sonder.add_argument("--debut", default="2026-01-01", help="AAAA-MM-JJ")
    sonder.add_argument("--fin", default="2026-03-31", help="AAAA-MM-JJ")
    sonder.add_argument("--source", default=None,
                        help="réponse enregistrée (.json ou .html)")
    sonder.set_defaults(fonction=_sonder)

    sonder_div = commandes.add_parser(
        "sonder-dividendes",
        help="ce que rendent les trois sources de dividendes",
        description="Interroge brvm.org, sikafinance et abourse, décrit "
                    "leurs tableaux et n'écrit rien. Les sélecteurs de ce "
                    "module n'ont jamais rencontré les vraies pages.",
    )
    sonder_div.add_argument("--date", default=None,
                            help="séance pour abourse (AAAA-MM-JJ)")
    sonder_div.set_defaults(fonction=_sonder_dividendes)

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

    veille = commandes.add_parser(
        "veille", help="l'archive s'enrichit-elle encore ?"
    )
    veille.add_argument(
        "--tolerance", type=int, default=5,
        help="jours ouvrés tolérés sans nouvelle séance (5 par défaut)",
    )
    veille.set_defaults(fonction=_veille)

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
