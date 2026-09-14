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

    Un rendement total calculé sur une fraction de l'archive et présenté
    comme total serait plus trompeur que le cours nu, qui au moins ne
    prétend rien. Ce chiffre accompagne donc chaque résultat corrigé.

    LA COUVERTURE SE COMPTE PAR COUPLE (SÉANCE, SOCIÉTÉ), ET C'EST LA
    TROISIÈME DÉFINITION — les deux premières mentaient, chacune à sa
    façon.

    Compter les séances CRÉDITÉES tombait à 1 % dès que le dividende se
    détacha à sa vraie date : il ne touche plus qu'une séance par an et
    par société, alors qu'on en sait plus qu'avant. La mesure punissait le
    progrès.

    Compter les séances dont l'EXERCICE est connu donnait 95 %, et
    flattait tout autant : en 2015, trois sociétés sur trente-cinq ont un
    dividende retenu, et l'exercice comptait pour couvert dès la
    première. Un lecteur y voyait un rendement total presque complet.

    Reste la seule mesure qui ne ment ni dans un sens ni dans l'autre :
    la part des couples (séance, société cotée ce jour-là) dont la société
    a un dividende connu pour l'exercice en cours. Elle vaut 56 % sur
    l'archive du 01/08/2026, ce qui est la vérité.
    """
    prix = features.serie(cours)
    if prix.empty:
        return {"seances": 0, "part": 0.0, "exercices": []}

    # Ce qui est RÉELLEMENT crédité, pas ce que le calendrier annonce :
    # les détachements d'avant la réduction du nominal sont refusés, et
    # les compter ici gonflerait la couverture de ce qu'on vient d'écarter.
    _, connus = detachements(cours, dividendes) if dividendes is not None         else (None, set())
    connus = set(connus)
    if fondamentaux is not None and not fondamentaux.empty:
        mesures = fondamentaux[fondamentaux["indicateur"] == "rendement"]
        connus |= {(str(t), str(d)[:4])
                   for t, d in zip(mesures["ticker"], mesures["date"])}

    annees = prix.index.to_series().str[:4]
    cote = prix.notna()
    couvert = pd.DataFrame(False, index=prix.index, columns=prix.columns)
    for ticker in prix.columns:
        exercices = [a for (t, a) in connus if t == ticker]
        if exercices:
            couvert[ticker] = annees.isin(exercices).values

    paires = int(cote.values.sum())
    retenues = int((couvert & cote).values.sum())
    return {"seances": retenues,
            "part": float(retenues / paires) if paires else 0.0,
            "exercices": sorted({a for _, a in connus if a.isdigit()})}


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

    # SOMMES CUMULÉES PLUTÔT QUE DEUX BOUCLES IMBRIQUÉES. La fenêtre
    # glissante se lisait en refiltrant le calendrier de détachements pour
    # chaque couple (séance, société) : 47 sociétés × 3 000 séances, soit
    # 141 000 filtres pandas et deux bonnes minutes de calcul — ce que
    # l'onglet Prédiction payait à chaque interaction. Les montants étant
    # triés par date, la somme sur ]date − fenêtre, date] est la différence
    # de deux cumuls, et chaque borne se trouve par recherche dichotomique.
    dates = pd.to_datetime(pd.Series(prix.index), errors="coerce")
    fin = dates.to_numpy()
    debut = fin - np.timedelta64(fenetre_jours, "D")
    # Une date de séance illisible ne peut pas encadrer de fenêtre : elle
    # vaut zéro, comme le faisaient les comparaisons avec NaT.
    datee = dates.notna().to_numpy()

    glissant = pd.DataFrame(0.0, index=prix.index, columns=prix.columns)
    for ticker, groupe in div.groupby("ticker"):
        if ticker not in glissant.columns:
            continue
        groupe = groupe.sort_values("date_detachement")
        bornes = groupe["date_detachement"].to_numpy()
        montants = pd.to_numeric(groupe["montant"], errors="coerce").fillna(0.0)
        # Le zéro de tête donne un cumul indexable par le rang renvoyé par
        # `searchsorted`, y compris quand aucun détachement ne précède.
        cumul = np.concatenate([[0.0], montants.to_numpy(float).cumsum()])
        # `right` des deux côtés : détachements <= date, moins ceux <=
        # date − fenêtre, ce qui laisse exactement ]date − fenêtre, date].
        somme = (cumul[np.searchsorted(bornes, fin, side="right")]
                 - cumul[np.searchsorted(bornes, debut, side="right")])
        glissant[ticker] = np.where(datee, somme, 0.0)

    return (glissant / prix.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)


# Bandes de rendement du dividende pour le diagnostic d'ajustement. Les
# bornes ne sont pas arbitraires : elles encadrent la limite de variation de
# ±7,5 % par séance, qui est l'explication qu'on cherche à confirmer ou à
# écarter.
BANDES_RENDEMENT = ((0.0, 0.05), (0.05, 0.075), (0.075, 0.15), (0.15, PLAFOND_RENDEMENT))


def ajustement(cours: pd.DataFrame, dividendes: pd.DataFrame,
               fenetres: tuple[int, ...] = (1, 2, 5, 10, 20, 40)) -> dict:
    """Le cours reflète-t-il vraiment le dividende qu'il vient de détacher ?

    POURQUOI CETTE MESURE EXISTE, ET CE QU'ELLE A ÉVITÉ
    ---------------------------------------------------
    Un rendement total se calcule en ajoutant le dividende au rendement du
    cours. L'opération suppose une chose qu'on ne vérifiait pas : que le
    cours archivé ait BAISSÉ du montant détaché. Si le cours ne baisse que
    de la moitié, l'addition fabrique la moitié restante — un rendement qui
    n'a jamais été touché par personne.

    Mesuré sur l'archive, 261 détachements confrontés au cours de la veille,
    nets de la tendance du marché. La part reflétée est la SOMME des baisses
    rapportée à la SOMME des dividendes — voir `_part_refletee` pour
    pourquoi ce n'est pas une moyenne de rapports :

        séances après le détachement    1    2    5   10   20   40
        part du dividende reflétée     42 % 46 % 56 % 69 % 77 % 88 %

    L'ajustement se fait, mais lentement, et à deux séances il manque plus
    de la moitié. Et il en manque partout, pas seulement sur les gros
    dividendes :

        dividende versé      0-5 %   5-7,5 %   7,5-15 %   15-40 %
        reflété à 2 séances   48 %      54 %       54 %      32 %

    LA PREMIÈRE VERSION DE CE DIAGNOSTIC CONCLUAIT « UTILISABLE », et
    l'erreur vaut d'être consignée. Elle lisait la médiane des cas à
    quarante séances — 95 % — et non l'agrégat à deux séances. Deux fautes
    qui allaient dans le même sens : la médiane décrit le détachement
    typique là où la question porte sur ce qu'une étiquette fabrique sur des
    milliers de lignes, et quarante séances mesurent deux mois de marché
    ordinaire bien plus que le détachement. Une mesure trop longue et une
    statistique trop clémente suffisent à valider ce qu'il fallait refuser.

    CE QU'ON NE PEUT PAS SÉPARER, et qu'il faut dire. Plusieurs causes
    concourent et l'archive ne permet pas de les départager : la limite de
    variation de ±7,5 % par séance, qui interdit à un dividende de 9 % de
    tomber d'un coup — 132 détachements sur 261 la dépassent ; les séances
    sans échange, où le cours reporté garde la valeur d'avant détachement ;
    et d'éventuelles incompatibilités d'échelle entre montants publiés et
    cours archivés, dont ce dépôt a déjà rencontré la trace ailleurs (voir
    les séances fantômes de `qualite.py`). Il reste aussi possible qu'une
    part du manque soit réelle : sur les places de frontière, l'ajustement
    incomplet au détachement est documenté. Non séparable veut dire non
    exploitable.

    CE QUE ÇA INTERDIT. Toute étiquette de rendement total sur cette archive
    crédite un dividende que le cours n'a pas rendu — plus de la moitié, en
    agrégat. Un trait qui prédit « un détachement approche » prédit alors ce
    rendement fantôme et non un gain : mesuré, « jours depuis le dernier
    détachement » rend un IC de +0,098 avec un t de +2,5 contre une
    étiquette totale, sur les seules lignes couvertes. Entièrement
    artificiel. C'est ce diagnostic qui l'a démasqué, et c'est pour cela que
    `prediction.construire_echantillon` garde une étiquette de cours nu.

    Rend la part reflétée par fenêtre, la même par bande de rendement, et le
    nombre de détachements confrontés.
    """
    prix = features.serie(cours)
    vide = {"detachements": 0, "rendement_moyen": float("nan"),
            "par_fenetre": {}, "par_bande": {}, "utilisable": False}
    if prix.empty or dividendes is None or dividendes.empty:
        return vide

    dates = list(prix.index)
    rang = {date: i for i, date in enumerate(dates)}
    # La tendance du marché est retirée : sans cela, une chute générale sur
    # la période serait comptée comme un ajustement au dividende.
    marche = prix.pct_change().mean(axis=1).fillna(0.0).cumsum().to_numpy()

    div = dividendes.dropna(subset=["date_detachement", "montant"]).copy()
    div["date_detachement"] = div["date_detachement"].astype(str)
    lignes = []
    for ligne in div.itertuples():
        ticker, jour = ligne.ticker, ligne.date_detachement
        if ticker not in prix.columns or jour not in rang:
            continue
        i = rang[jour]
        if i < 1:
            continue
        veille = prix[ticker].iloc[i - 1]
        if not (np.isfinite(veille) and veille > 0):
            continue
        rendement = float(ligne.montant) / veille
        # Le plafond écarte les incompatibilités d'échelle, pas les
        # dividendes généreux — voir PLAFOND_RENDEMENT.
        if not 0 < rendement < PLAFOND_RENDEMENT:
            continue
        mesure = {"rendement": rendement}
        for fenetre in fenetres:
            j = i - 1 + fenetre
            if j >= len(dates):
                mesure[fenetre] = np.nan
                continue
            cours_apres = prix[ticker].iloc[j]
            if not np.isfinite(cours_apres):
                mesure[fenetre] = np.nan
                continue
            variation = (cours_apres / veille - 1) - (marche[j] - marche[i - 1])
            # LA BAISSE, PAS LE RATIO. Moyenner des rapports dont le
            # dénominateur peut valoir 1 % donne n'importe quoi : un
            # dividende de 3 % assorti d'une baisse de 60 % rend « 2 000 %
            # de reflet ». On garde les deux grandeurs et on agrège
            # ensuite — voir `_part_refletee`.
            mesure[fenetre] = -variation
        lignes.append(mesure)

    if not lignes:
        return vide
    table = pd.DataFrame(lignes)

    def _part_refletee(part: pd.DataFrame, fenetre: int) -> float:
        """Somme des baisses rapportée à la somme des dividendes.

        LE RAPPORT DES AGRÉGATS, et non la moyenne des rapports. C'est la
        grandeur qui gouverne le rendement fantôme d'une étiquette totale :
        sur mille lignes, ce qui se fabrique est la somme de ce qui n'est
        pas tombé, divisée par la somme de ce qui a été versé. Une moyenne
        de ratios répondrait à une autre question, et mal.
        """
        propre = part[["rendement", fenetre]].dropna()
        total = propre["rendement"].sum()
        if total <= 0:
            return float("nan")
        return float(propre[fenetre].sum() / total)
    # LA MOYENNE ET LA MÉDIANE, PARCE QU'ELLES NE DISENT PAS LA MÊME CHOSE ET
    # QUE LA DIFFÉRENCE A FAILLI FAIRE CONCLURE À L'ENVERS. À quarante
    # séances, la médiane vaut 95 % et la moyenne 78 % : une minorité de
    # détachements très mal reflétés tire la seconde. Or la question posée
    # — « une étiquette de rendement total fabrique-t-elle du rendement ? »
    # — porte sur l'AGRÉGAT de milliers de lignes, donc sur la moyenne. Un
    # diagnostic bâti sur la médiane rassurait à tort.
    par_fenetre = {int(f): {
        "agregat": _part_refletee(table, f),
        # La médiane des cas individuels, pour information seulement : elle
        # décrit le détachement typique, pas ce qu'une étiquette fabrique.
        # À quarante séances elle vaut 95 % là où l'agrégat vaut 78 %, et
        # s'y fier faisait conclure à l'envers.
        "mediane_des_cas": float((table[f] / table["rendement"]).median()),
    } for f in fenetres if f in table and table[f].notna().any()}

    # LE VERDICT SE PREND SUR UNE FENÊTRE COURTE, et c'est un choix de
    # méthode. Plus la fenêtre s'allonge, moins ce qu'on mesure a de rapport
    # avec le détachement : à quarante séances, deux mois de marché ordinaire
    # noient l'effet et on lit des « 185 % de reflet » qui ne sont que du
    # bruit. Deux séances laissent à la limite de ±7,5 % le temps d'agir
    # deux fois, et restent assez proches pour que l'attribution tienne.
    reference = min(f for f in par_fenetre) if par_fenetre else None
    for candidat in (2, 1):
        if candidat in par_fenetre:
            reference = candidat
            break

    par_bande = {}
    for bas, haut in BANDES_RENDEMENT:
        part = table[(table["rendement"] >= bas) & (table["rendement"] < haut)]
        if len(part) < 5 or reference is None or reference not in part:
            continue
        par_bande[(bas, haut)] = {
            "detachements": len(part),
            "rendement_moyen": float(part["rendement"].mean()),
            "part_refletee": _part_refletee(part, reference),
        }
    refletee = (par_fenetre[reference]["agregat"]
                if reference is not None else float("nan"))
    return {
        "detachements": len(table),
        "rendement_moyen": float(table["rendement"].mean()),
        "par_fenetre": par_fenetre,
        "par_bande": par_bande,
        "fenetre_verdict": reference,
        "part_refletee": refletee,
        # LE VERDICT, BINAIRE PAR DESSEIN. Sous 90 % de reflet, une étiquette
        # de rendement total crédite plus d'un point de rendement fantôme par
        # détachement — sur un dividende moyen de 9 %, c'est près de six
        # points. Ce n'est pas une imprécision à mentionner en note, c'est
        # une mesure à ne pas faire.
        "utilisable": bool(np.isfinite(refletee) and refletee >= 0.90),
    }


def expliquer_ajustement(resultat: dict) -> str:
    """Rendu texte. Le verdict d'utilisabilité n'est jamais séparé du chiffre."""
    if not resultat["detachements"]:
        return ("Aucun détachement confrontable au cours : calendrier absent, "
                "ou dates hors de l'archive.")
    lignes = [
        f"{resultat['detachements']} détachements confrontés au cours de la "
        f"veille, nets de la tendance du marché.",
        f"Rendement moyen détaché : {resultat['rendement_moyen']:+.2%}.",
        "",
        "  séances après " + "".join(f"{f:>8}" for f in resultat["par_fenetre"]),
        "  reflété (agrég.)" + "".join(f"{m['agregat']:>6.0%} " for m in
                                       resultat["par_fenetre"].values()),
        "  cas médian     " + "".join(f"{m['mediane_des_cas']:>6.0%} " for m in
                                      resultat["par_fenetre"].values()),
        "",
        "  L'agrégat décide — somme des baisses sur somme des dividendes : "
        "c'est lui",
        "  qui gouverne ce qu'une étiquette totale fabrique sur des milliers de",
        f"  lignes. Le verdict se prend à {resultat['fenetre_verdict']} séances, "
        "parce qu'au-delà c'est le",
        "  marché qu'on mesure et non le détachement.",
    ]
    if resultat["par_bande"]:
        lignes += ["", "  par taille du dividende détaché :"]
        for (bas, haut), mesure in resultat["par_bande"].items():
            lignes.append(
                f"    {bas:>5.0%}–{haut:<5.0%} {mesure['detachements']:>4} cas, "
                f"versé {mesure['rendement_moyen']:+.1%}, reflété à "
                f"{mesure['part_refletee']:.0%}")
        lignes += [
            "",
            "Le manque est partout, pas seulement sur les gros dividendes : "
            "même sous la",
            "limite de ±7,5 % par séance, il manque la moitié. Plusieurs "
            "causes concourent",
            "— la limite, les séances sans échange, d'éventuels écarts "
            "d'échelle entre",
            "montants publiés et cours archivés — et l'archive ne permet pas "
            "de les départager.",
        ]
    lignes += [""]
    if resultat["utilisable"]:
        lignes.append(
            "UTILISABLE : le cours reflète le dividende. Une étiquette de "
            "rendement total ne fabriquerait rien.")
    else:
        lignes.append(
            "INUTILISABLE POUR UN RENDEMENT TOTAL. Ajouter le dividende au "
            "rendement du cours créditerait ce que le cours n'a pas rendu, "
            "d'autant plus que le dividende est gros. Un trait qui prédit "
            "l'approche d'un détachement prédirait alors ce rendement "
            "fantôme : c'est arrivé, voir la docstring d'`ajustement`.")
    return "\n".join(lignes)


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
