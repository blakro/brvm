"""Contrôles d'intégrité de l'archive des cours.

CE QUE CE MODULE CHERCHE, ET POURQUOI CE N'EST PAS LA LIMITE DE ±7,5 %
---------------------------------------------------------------------

La BRVM cote par fixing avec une limite de variation de ±7,5 % par
séance. La tentation est d'en faire un invariant dur et de signaler toute
variation qui la franchit. Mesuré sur l'archive, ce contrôle produit 356
alertes dont l'immense majorité est légitime :

- le prix de référence est ajusté du dividende le jour du détachement,
  si bien qu'une baisse de 9 à 13 % y est régulière — 174 des 356 alertes
  tombent entre mai et août, la saison des détachements ;
- la limite relie deux séances consécutives, pas deux blocs séparés par
  un mois sans échange — 34 alertes suivent un trou de plus d'une
  semaine ;
- une division du nominal la franchit par construction.

Un contrôle qui crie sur des données correctes n'est pas un contrôle :
c'est un bruit qu'on apprend à ignorer, et le jour où il a raison
personne ne l'écoute. Ce module cherche donc une signature étroite et
sans ambiguïté.

LA SIGNATURE : LA SÉANCE FANTÔME
--------------------------------

Une ligne dont le cours vaut un multiple entier — ×2, ×5, ×10 — de la
séance qui la précède ET de celle qui la suit, ces deux-là s'accordant
entre elles. Aucun marché ne fait cela : il faudrait doubler puis
revenir, deux fois l'impossible en deux séances sous une limite de
±7,5 %.

Sur l'archive au 2026-07-27, 38 lignes portent cette signature, toutes
entre 2015 et 2017, sur trois valeurs. Leur mécanisme se lit à découvert
sur ONTBF : le cours y est exactement divisé par deux, la quantité
exactement doublée, et les capitaux échangés reproduisent au franc près
ceux de la veille. La ligne n'est pas une séance mal transcrite, c'est un
écho de la précédente rejoué à une autre échelle.

D'OÙ LE RETRAIT PLUTÔT QUE LA RÉPARATION. Réparer supposerait de
connaître le vrai cours du jour ; il n'y en a pas, la séance n'a pas eu
lieu sous cette forme. Remplacer la ligne par le cours de la veille
fabriquerait une observation. Un trou d'une séance, lui, est honnête :
l'archive en compte déjà des milliers — la plupart des valeurs ne
s'échangent pas tous les jours — et tout le code d'analyse les traite.
"""

from __future__ import annotations

import pandas as pd

# Multiples cherchés, dans les deux sens. Au-delà de 10 le rapport se
# confond avec une vraie division du nominal ; en deçà de 2 il se
# confond avec un mouvement de marché.
FACTEURS = (2, 3, 4, 5, 6, 7, 8, 9, 10)

# Écart toléré autour du multiple, en proportion de ce multiple. À 12 %,
# un rapport de 1,9 ou 2,2 passe encore pour un doublement ; un rapport
# de 1,7 ne passe plus. Assez lâche pour attraper une ligne dont les
# voisines ont elles-mêmes bougé de quelques pour cent, assez serré pour
# ne rien confondre avec un mouvement ordinaire.
TOLERANCE = 0.12

COLONNES = ["date", "ticker", "cloture", "precedent", "suivant", "facteur"]


def pics_isoles(cours: pd.DataFrame, tolerance: float = TOLERANCE,
                facteurs: tuple[int, ...] = FACTEURS) -> pd.DataFrame:
    """Les lignes valant un multiple entier de leurs DEUX voisines.

    Les deux voisines, jamais une seule : une ligne qui double face à la
    veille et reste doublée le lendemain est une division du nominal ou
    une vraie rupture, et il n'appartient pas à ce contrôle d'en juger.
    C'est l'aller-retour qui est impossible, pas l'aller.

    Renvoie un tableau vide — mais aux bonnes colonnes — quand il n'y a
    rien à signaler, pour qu'un appelant puisse toujours lire `.empty`
    sans se demander ce qu'il tient.
    """
    if cours.empty or "cloture" not in cours.columns:
        return pd.DataFrame(columns=COLONNES)

    table = cours.sort_values(["ticker", "date"]).reset_index(drop=True)
    precedent = table.groupby("ticker")["cloture"].shift()
    suivant = table.groupby("ticker")["cloture"].shift(-1)

    # Une ligne de bord n'a pas deux voisines : elle est hors du contrôle,
    # pas innocentée par lui.
    vers_avant = table["cloture"] / precedent
    vers_arriere = table["cloture"] / suivant

    marque = pd.Series(False, index=table.index)
    facteur = pd.Series(float("nan"), index=table.index)
    for k in facteurs:
        for multiple in (float(k), 1 / k):
            proche = (((vers_avant - multiple).abs() / multiple < tolerance)
                      & ((vers_arriere - multiple).abs() / multiple < tolerance))
            proche = proche.fillna(False)
            marque |= proche
            facteur[proche] = multiple

    suspects = table[marque].copy()
    suspects["precedent"] = precedent[marque]
    suspects["suivant"] = suivant[marque]
    suspects["facteur"] = facteur[marque]
    return suspects[COLONNES].sort_values(["ticker", "date"]).reset_index(drop=True)


def retirer(cours: pd.DataFrame, suspects: pd.DataFrame) -> pd.DataFrame:
    """L'archive privée des lignes signalées, l'ordre d'origine conservé.

    Le rapprochement se fait sur (date, ticker) — la clé de la table —
    et non sur l'index, qui ne survit pas au tri de `pics_isoles`.
    """
    if suspects.empty:
        return cours
    cle = pd.MultiIndex.from_frame(cours[["date", "ticker"]])
    a_retirer = pd.MultiIndex.from_frame(suspects[["date", "ticker"]])
    return cours[~cle.isin(a_retirer)].copy()


# Au-delà, les deux sources ne décrivent pas le même versement. 10 %
# laisse passer les arrondis et les acomptes comptés d'un côté seulement ;
# un facteur 2 ne passe pas.
ECART_SOURCES = 0.10

COLONNES_SOURCES = ["ticker", "exercice", "calendrier", "sikafinance", "ecart"]


def desaccords(dividendes: pd.DataFrame,
               fondamentaux: pd.DataFrame,
               tolerance: float = ECART_SOURCES) -> pd.DataFrame:
    """Où le calendrier de brvm.org et le tableau de sikafinance divergent.

    POURQUOI CE CONTRÔLE EXISTE. Jusqu'ici, aucun détachement n'avait été
    vérifié contre une source tierce : seule la cohérence interne l'était
    — un rendement médian de 7,8 % est plausible, ce qui ne prouve rien
    sur une ligne particulière. Or les deux sources se recouvrent sur une
    centaine de couples (société, exercice), et se comparer coûte deux
    jointures.

    CE QUE LE CONTRÔLE NE FAIT PAS : trancher. Sur l'archive du
    01/08/2026, quinze couples divergent de plus de 25 %, et plusieurs
    d'un FACTEUR 2 EXACT — les Bank of Africa et la SIB, où brvm.org
    annonce 684 quand sikafinance annonce 342. Un facteur aussi rond
    désigne une convention qui diffère (montant total contre acompte,
    brut contre net), pas une faute de saisie. La chute du cours au
    détachement ne départage pas non plus : elle vaut 3,6 % en moyenne
    quand le dividende en vaut 9,3, la limite de ±7,5 % par séance
    empêchant l'ajustement de tenir en un jour.

    Choisir sans savoir reviendrait à préférer une source pour la
    commodité. Le désaccord est donc signalé et laissé visible.
    """
    vide = pd.DataFrame(columns=COLONNES_SOURCES)
    if dividendes is None or dividendes.empty:
        return vide
    if fondamentaux is None or fondamentaux.empty:
        return vide
    if "exercice" not in dividendes.columns:
        return vide

    calendrier = dividendes.dropna(subset=["exercice"]).copy()
    if calendrier.empty:
        return vide
    calendrier["exercice"] = (calendrier["exercice"].astype(float)
                              .astype(int).astype(str))
    # La somme des acomptes : c'est le versement de l'exercice qui se
    # compare, pas chaque ligne prise isolément.
    somme = calendrier.groupby(["ticker", "exercice"])["montant"].sum()

    montants = fondamentaux[fondamentaux["indicateur"] == "dividende"].copy()
    if montants.empty:
        return vide
    montants["exercice"] = montants["date"].astype(str).str[:4]
    autre = montants.groupby(["ticker", "exercice"])["valeur"].sum()

    compare = pd.DataFrame({"calendrier": somme, "sikafinance": autre}).dropna()
    compare = compare[compare["sikafinance"] > 0]
    if compare.empty:
        return vide
    compare["ecart"] = (compare["calendrier"] / compare["sikafinance"] - 1).abs()
    retenus = compare[compare["ecart"] > tolerance].reset_index()
    return retenus[COLONNES_SOURCES].sort_values("ecart", ascending=False)


# La limite de variation par séance de la BRVM. Elle n'est PAS un
# invariant sur les clôtures — voir `limites` — mais elle reste le repère
# à partir duquel une variation mérite d'être regardée.
LIMITE_SEANCE = 0.075

# UN DIXIÈME DE POINT DE TOLÉRANCE, ET IL N'EST PAS ARBITRAIRE. Les cours
# se cotent en francs entiers : un mouvement bridé par la limite arrondit
# et peut ressortir à 7,52 % sans l'avoir franchie. La distribution le
# montre — 1 985 variations se pressent dans [7,45 % ; 7,50 %[, 131 dans
# le millième suivant, puis la queue s'aplatit. Compter ces bornes comme
# des dépassements noierait les vraies sous cinq fois leur nombre.
TOLERANCE_ARRONDI = 0.001

COLONNES_LIMITES = ["date", "ticker", "precedent", "cloture", "variation",
                    "cause_probable"]


def limites(cours: pd.DataFrame,
            limite: float = LIMITE_SEANCE) -> pd.DataFrame:
    """Les variations qui franchissent ±7,5 %, avec leur cause probable.

    POURQUOI C'EST UN RAPPORT ET NON UN REFUS. La BRVM cote avec une
    limite de ±7,5 % par séance, et la tentation est d'en faire un
    invariant dur. Mesuré sur l'archive, ce contrôle produit 356 alertes
    dont l'immense majorité est légitime :

    - le prix de référence est ajusté du dividende le jour du
      détachement, si bien qu'une baisse de 9 à 13 % y est régulière ;
    - la limite relie deux séances CONSÉCUTIVES, pas deux blocs séparés
      par un mois sans échange ;
    - une division du nominal la franchit par construction.

    Un contrôle qui crie sur des données correctes n'est pas un contrôle :
    c'est un bruit qu'on apprend à ignorer, et le jour où il a raison
    personne ne l'écoute. `pics_isoles` cherche donc la seule signature
    sans ambiguïté ; cette fonction-ci se contente de DÉCRIRE le reste,
    pour que 356 dépassements cessent d'être un chiffre jamais regardé.

    La cause probable est une hypothèse rangée, pas un verdict.
    """
    if cours.empty or "cloture" not in cours.columns:
        return pd.DataFrame(columns=COLONNES_LIMITES)

    table = cours.sort_values(["ticker", "date"]).reset_index(drop=True)
    precedent = table.groupby("ticker")["cloture"].shift()
    jours = pd.to_datetime(table["date"], errors="coerce")
    ecart = jours.groupby(table["ticker"]).diff().dt.days
    variation = table["cloture"] / precedent - 1

    marque = variation.abs() > limite + TOLERANCE_ARRONDI
    marque = marque.fillna(False)
    if not marque.any():
        return pd.DataFrame(columns=COLONNES_LIMITES)

    hors = table[marque].copy()
    hors["precedent"] = precedent[marque]
    hors["variation"] = variation[marque]
    mois = jours[marque].dt.month
    trou = ecart[marque] > 7

    # L'ordre compte : un trou explique la variation quel que soit le
    # mois, et il faut le dire avant d'invoquer la saison.
    cause = pd.Series("à examiner", index=hors.index)
    cause[mois.between(5, 8)] = "saison des détachements (mai-août)"
    cause[trou] = "séance précédente à plus d'une semaine"
    hors["cause_probable"] = cause
    return hors[COLONNES_LIMITES].reset_index(drop=True)
