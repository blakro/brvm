"""Ligne de commande du projet.

    python -m brvm verifier              diagnostic des sélecteurs
    python -m brvm verifier page.html    idem, sur une page enregistrée
    python -m brvm ingerer               enregistre la séance publiée
    python -m brvm referentiel           met à jour ticker / nom / secteur
    python -m brvm sonder                un appel réel à l'API sikafinance
    python -m brvm sonder-dividendes     ce que rendent les trois sources
    python -m brvm sonder-historique     comment remonter avant 2022
    python -m brvm rapatrier             historique sikafinance → archive
    python -m brvm dividendes            calendriers et historique → archive
    python -m brvm noter                 classe les valeurs
    python -m brvm rechercher            quel prédicteur marche, et où
    python -m brvm predire               probabilité de surperformance
    python -m brvm rendement             retour à la moyenne du rendement
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
               qualite, recherche, scoring)
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


def _dividendes(args) -> int:
    """Calendriers et historique des dividendes → archive.

    Les lignes non appariées à un ticker sont ÉCRITES NULLE PART et
    listées : un dividende attribué à la mauvaise société ne se verrait
    jamais, aucun contrôle en aval n'étant capable de le rattraper.
    """
    referentiel = db.lire("referentiel")
    if referentiel.empty:
        print("référentiel vide — lancez « brvm referentiel » d'abord",
              file=sys.stderr)
        return 1

    div, fonda, rapport = source_dividendes.collecter(
        referentiel, pages_max=args.pages)
    for source, detail in rapport.items():
        if source != "non_apparies":
            print(f"  {source:<14} {detail}")

    absents = rapport.get("non_apparies") or []
    if absents:
        print(f"\n{len(absents)} sociétés non appariées, donc non écrites :",
              file=sys.stderr)
        for nom in absents:
            print(f"  {nom}", file=sys.stderr)

    if div.empty and fonda.empty:
        print("\nrien à écrire", file=sys.stderr)
        return 1

    if args.simulation:
        print(f"\nsimulation : {len(div)} détachements et {len(fonda)} "
              "mesures seraient enregistrés")
        return 0

    if not div.empty:
        db.enregistrer(div, "dividendes")
        db.exporter("dividendes")
    if not fonda.empty:
        db.enregistrer(fonda, "fondamentaux")
        db.exporter("fondamentaux")
    print(f"\n{len(div)} détachements, {len(fonda)} mesures pluriannuelles "
          f"sur {div['ticker'].nunique() if not div.empty else 0} et "
          f"{fonda['ticker'].nunique() if not fonda.empty else 0} sociétés")
    return 0


def _sonder_avis(args) -> int:
    """Les avis officiels de détachement sont-ils atteignables ?

    L'enjeu : les deux sources de dividendes divergent sur 43 exercices,
    parfois d'un facteur 2, et l'écart vaut douze points de rendement
    total. Aucune des deux ne peut trancher l'autre. Un avis publié par
    la Bourse, lui, le pourrait — ce serait le premier document primaire
    du projet.
    """
    rapport = source_dividendes.sonder_avis(pages=args.pages)
    for page in rapport["pages"]:
        print(f"\n=== {page['url']} ===")
        if "echec" in page:
            print(f"  ÉCHEC : {page['echec']}")
            continue
        print(f"  HTTP {page['code']}, "
              f"{page.get('lignes_avec_lien', 0)} lignes portant une ancre")
        for exemple in page.get("exemples", []):
            print(f"    {exemple['ligne']}")
            for lien in exemple["liens"]:
                print(f"      → {lien}")

    print("\n=== les cibles ===")
    if not rapport["avis"]:
        print("  aucune ancre à suivre : la colonne « Avis » n'est pas un "
              "lien,\n  ou le tableau ne porte pas d'ancre du tout. La piste "
              "s'arrête ici.")
    for avis in rapport["avis"]:
        print(f"  {avis['url']}")
        if "echec" in avis:
            print(f"    ÉCHEC : {avis['echec']}")
            continue
        print(f"    HTTP {avis['code']}, {avis.get('octets', 0)} octets, "
              f"type {avis.get('type', '?')}, "
              f"PDF {'oui' if avis.get('est_pdf') else 'NON'}")

    print("\nRien n'a été écrit. Trois hypothèses distinctes : que "
          "« Télécharger » soit\nune ancre, que sa cible réponde, et que ce "
          "soit un PDF. Le journal dit\nlaquelle échoue.")
    return 0


def _sonder_historique(args) -> int:
    """Quelles pistes mènent aux exercices anciens ? Journal seul, rien d'écrit.

    L'archive porte quatre exercices (2022-2025), soit trois transitions
    annuelles. C'est assez pour établir que le dividende persiste, pas pour
    tester si son rendement prédit les cours : trois périodes disjointes ne
    font pas un échantillon.

    Les pistes de `PISTES_HISTORIQUE` sont des hypothèses, aucune n'a été
    vérifiée — les trois hôtes sont refusés au CONNECT depuis
    l'environnement de développement. Ce journal est ce qui les tranche.
    """
    rapport = source_dividendes.sonder_historique()
    # UNE RÉFÉRENCE PAR PISTE, PAS UNE POUR TOUT LE JOURNAL. Au premier
    # passage, les six pages de brvm.org servaient de référence aux appels
    # sikafinance qui suivaient : ceux-ci étaient donc déclarés « apporte
    # autre chose » alors qu'ils rendaient tous la même page, au dernier
    # octet près. Comparer deux sites entre eux ne veut rien dire.
    references: dict[str, tuple[dict, str | None]] = {}
    for entree in rapport:
        print(f"\n=== {entree['piste']} ===")
        print(f"  {entree['url']}")
        if "echec" in entree:
            print(f"  ÉCHEC : {entree['echec']}")
            continue
        print(f"  HTTP {entree['code']}, {entree.get('octets', 0)} octets")
        if not entree.get("tableaux"):
            continue
        print(f"  {entree['tableaux']} tableaux : {entree['dimensions']}")
        for i, tete in enumerate(entree["entetes"]):
            print(f"    [{i}] colonnes {tete}")
            lignes = (entree.get("premiere_colonne") or [None] * (i + 1))[i]
            if lignes:
                print(f"    [{i}] lignes   {lignes}")
        exercices = entree.get("exercices") or []
        print(f"  exercices en colonnes : {exercices or 'aucun'}")
        if "dividendes_lus" in entree:
            print(f"  calendrier : {entree['dividendes_lus']} lignes, "
                  f"{entree.get('dates', '—')}")
            for ligne in entree.get("extrait", []):
                print(f"    {ligne}")
        # Le verdict qui compte : cette page montre-t-elle autre chose que
        # la première de SA piste ? Une réponse 200 identique n'apporte
        # rien, et c'est le piège d'un site qui ignore un paramètre inconnu
        # au lieu de rendre une 404 — brvm.org le fait déjà sur les
        # secteurs. L'empreinte porte sur les cellules des tableaux : se
        # fier à ce qu'un lecteur extrait rend aveugle dès qu'il échoue, et
        # c'est ainsi que six pages toutes différentes ont été déclarées
        # identiques au premier passage.
        # DEUX COMPARAISONS, PAS UNE. Ne se comparer qu'à la première page
        # de la piste était littéralement vrai et pratiquement inutile :
        # les pages 50, 51 et 52 du calendrier avaient la MÊME empreinte
        # entre elles, et toutes les trois ont été annoncées « apporte
        # autre chose » parce qu'elles différaient de la page 40. Le fait
        # qui compte — la pagination s'est épuisée — n'était lisible que
        # dans les données brutes.
        empreinte = entree.get("empreinte")
        piste = entree["piste"]
        vues, precedente = references.setdefault(piste, ({}, None))
        print(f"  empreinte du contenu : {empreinte}")
        if precedente is None:
            print("  → page de référence de cette piste")
        elif empreinte == precedente:
            print("  → IDENTIQUE À LA PRÉCÉDENTE : la source se répète, "
                  "le parcours n'avance plus")
        elif empreinte in vues:
            print(f"  → déjà vue plus haut ({vues[empreinte]}) : "
                  "la source boucle")
        else:
            print("  → contenu nouveau")
        vues.setdefault(empreinte, entree["url"])
        references[piste] = (vues, empreinte)

    print("\nRien n'a été écrit. Les sélecteurs se corrigeront sur ce "
          "journal, pas sur des suppositions.")
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
    fusion, comblees = db.fusionner_cours(connu, nouveau)
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
        if comblees:
            print(f"{comblees} valeurs manquantes comblées sur des lignes "
                  "déjà présentes")

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

    resultat = backtest.backtester(cours, db.lire("referentiel"),
                                   fondamentaux=db.lire("fondamentaux"),
                                   dividendes=db.lire("dividendes"))
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


def _limites() -> None:
    """Les variations hors ±7,5 %, rangées par cause probable.

    Décrites, jamais refusées : le prix de référence est ajusté du
    dividende au détachement, la limite ne relie pas deux séances séparées
    d'un mois, et une division du nominal la franchit par construction.
    """
    hors = qualite.limites(pd.read_csv(db.chemin_archive("cours")))
    if hors.empty:
        print("\nAucune variation hors de la limite de ±7,5 %.")
        return
    print(f"\n{len(hors)} variations franchissent ±7,5 %, par cause "
          "probable :\n")
    for cause, lot in hors.groupby("cause_probable"):
        print(f"  {len(lot):>4}  {cause}")
    print("\nAucune n'est refusée : la limite s'applique au prix de "
          "référence, qui est\najusté du dividende au détachement, et elle "
          "ne relie pas deux séances\nséparées d'un mois. Un contrôle qui "
          "crie sur des données justes s'apprend\nà s'ignorer — voir "
          "« séances fantômes » pour la seule signature sans doute.")


def _desaccords() -> None:
    """Ce sur quoi les deux sources de dividendes ne s'accordent pas.

    Signalé, jamais tranché : un facteur 2 exact désigne une convention
    qui diffère, pas une faute de saisie, et préférer une source sans
    savoir reviendrait à choisir pour la commodité.
    """
    ecarts = qualite.desaccords(db.lire("dividendes"), db.lire("fondamentaux"))
    if ecarts.empty:
        print("\nDividendes : les deux sources s'accordent.")
        return
    print(f"\n{len(ecarts)} couples (société, exercice) où brvm.org et "
          f"sikafinance divergent de plus de "
          f"{qualite.ECART_SOURCES:.0%} :\n")
    for ligne in ecarts.head(12).itertuples(index=False):
        print(f"  {ligne.ticker:<6} {ligne.exercice}  "
              f"calendrier {ligne.calendrier:>9.2f}  "
              f"sikafinance {ligne.sikafinance:>9.2f}  "
              f"écart {ligne.ecart:>6.0%}")
    if len(ecarts) > 12:
        print(f"  … et {len(ecarts) - 12} autres")
    print("\nAucune des deux n'est corrigée : un facteur 2 exact désigne "
          "une convention\nqui diffère — montant total contre acompte, brut "
          "contre net — pas une faute\nde saisie. La chute du cours au "
          "détachement ne départage pas non plus, la\nlimite de ±7,5 % "
          "empêchant l'ajustement de tenir en une séance.")


def _qualite(args) -> int:
    """Signale — et sur demande retire — les séances fantômes.

    Le code de retour est 1 quand il reste des lignes signalées : la
    commande peut ainsi garder une action au rouge après un rapatriement
    qui aurait réintroduit ce qu'un précédent passage avait retiré. Sans
    cela, la correction ne tiendrait qu'un import.

    `--retirer` écrit l'archive CSV **et** efface les lignes de la base.
    Les deux, parce que `importer` est un INSERT OR REPLACE : il ajoute et
    corrige, il n'enlève jamais. Nettoyer le seul CSV laisse les lignes
    dans une base qui les connaît déjà, et le premier `exporter` les
    réécrit dans le CSV — la correction disparaît sans un mot. C'est
    exactement ce qui s'est produit au premier essai.
    """
    chemin = db.chemin_archive("cours")
    if not chemin.exists():
        print(f"pas d'archive à contrôler : {chemin}", file=sys.stderr)
        return 1

    archive = pd.read_csv(chemin)
    suspects = qualite.pics_isoles(archive)

    print(f"{len(archive)} lignes contrôlées ← {chemin}")
    if suspects.empty:
        print("aucune séance fantôme.")
        _limites()
        _desaccords()
        return 0

    print(f"\n{len(suspects)} séances fantômes — cours valant un multiple "
          f"entier de la veille ET du lendemain :\n")
    for ticker, lot in suspects.groupby("ticker"):
        facteurs = ", ".join(f"×{f:g}" if f >= 1 else f"÷{1 / f:g}"
                             for f in sorted(set(lot["facteur"])))
        print(f"  {ticker:<6} {len(lot):>3} lignes  {facteurs}  "
              f"{lot['date'].min()} → {lot['date'].max()}")

    _limites()
    _desaccords()

    if not args.retirer:
        print("\nRien n'a été modifié. « brvm qualite --retirer » les efface "
              "de l'archive.\n"
              "Le retrait plutôt que la réparation : ces lignes n'ont pas de "
              "vrai cours derrière elles, leur substituer une valeur "
              "fabriquerait une observation.", file=sys.stderr)
        return 1

    propre = qualite.retirer(archive, suspects)
    propre.to_csv(chemin, index=False)
    efface = db.effacer_cours(suspects)
    print(f"\n{len(archive)} → {len(propre)} lignes → {chemin}")
    print(f"{efface} lignes effacées de la base.")
    return 0


# TOUTES LES TABLES ARCHIVÉES, PAS DEUX. Le couple export/import ne
# connaissait que `cours` et `referentiel` : les dividendes et les
# fondamentaux étaient bien versionnés mais jamais rechargés, et le
# backtest les trouvait vides tout en les ayant sur disque. Le symptôme
# était muet — il rendait simplement les mêmes chiffres qu'avant.
TABLES_ARCHIVEES = ("cours", "referentiel", "dividendes", "fondamentaux",
                    "exogenes")


def _transferer(sens: str) -> int:
    operation = db.exporter if sens == "exporter" else db.importer
    fleche = "→" if sens == "exporter" else "←"
    for table in TABLES_ARCHIVEES:
        chemin = db.chemin_archive(table)
        if sens == "importer" and not chemin.exists():
            continue
        lignes = operation(table)
        print(f"{lignes:>6} lignes {fleche} {chemin}")
    return 0


def _exporter(args) -> int:
    return _transferer("exporter")


def _importer(args) -> int:
    return _transferer("importer")


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
        prog="brvm",
        description="Collecte, archivage et analyse des cours de la BRVM. "
                    "L'archive CSV versionnée est la source de vérité ; la "
                    "base SQLite s'en reconstruit."
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

    sonder_histo = commandes.add_parser(
        "sonder-historique",
        help="quelles pistes mènent aux exercices de dividendes anciens",
        description="Essaie les pistes de PISTES_HISTORIQUE et dit ce que "
                    "chacune rend. N'écrit rien. L'archive s'arrête à quatre "
                    "exercices ; c'est ce journal qui dira comment remonter.",
    )
    sonder_histo.set_defaults(fonction=_sonder_historique)

    sonder_av = commandes.add_parser(
        "sonder-avis",
        help="les avis officiels de détachement sont-ils atteignables",
        description="Suit la colonne « Avis » du calendrier officiel. "
                    "N'écrit rien. Les deux sources de dividendes divergent "
                    "sur 43 exercices ; un avis publié par la Bourse est le "
                    "seul document capable de les départager.",
    )
    sonder_av.add_argument("--pages", type=int, default=2,
                           help="pages de calendrier à examiner (2 par défaut)")
    sonder_av.set_defaults(fonction=_sonder_avis)

    div = commandes.add_parser(
        "dividendes",
        help="calendriers et historique des dividendes → archive",
        description="Lit brvm.org et sikafinance, apparie les noms aux "
                    "tickers et écrit. Une société non appariée n'est pas "
                    "écrite : elle est listée.",
    )
    div.add_argument("--simulation", action="store_true",
                     help="compter sans écrire")
    div.add_argument(
        "--pages", type=int, default=source_dividendes.PAGES_MAX,
        help="sécurité contre une pagination sans fin du calendrier "
             "brvm.org ; l'arrêt normal se fait sur une page déjà vue "
             f"({source_dividendes.PAGES_MAX} par défaut)",
    )
    div.set_defaults(fonction=_dividendes)

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

    qual = commandes.add_parser(
        "qualite", help="séances fantômes dans l'archive des cours"
    )
    qual.add_argument(
        "--retirer", action="store_true",
        help="effacer les lignes signalées au lieu de seulement les lister",
    )
    qual.set_defaults(fonction=_qualite)

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
