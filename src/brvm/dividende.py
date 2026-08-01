"""Rendement du dividende et son retour à la moyenne.

POUR QUELS SECTEURS, ET POURQUOI PAS LES AUTRES
------------------------------------------------
Télécommunications et Services Publics : Sonatel, Orange CI, Onatel, la CIE
et la SODECI. Revenus réguliers, tarifs régulés ou quasi, logique
d'obligation plus que d'action. Le cours y oscille autour d'un rendement
d'équilibre : quand le rendement monte nettement au-dessus de sa moyenne,
c'est le cours qui a baissé, et il a tendance à revenir.

Le ML n'apporte rien ici et ce module n'en contient pas. Cinq valeurs ne
font pas un échantillon d'apprentissage ; elles font une relation à estimer
par régression, avec deux paramètres et un test de validité.

LE MODÈLE
---------
Processus d'Ornstein-Uhlenbeck sur le rendement `y` :

    y(t+1) - y(t) = θ·(μ - y(t)) + bruit

estimé par moindres carrés sur ΔY contre Y. Deux nombres en sortent :
`μ`, le rendement d'équilibre, et `θ`, la vitesse à laquelle on y revient.

LA DEMI-VIE EST LE GARDE-FOU, PAS UN ORNEMENT
----------------------------------------------
`ln(2)/θ` donne le temps qu'il faut pour combler la moitié de l'écart. Un
signal dont la demi-vie dépasse l'horizon de détention ne dit rien
d'exploitable : le retour aura lieu, peut-être, mais après qu'on aura
vendu. Toute valeur dont la demi-vie excède l'horizon est donc écartée,
même si son écart au rendement d'équilibre est spectaculaire.

C'est ce contrôle qui distingue un modèle de retour à la moyenne d'une
simple mesure « ce titre a beaucoup baissé ».
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import features
from .config import charger

# Au-delà, un détachement n'est pas un dividende généreux : c'est une
# incompatibilité d'échelle entre le montant publié et le cours archivé.
# Le plus haut rendement crédible jamais publié par les sources sur cette
# place est de 24 % (BOA Mali, exercice 2024) ; 40 % laisse donc une marge
# large avant de refuser quoi que ce soit de réel.
PLAFOND_RENDEMENT = 0.40

COLONNES = ["ticker", "rendement", "equilibre", "ecart_normalise",
            "demi_vie", "exploitable"]


def detachements(cours: pd.DataFrame,
                 dividendes: pd.DataFrame) -> tuple[pd.DataFrame, set]:
    """Le dividende crédité LE JOUR où il se détache. Rend (table, couples vus).

    LA CONVENTION EXACTE, DEPUIS QUE LES DATES EXISTENT. Le calendrier
    officiel de brvm.org porte 309 détachements datés sur onze exercices.
    Le rendement d'une ligne est son montant rapporté au cours de la
    DERNIÈRE séance connue avant le détachement — le cours qui va chuter,
    pas celui qui a déjà chuté. Prendre le cours du jour même diviserait
    par un prix déjà amputé du dividende et surestimerait le rendement.

    Les couples (ticker, exercice) rencontrés sont rendus avec la table :
    c'est ce qui permet à `accroissement` de ne pas compter deux fois un
    exercice connu à la fois par le calendrier et par les fondamentaux.
    """
    prix = features.serie(cours)
    vide = pd.DataFrame(0.0, index=prix.index, columns=prix.columns)
    if prix.empty or dividendes is None or dividendes.empty:
        return vide, set()
    if not {"ticker", "date_detachement", "montant"} <= set(dividendes.columns):
        return vide, set()

    # Premier passage : le rendement qu'impliquerait chaque ligne.
    brut = []
    for _, ligne in dividendes.iterrows():
        ticker = str(ligne["ticker"])
        if ticker not in prix.columns:
            continue
        montant = pd.to_numeric(ligne["montant"], errors="coerce")
        if not (montant > 0):
            continue
        date = str(ligne["date_detachement"])[:10]
        # La dernière séance connue à cette date ou avant. Le détachement
        # tombe parfois un jour sans cotation pour cette valeur.
        anterieures = prix.index[prix.index <= date]
        if len(anterieures) == 0:
            continue
        seance = anterieures[-1]
        veille = prix.loc[seance, ticker]
        if not (veille > 0):
            continue
        brut.append({"ticker": ticker, "seance": seance,
                     "rendement": float(montant) / float(veille),
                     "exercice": str(ligne.get("exercice", ""))[:4]})
    if not brut:
        return vide, set()
    brut = pd.DataFrame(brut)

    # LA COUPURE DE 2018, ET POURQUOI ELLE SE MESURE AU LIEU DE SE SUPPOSER.
    # Les montants du calendrier officiel sont ceux publiés à l'époque ;
    # les cours de l'archive ne sont pas sur la même échelle avant la
    # réduction du nominal imposée sur cette place en 2018. Le rapport se
    # voit à l'œil nu — CFAC verse 2 032 en 2017 puis 9,9 en 2018, la SDSC
    # 8 997 puis 184, la SGBC 5 837 puis 585 : trois facteurs différents,
    # la même année. Le rendement implicite médian passe de 60 % en 2017 à
    # 7 % en 2018.
    #
    # ON NE CORRIGE PAS, ON REFUSE. Reconstituer un facteur par société à
    # partir du saut reviendrait à déduire la donnée de l'anomalie qu'elle
    # est censée expliquer. Pour chaque société, la dernière séance portant
    # un rendement impossible marque la frontière : tout ce qui est à cette
    # date ou avant est écarté. Une société dont aucun rendement n'est
    # impossible ne perd rien.
    frontiere = (brut[brut["rendement"] > PLAFOND_RENDEMENT]
                 .groupby("ticker")["seance"].max())
    garde = brut[brut.apply(
        lambda l: l["seance"] > frontiere.get(l["ticker"], ""), axis=1)]

    table, couverts = vide.copy(), set()
    for _, l in garde.iterrows():
        table.loc[l["seance"], l["ticker"]] += l["rendement"]
        if l["exercice"].isdigit():
            couverts.add((l["ticker"], l["exercice"]))
    return table, couverts


def accroissement(cours: pd.DataFrame,
                  fondamentaux: pd.DataFrame,
                  dividendes: pd.DataFrame | None = None) -> pd.DataFrame:
    """Rendement du dividende accru séance par séance, dates × tickers.

    POURQUOI CETTE FONCTION, ET CE QU'ELLE APPROXIME
    ------------------------------------------------
    Le backtest travaillait sur cours nus. Or, sur les quatre exercices
    connus, le dividende médian vaut 7 à 10 % PAR AN quand le cours va de
    -1,6 % à +61,4 % : ignorer le dividende, c'est se tromper de plus que
    tout ce qu'on cherche à mesurer, et se tromper systématiquement CONTRE
    les valeurs de rendement — celles que le momentum délaisse déjà.

    DEUX CONVENTIONS, ET LA PREMIÈRE EST LA BONNE.

    1. LE DÉTACHEMENT DATÉ, quand le calendrier officiel le donne — 309
       lignes sur onze exercices depuis la collecte du 01/08/2026. Le
       dividende est crédité le jour où il tombe, comme dans la réalité.

    2. LA RÉPARTITION SUR L'EXERCICE, en repli, pour les couples
       (société, exercice) que le calendrier ne couvre pas. Le tableau
       pluriannuel de sikafinance donne un rendement par exercice sans
       date : le dividende est alors étalé sur les séances de l'année.

    Un couple couvert par le calendrier N'EST PAS repris par le repli :
    sans cette exclusion, un exercice connu des deux côtés serait compté
    deux fois, et le rendement total gonflerait sans que rien ne le dise.

    CE QUE LE REPLI APPROXIME ENCORE. Sur une détention d'un trimestre ou
    plus — le pas le plus court du backtest est de 20 séances — l'écart
    entre les deux conventions est faible. Sur quelques jours, il ne l'est
    pas : un détachement fait chuter le cours d'un coup, et l'étaler
    lisserait précisément ce qu'on voudrait voir.

    Les exercices sans donnée rendent zéro, pas NaN : une année sans
    dividende connu n'ajoute rien au rendement, et propager un NaN
    effacerait aussi le rendement du cours.
    """
    prix = features.serie(cours)
    vide = pd.DataFrame(0.0, index=prix.index, columns=prix.columns)
    if prix.empty:
        return vide

    accru, couverts = detachements(cours, dividendes)
    if fondamentaux is None or fondamentaux.empty:
        return accru

    rendements = fondamentaux[fondamentaux["indicateur"] == "rendement"]
    if rendements.empty:
        return accru

    annees = prix.index.to_series().str[:4]
    for _, ligne in rendements.iterrows():
        ticker, annee = str(ligne["ticker"]), str(ligne["date"])[:4]
        if ticker not in accru.columns:
            continue
        # Déjà porté par une vraie date : ne pas le compter une seconde fois.
        if (ticker, annee) in couverts:
            continue
        seances = annees[annees == annee].index
        if len(seances) == 0:
            continue
        # Le rendement est publié en pourcentage.
        accru.loc[seances, ticker] = float(ligne["valeur"]) / 100 / len(seances)
    return accru


def couverture(cours: pd.DataFrame, fondamentaux: pd.DataFrame,
               dividendes: pd.DataFrame | None = None) -> dict:
    """Sur quelle part de l'archive le dividende est-il connu ?

    Un rendement total calculé sur 35 % des séances et présenté comme
    total serait plus trompeur que le cours nu, qui au moins ne prétend
    rien. Ce chiffre accompagne donc chaque résultat corrigé.

    LA COUVERTURE SE COMPTE EN EXERCICES CONNUS, PAS EN SÉANCES CRÉDITÉES.
    Ce point n'est pas cosmétique : depuis que le dividende se détache à
    sa vraie date, il ne touche que 309 séances sur 2 996. Compter les
    séances non nulles ferait alors chuter la couverture de 35 % à 1 %
    alors qu'on en SAIT PLUS qu'avant — la mesure aurait puni le progrès.
    Est couverte une séance dont l'exercice porte un dividende connu,
    quelle que soit la convention qui le crédite.
    """
    prix = features.serie(cours)
    if prix.empty:
        return {"seances": 0, "part": 0.0, "exercices": []}

    exercices = set()
    if fondamentaux is not None and not fondamentaux.empty:
        connus = fondamentaux[fondamentaux["indicateur"] == "rendement"]
        exercices |= {str(d)[:4] for d in connus["date"]}
    if dividendes is not None and not dividendes.empty \
            and "exercice" in dividendes.columns:
        exercices |= {str(e)[:4] for e in dividendes["exercice"].dropna()}
    exercices = {e for e in exercices if e.isdigit()}

    couvertes = prix.index.to_series().str[:4].isin(exercices)
    return {"seances": int(couvertes.sum()),
            "part": float(couvertes.mean()),
            "exercices": sorted(exercices)}


def rendement_courant(
    cours: pd.DataFrame, dividendes: pd.DataFrame, fenetre_jours: int = 365
) -> pd.DataFrame:
    """Série du rendement du dividende : dividendes glissants / cours.

    Les dividendes des `fenetre_jours` derniers jours CALENDAIRES, et non
    des N dernières séances : un détachement annuel doit rester compté
    pendant douze mois, quel que soit le nombre de jours cotés entre-temps.
    """
    prix = features.serie(cours)
    if prix.empty or dividendes.empty:
        return pd.DataFrame()

    div = dividendes.copy()
    div["date_detachement"] = pd.to_datetime(div["date_detachement"],
                                             errors="coerce")
    div = div.dropna(subset=["date_detachement", "montant"])
    if div.empty:
        return pd.DataFrame()

    dates = pd.to_datetime(pd.Series(prix.index), errors="coerce")
    glissant = pd.DataFrame(0.0, index=prix.index, columns=prix.columns)
    for ticker, groupe in div.groupby("ticker"):
        if ticker not in glissant.columns:
            continue
        for date, montant in zip(dates, glissant.index):
            fenetre = groupe[
                (groupe["date_detachement"] <= date)
                & (groupe["date_detachement"] > date - pd.Timedelta(days=fenetre_jours))
            ]
            glissant.loc[montant, ticker] = float(fenetre["montant"].sum())

    return (glissant / prix.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)


# Valeur critique de Dickey-Fuller à 5 %, régression avec constante sans
# tendance. En deçà, l'hypothèse « la série n'a pas de moyenne où revenir »
# n'est pas rejetée.
SEUIL_DICKEY_FULLER = -2.86


def ajuster_ou(serie: pd.Series) -> tuple[float, float]:
    """(équilibre μ, vitesse θ) d'un processus d'Ornstein-Uhlenbeck.

    Régression de Δy sur y : Δy = a + b·y, d'où θ = -b et μ = a/θ.

    LE COEFFICIENT NE SUFFIT PAS, IL FAUT SA SIGNIFICATIVITÉ. Les moindres
    carrés appliqués à une marche aléatoire rendent presque toujours un `b`
    légèrement négatif — c'est le biais de Dickey-Fuller, et il est massif :
    mesuré sur ce code avant correction, un retour à la moyenne était
    « détecté » sur 162 marches aléatoires sur 200. Estimer θ sans le tester
    revient donc à inventer un équilibre et une demi-vie à des séries qui
    n'en ont pas, et à en tirer un signal aussi confiant que faux.

    On calcule donc la statistique t du coefficient et on la compare à la
    valeur critique de Dickey-Fuller. Au-dessus, la fonction rend NaN.
    """
    y = serie.dropna()
    if len(y) < 30 or y.nunique() < 5:
        return float("nan"), float("nan")

    precedent = y.iloc[:-1].to_numpy()
    delta = y.diff().dropna().to_numpy()
    ecart = precedent - precedent.mean()
    somme_carres = float((ecart ** 2).sum())
    if somme_carres == 0:
        return float("nan"), float("nan")

    b, a = np.polyfit(precedent, delta, 1)
    theta = -b
    if theta <= 0:
        return float("nan"), float("nan")

    residus = delta - (b * precedent + a)
    ddl = len(delta) - 2
    if ddl <= 0:
        return float("nan"), float("nan")
    variance = float((residus ** 2).sum()) / ddl
    erreur_type = np.sqrt(variance / somme_carres)
    if erreur_type == 0:
        return float("nan"), float("nan")

    if b / erreur_type > SEUIL_DICKEY_FULLER:
        # Retour à la moyenne non significatif : très probablement une
        # marche aléatoire, dont l'équilibre estimé n'existe pas.
        return float("nan"), float("nan")

    return float(a / theta), float(theta)


def demi_vie(theta: float) -> float:
    """Temps, en séances, pour combler la moitié de l'écart à l'équilibre."""
    if not np.isfinite(theta) or theta <= 0:
        return float("inf")
    return float(np.log(2) / theta)


def signal(
    cours: pd.DataFrame,
    dividendes: pd.DataFrame,
    tickers: list[str] | None = None,
    reglages: dict | None = None,
) -> pd.DataFrame:
    """Écart normalisé au rendement d'équilibre, par valeur.

    `ecart_normalise` positif = rendement au-dessus de sa moyenne, donc
    cours déprimé, donc appréciation attendue. `exploitable` vaut faux
    lorsque la demi-vie dépasse l'horizon : le retour est alors trop lent
    pour être capté, quel que soit l'écart.
    """
    conf = reglages or charger()
    horizon = int(conf.get("prediction", {}).get("horizon", 60))

    rendements = rendement_courant(cours, dividendes)
    if rendements.empty:
        return pd.DataFrame(columns=COLONNES)

    if tickers is not None:
        gardes = [t for t in tickers if t in rendements.columns]
        rendements = rendements[gardes]

    lignes = []
    for ticker in rendements.columns:
        serie = rendements[ticker].dropna()
        if serie.empty:
            continue
        equilibre, theta = ajuster_ou(serie)
        moitie = demi_vie(theta)
        ecart = serie.std()
        lignes.append({
            "ticker": ticker,
            "rendement": float(serie.iloc[-1]),
            "equilibre": equilibre,
            "ecart_normalise": (
                float((serie.iloc[-1] - equilibre) / ecart)
                if np.isfinite(equilibre) and ecart and np.isfinite(ecart) else float("nan")
            ),
            "demi_vie": moitie,
            "exploitable": bool(np.isfinite(moitie) and moitie <= horizon),
        })

    if not lignes:
        return pd.DataFrame(columns=COLONNES)
    return pd.DataFrame(lignes)[COLONNES].sort_values(
        "ecart_normalise", ascending=False, na_position="last"
    ).reset_index(drop=True)


def expliquer(tableau: pd.DataFrame, horizon: int = 60) -> str:
    if tableau.empty:
        return ("Aucun rendement calculable : il faut des dividendes en base "
                "(« brvm importer-dividendes ») et un historique de cours "
                "couvrant plusieurs détachements.")

    exploitables = int(tableau["exploitable"].sum())
    estimes = int(np.isfinite(tableau["equilibre"]).sum())
    lignes = [
        f"{len(tableau)} valeurs, {estimes} au retour à la moyenne établi, "
        f"dont {exploitables} assez rapide pour un horizon de {horizon} "
        "séances.",
        "",
        f"{'ticker':<8}{'rdt':>8}{'équil.':>9}{'écart':>8}{'demi-vie':>10}",
    ]
    for r in tableau.itertuples():
        # Trois états à ne pas confondre : non estimé (historique trop court
        # ou pas de retour significatif), estimé mais trop lent, exploitable.
        # Écrire « trop lent » dans le premier cas ferait croire à une
        # mesure là où il n'y a rien de mesuré.
        if not np.isfinite(r.equilibre):
            lignes.append(
                f"{r.ticker:<8}{r.rendement:>7.2%}{'—':>9}{'—':>8}{'—':>10}"
                "  (non estimé : historique trop court ou pas de retour "
                "significatif)"
            )
            continue
        marque = "" if r.exploitable else "  (trop lent)"
        lignes.append(
            f"{r.ticker:<8}{r.rendement:>7.2%}{r.equilibre:>9.2%}"
            f"{r.ecart_normalise:>+8.2f}{r.demi_vie:>10.0f}{marque}"
        )
    lignes += [
        "",
        "Écart positif = rendement au-dessus de sa moyenne, donc cours "
        "déprimé, donc appréciation attendue. Une demi-vie supérieure à "
        "l'horizon rend le signal inexploitable, quel que soit l'écart : "
        "le retour aura lieu après qu'on aura vendu.",
    ]
    return "\n".join(lignes)
