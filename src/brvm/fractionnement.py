"""Fractionnements et regroupements d'actions : les repérer, en tenir compte.

CE QUI S'EST PASSÉ
------------------
Le 26 octobre 2026, la SONATEL (SNTS) a été fractionnée : une action
ancienne est devenue dix actions nouvelles. La veille, l'archive porte
43 850 FCFA ; ce jour-là, 4 700. Rien n'a été perdu — l'actionnaire tient
dix fois plus de titres, chacun dix fois moins cher — mais toute analyse
qui lit la série brute y voit une chute de 89 % en une séance : une pire
chute record, un momentum effondré, un rendement du dividende de 40 % (le
dernier dividende, versé sur l'action ancienne, rapporté au prix de la
nouvelle), et un modèle de prévision qui apprend sur un krach qui n'a pas
eu lieu.

L'ARCHIVE GARDE LES COURS TELS QU'ILS ONT ÉTÉ PUBLIÉS
----------------------------------------------------
On n'y réécrit rien. Le CSV fait foi, il se compare au site d'origine
ligne à ligne, et le réécrire à chaque fractionnement rendrait le diff
illisible et la vérification impossible. L'ajustement se fait À LA
LECTURE, pour l'analyse et pour l'app, à partir d'une liste
d'événements :

- les cours d'avant le fractionnement sont divisés par le rapport ;
- les quantités échangées d'avant sont multipliées par lui, les capitaux
  échangés (FCFA) ne bougent pas ;
- les dividendes détachés avant sont divisés par lui, sans quoi le
  rendement du dividende serait multiplié d'autant.

C'est la convention de toutes les séries « ajustées » : le dernier cours
est le vrai, et le passé est exprimé en actions d'aujourd'hui.

D'OÙ VIENT LA LISTE : UN REGISTRE, ET UNE DÉTECTION
---------------------------------------------------
1. LE REGISTRE, `data/fractionnements.csv`, fait foi. Une ligne par
   événement : ticker, première séance sur la nouvelle base, rapport
   (actions nouvelles pour une ancienne : 10 pour « 1 pour 10 », 0,1
   pour un regroupement de dix en une). Un rapport de 1 dit « ceci n'est
   PAS un fractionnement » et fait taire la détection à cette date.

2. LA DÉTECTION couvre les fractionnements FUTURS sans que personne ait
   à y penser. La BRVM borne la variation d'une séance à ±7,5 % : un
   cours divisé par deux ou plus d'une séance à l'autre n'est pas un
   mouvement de marché. La signature retenue est étroite :

   - le rapport de la veille au jour, une fois retirée une variation
     ordinaire d'au plus `BANDE`, doit tomber sur un entier d'au moins 2
     (ou son inverse pour un regroupement) ; s'il en admet plusieurs, le
     plus rond l'emporte — 10 plutôt que 9 ;
   - le nouveau niveau doit TENIR : les séances suivantes restent plus
     près du nouveau cours que de l'ancien, et les précédentes plus près
     de l'ancien. C'est ce qui écarte les séances fantômes de 2015-2017
     (voir `qualite`), qui doublent puis reviennent, et le retour d'un
     fantôme, qui ressemblerait sinon à un regroupement.

   Un détachement de dividende, même exceptionnel, ne passe pas : FTSC a
   perdu 42 % le 26/09/2025 en détachant 1 320 FCFA, et un rapport de
   1,72 ne tombe sur aucun entier à 10 % près.

   La séance du fractionnement est ajustée DÈS LE SOIR MÊME, avant
   qu'aucune séance ne l'ait confirmée : l'app aurait sinon affiché un
   krach de 89 % jusqu'à confirmation. Si le nouveau niveau ne tient pas
   — une clôture mal transcrite, par exemple —, la détection le voit à la
   séance suivante et cesse d'ajuster, sans rien avoir écrit nulle part.

CE QUE LA DÉTECTION NE FAIT PAS. Un rapport qui n'est pas entier (trois
pour deux) ou un fractionnement noyé dans un trou de cotation de
plusieurs semaines ne sont pas reconnus : ils se déclarent au registre.
`python -m brvm fractionnements` liste ce qui est appliqué et ce qui est
seulement détecté, et `--enregistrer` verse les détections au registre.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

COLONNES = ["ticker", "date", "rapport", "note"]
COLONNES_EVENEMENTS = ["ticker", "date", "rapport", "origine", "precedent",
                       "cloture", "seances_apres"]

# Variation ordinaire tolérée autour du rapport, en plus du changement
# d'échelle. La limite de séance vaut 7,5 % ; le reste couvre l'arrondi
# du prix de référence au franc et une séance un peu décalée. Assez lâche
# pour reconnaître SNTS (43 850 → 4 700, soit 10 à -6,8 % près), assez
# serré pour qu'un rapport de 1,72 ne passe pas pour 2.
BANDE = 0.10

# Séances examinées de part et d'autre pour vérifier que le nouveau niveau
# tient et que l'ancien tenait. Une semaine de cotation.
CONFIRMATION = 5

# Fenêtre, en jours calendaires, dans laquelle une ligne du registre
# l'emporte sur une détection du même ticker. Sans elle, un registre daté
# du jour officiel — où la valeur n'a pas coté — et une détection datée de
# la première séance échangée ajusteraient deux fois.
FENETRE_REGISTRE = 31

# Indicateurs de `fondamentaux` exprimés PAR ACTION, avec le rendement qui
# les accompagne. Les rendements, eux, sont des rapports : un
# fractionnement ne les change pas.
PAR_ACTION = {"dividende": "rendement", "dividende_net": "rendement_net"}


def _rondeur(k: int) -> int:
    """0 pour 2, 5, 10, 20, 50, 100… ; 1 pour 4, 25, 250 ; 2 sinon.

    Les rapports de fractionnement sont des nombres ronds. Quand la bande
    admet deux entiers — SNTS admet 9 et 10 —, c'est le plus rond qui a eu
    lieu.
    """
    while k % 10 == 0 and k > 1:
        k //= 10
    if k in (1, 2, 5):
        return 0
    if k in (4, 25):
        return 1
    return 2


def rapport_probable(precedent: float, cloture: float,
                     bande: float = BANDE) -> float | None:
    """Le rapport de fractionnement qui explique ce saut, ou None.

    Rend 10 pour 43 850 → 4 700, 0,1 pour un regroupement de dix en une,
    None quand le saut ne tombe sur aucun entier d'au moins 2 une fois
    retirée une variation ordinaire d'au plus `bande`.
    """
    if not (precedent > 0 and cloture > 0):
        return None
    saut = precedent / cloture
    inverse = saut < 1
    if inverse:
        saut = 1 / saut
    # cloture = precedent / k × (1 + v), |v| ≤ bande  ⇒  k = saut × (1 + v).
    bas, haut = saut * (1 - bande), saut * (1 + bande)
    entiers = range(max(2, math.ceil(bas)), math.floor(haut) + 1)
    if not entiers:
        return None
    k = min(entiers, key=lambda e: (_rondeur(e), abs(math.log(saut / e))))
    return 1 / k if inverse else float(k)


def detecter(cours: pd.DataFrame, bande: float = BANDE,
             confirmation: int = CONFIRMATION) -> pd.DataFrame:
    """Les fractionnements et regroupements lisibles dans les cours BRUTS.

    Rend une ligne par événement, aux colonnes de `COLONNES_EVENEMENTS`.
    `origine` vaut « détecté », ou « détecté, à confirmer » tant que moins
    de `confirmation` séances ont suivi : l'événement est appliqué dans les
    deux cas, la mention dit seulement sur quoi il repose.
    """
    vide = pd.DataFrame(columns=COLONNES_EVENEMENTS)
    if cours is None or cours.empty or "cloture" not in cours.columns:
        return vide

    table = (cours[["date", "ticker", "cloture"]]
             .assign(cloture=lambda t: pd.to_numeric(t["cloture"],
                                                     errors="coerce"))
             .dropna(subset=["cloture"]))
    table = table[table["cloture"] > 0]
    table = table.sort_values(["ticker", "date"]).reset_index(drop=True)
    precedent = table.groupby("ticker")["cloture"].shift()
    saut = precedent / table["cloture"]
    # Le plus petit saut qu'un rapport de 2 puisse produire. En deçà, rien
    # à examiner : c'est le filtre qui rend la boucle ci-dessous courte.
    seuil = 2 * (1 - bande)
    candidats = table.index[(saut >= seuil) | (saut <= 1 / seuil)]

    lignes = []
    for i in candidats:
        ticker = table.at[i, "ticker"]
        ancien, nouveau = float(precedent[i]), float(table.at[i, "cloture"])
        rapport = rapport_probable(ancien, nouveau, bande)
        if rapport is None:
            continue

        # Le milieu géométrique sépare les deux niveaux : une séance est
        # « du côté » de celui dont elle est le plus proche en logarithme.
        milieu = math.sqrt(ancien * nouveau)
        baisse = nouveau < ancien
        serie = table[table["ticker"] == ticker]
        rang = serie.index.get_loc(i)
        apres = serie["cloture"].iloc[rang + 1:rang + 1 + confirmation]
        avant = serie["cloture"].iloc[max(0, rang - 1 - confirmation):rang - 1]
        tient = ((apres < milieu) if baisse else (apres > milieu)).all()
        tenait = ((avant > milieu) if baisse else (avant < milieu)).all()
        if not (tient and tenait):
            continue

        lignes.append({
            "ticker": ticker, "date": str(table.at[i, "date"])[:10],
            "rapport": rapport,
            "origine": ("détecté" if len(apres) >= confirmation
                        else "détecté, à confirmer"),
            "precedent": ancien, "cloture": nouveau,
            "seances_apres": int(len(apres)),
        })
    if not lignes:
        return vide
    return pd.DataFrame(lignes, columns=COLONNES_EVENEMENTS)


def evenements(cours: pd.DataFrame, registre: pd.DataFrame | None = None,
               detection: bool = True) -> pd.DataFrame:
    """Les événements à appliquer : le registre, complété par la détection.

    Le registre l'emporte sur toute détection du même ticker à moins de
    `FENETRE_REGISTRE` jours. Une ligne au rapport de 1 y est un veto :
    elle éteint la détection à cette date, puis disparaît de la liste.
    """
    colonnes = COLONNES_EVENEMENTS
    declares = pd.DataFrame(columns=colonnes)
    if registre is not None and not registre.empty:
        declares = registre.copy()
        declares["date"] = declares["date"].astype(str).str[:10]
        declares["rapport"] = pd.to_numeric(declares["rapport"],
                                            errors="coerce")
        declares = declares.dropna(subset=["ticker", "date", "rapport"])
        declares = declares[declares["rapport"] > 0]
        declares = declares.assign(origine="registre").reindex(
            columns=colonnes)

    detectes = detecter(cours) if detection else pd.DataFrame(columns=colonnes)
    if not detectes.empty and not declares.empty:
        jours = pd.to_datetime(declares["date"], errors="coerce")
        garde = []
        for ligne in detectes.itertuples():
            meme = jours[declares["ticker"] == ligne.ticker]
            ecart = (meme - pd.Timestamp(ligne.date)).abs().dt.days
            garde.append(not (ecart <= FENETRE_REGISTRE).any())
        detectes = detectes[garde]

    morceaux = [t for t in (declares, detectes) if not t.empty]
    if not morceaux:
        return pd.DataFrame(columns=colonnes)
    tout = pd.concat(morceaux, ignore_index=True)
    tout = tout[~np.isclose(tout["rapport"].astype(float), 1.0)]
    return tout.sort_values(["ticker", "date"]).reset_index(drop=True)


def diviseurs(evenements_: pd.DataFrame, tickers: pd.Series,
              dates: pd.Series) -> np.ndarray:
    """Le diviseur cumulé de chaque (ticker, date) : le produit des rapports
    des événements STRICTEMENT postérieurs. 1 là où rien ne s'applique.

    Postérieurs, et non antérieurs : c'est le passé qui s'exprime en
    actions d'aujourd'hui, si bien que le dernier cours n'est jamais
    touché — c'est celui qu'un acheteur paiera.
    """
    facteur = np.ones(len(tickers))
    if evenements_ is None or evenements_.empty:
        return facteur
    tickers = tickers.astype(str).to_numpy()
    dates = dates.astype(str).str[:10].to_numpy()
    for e in evenements_.itertuples():
        touche = (tickers == e.ticker) & (dates < e.date)
        facteur[touche] *= float(e.rapport)
    return facteur


def ajuster_cours(cours: pd.DataFrame,
                  evenements_: pd.DataFrame) -> pd.DataFrame:
    """Cours exprimés en actions d'aujourd'hui. L'original n'est pas touché."""
    if cours is None or cours.empty or evenements_ is None \
            or evenements_.empty:
        return cours
    facteur = diviseurs(evenements_, cours["ticker"], cours["date"])
    if (facteur == 1).all():
        return cours
    sortie = cours.copy()
    for colonne in ("ouverture", "haut", "bas", "cloture"):
        if colonne in sortie.columns:
            sortie[colonne] = pd.to_numeric(sortie[colonne],
                                            errors="coerce") / facteur
    # Dix fois plus d'actions pour le même argent : la quantité suit le
    # rapport, les capitaux échangés en FCFA ne bougent pas.
    if "volume_titres" in sortie.columns:
        sortie["volume_titres"] = pd.to_numeric(sortie["volume_titres"],
                                                errors="coerce") * facteur
    return sortie


def ajuster_dividendes(dividendes: pd.DataFrame,
                       evenements_: pd.DataFrame) -> pd.DataFrame:
    """Montants détachés avant un fractionnement, divisés par son rapport.

    Le montant publié l'est par action ANCIENNE. Le laisser tel quel le
    rapporterait au cours de l'action nouvelle : 1 740 FCFA sur 4 300,
    40 % de rendement pour SNTS au lieu de 4 %.
    """
    if dividendes is None or dividendes.empty or evenements_ is None \
            or evenements_.empty:
        return dividendes
    facteur = diviseurs(evenements_, dividendes["ticker"],
                        dividendes["date_detachement"])
    if (facteur == 1).all():
        return dividendes
    sortie = dividendes.copy()
    sortie["montant"] = pd.to_numeric(sortie["montant"],
                                      errors="coerce") / facteur
    return sortie


def ajuster_fondamentaux(fondamentaux: pd.DataFrame,
                         evenements_: pd.DataFrame,
                         cours_ajustes: pd.DataFrame | None = None,
                         dividendes: pd.DataFrame | None = None
                         ) -> pd.DataFrame:
    """Dividendes par action des fondamentaux, ramenés à l'action d'aujourd'hui.

    LA DIFFICULTÉ : CES MONTANTS N'ONT PAS DE DATE DE VERSEMENT. Ils sont
    rangés par exercice (au 31 décembre), et le dividende d'un exercice se
    détache l'année suivante — avant ou après un fractionnement survenu
    entre-temps. Pire, la source peut republier son tableau déjà ajusté :
    l'ajuster une seconde fois diviserait par cent.

    D'OÙ LE RENDEMENT COMME TÉMOIN. La source publie, à côté de chaque
    montant, le rendement qu'il représente. Leur rapport donne le cours
    sur lequel le montant est exprimé : 1 740 FCFA à 7,25 % pour SNTS en
    2025, soit 24 000 — le cours de l'action ancienne. Parmi les échelles
    possibles, on retient celle qui ramène ce cours implicite au niveau
    du cours AJUSTÉ de l'exercice : l'écart entre deux échelles vaut au
    moins un facteur 2, le cours d'une année en varie bien moins.

    Faute de rendement ou de cours, la date décide : celle du détachement
    de l'exercice au calendrier quand il est connu, la fin de l'exercice
    sinon.
    """
    if fondamentaux is None or fondamentaux.empty or evenements_ is None \
            or evenements_.empty:
        return fondamentaux
    concernes = (fondamentaux["indicateur"].isin(PAR_ACTION)
                 & fondamentaux["ticker"].isin(set(evenements_["ticker"])))
    if not concernes.any():
        return fondamentaux

    sortie = fondamentaux.copy()
    sortie["valeur"] = pd.to_numeric(sortie["valeur"], errors="coerce")
    cle = (sortie["ticker"].astype(str) + "|" + sortie["date"].astype(str)
           + "|" + sortie["indicateur"].astype(str))
    valeurs = dict(zip(cle, sortie["valeur"]))

    niveaux: dict[tuple[str, str], float] = {}
    if cours_ajustes is not None and not cours_ajustes.empty:
        prix = cours_ajustes[cours_ajustes["ticker"].isin(
            set(evenements_["ticker"]))]
        prix = prix.assign(annee=prix["date"].astype(str).str[:4],
                           cloture=pd.to_numeric(prix["cloture"],
                                                 errors="coerce"))
        niveaux = prix.groupby(["ticker", "annee"])["cloture"].median() \
            .to_dict()

    detache: dict[tuple[str, str], str] = {}
    if dividendes is not None and not dividendes.empty \
            and "exercice" in dividendes.columns:
        datees = dividendes.dropna(subset=["exercice"])
        for ligne in datees.sort_values("date_detachement").itertuples():
            try:
                annee = str(int(float(ligne.exercice)))
            except (TypeError, ValueError):
                continue
            detache.setdefault((str(ligne.ticker), annee),
                               str(ligne.date_detachement)[:10])

    for i in sortie.index[concernes]:
        ticker = str(sortie.at[i, "ticker"])
        date = str(sortie.at[i, "date"])[:10]
        annee = date[:4]
        montant = sortie.at[i, "valeur"]
        if not (montant > 0):
            continue
        propres = evenements_[evenements_["ticker"] == ticker]
        # Les échelles possibles : celle du début de l'exercice, puis celle
        # qui suit chacun des événements postérieurs — jusqu'à 1, l'échelle
        # d'aujourd'hui.
        debut = f"{annee}-01-01"
        echelles = {float(diviseurs(propres, pd.Series([ticker]),
                                    pd.Series([debut]))[0])}
        for e in propres[propres["date"] > debut].itertuples():
            echelles.add(float(diviseurs(propres, pd.Series([ticker]),
                                         pd.Series([e.date]))[0]))

        rendement = valeurs.get(
            f"{ticker}|{sortie.at[i, 'date']}|{PAR_ACTION[sortie.at[i, 'indicateur']]}")
        niveau = niveaux.get((ticker, annee))
        if rendement is not None and rendement > 0 and niveau and niveau > 0:
            implicite = float(montant) / (float(rendement) / 100)
            diviseur = min(echelles, key=lambda d: abs(
                math.log(implicite / d / niveau)))
        else:
            reference = detache.get((ticker, annee), date)
            diviseur = float(diviseurs(propres, pd.Series([ticker]),
                                       pd.Series([reference]))[0])
        sortie.at[i, "valeur"] = float(montant) / diviseur
    return sortie


def ajuster(cours: pd.DataFrame, dividendes: pd.DataFrame | None = None,
            fondamentaux: pd.DataFrame | None = None,
            registre: pd.DataFrame | None = None,
            detection: bool = True) -> dict:
    """Tout ajuster d'un coup. Rend un dict : cours, dividendes,
    fondamentaux (ajustés) et evenements (ce qui a été appliqué).

    Le point d'entrée de l'analyse et de l'app : les trois tables doivent
    l'être ENSEMBLE, sans quoi un cours ajusté rencontre un dividende qui
    ne l'est pas, et c'est le rendement du dividende qui ment.
    """
    liste = evenements(cours, registre, detection)
    cours_ajustes = ajuster_cours(cours, liste)
    return {
        "cours": cours_ajustes,
        "dividendes": ajuster_dividendes(dividendes, liste),
        "fondamentaux": ajuster_fondamentaux(fondamentaux, liste,
                                             cours_ajustes, dividendes),
        "evenements": liste,
    }


def decrire(evenement) -> str:
    """« 1 action ancienne = 10 nouvelles », en clair, pour l'app et la CLI."""
    rapport = float(evenement["rapport"] if isinstance(evenement, dict)
                    else evenement.rapport)
    if rapport >= 1:
        return f"1 action ancienne = {rapport:g} nouvelles"
    return f"{1 / rapport:g} actions anciennes = 1 nouvelle"
