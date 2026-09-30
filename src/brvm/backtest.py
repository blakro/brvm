"""Simulation historique du classement produit par `scoring`.

CE QUE CE MODULE NE PEUT PAS VOUS DIRE
--------------------------------------
Trois biais lui survivent, et aucun n'est corrigeable avec les données dont
le projet dispose. Ils sont rappelés dans `AVERTISSEMENTS`, qui accompagne
chaque résultat — pour qu'un chiffre flatteur ne circule jamais sans eux.

1. BIAIS DU SURVIVANT. Le référentiel liste les sociétés cotées
   aujourd'hui. Une société radiée entre-temps a disparu de l'univers, y
   compris des périodes où elle cotait encore — et elle a généralement été
   radiée après avoir mal fini. Le passé simulé est donc celui des
   survivants, et il est plus beau que le vrai.

2. PAS DE DIVIDENDES. La table `cours` porte des cours nus. Sur la BRVM,
   où les rendements dépassent souvent 5 %, les ignorer sous-estime la
   performance de toutes les stratégies — et pénalise doublement les
   valeurs de rendement, celles-là mêmes que le momentum délaisse.

3. FRAIS ESTIMÉS. Commissions et impact sont des paramètres, pas des
   relevés de courtage. Ils sont pris par défaut du côté prudent.

CE QU'IL PROTÈGE, EN REVANCHE
-----------------------------
Le regard en avant, qui est l'erreur qui transforme une stratégie médiocre
en courbe magnifique. Deux garde-fous :

- la décision d'une date `t` ne voit que les cours jusqu'à `t` inclus, le
  classement étant recalculé sur une tranche coupée à `t` ;
- l'exécution est retardée d'une séance : on décide sur la clôture de `t`,
  on achète à celle de `t+1`. Décider et exécuter au même cours revient à
  passer un ordre à un prix déjà connu ;
- on ne décide que sur une COTATION RÉELLE. Les traits se calculent sur des
  cours reportés, faute de quoi la moitié illiquide du marché sort du
  classement — mais choisir une valeur le jour où elle n'a pas échangé
  revient à passer un ordre à un prix que personne n'a traité, et c'est le
  regard en avant le plus rentable qui existe : on achèterait
  systématiquement au dernier cours connu d'un titre en train de bouger.

LA QUESTION DES FRAIS, ET POURQUOI ELLE SE POSE ICI
---------------------------------------------------
Sur cette place, les frais ne rabotent pas un avantage, ils le renversent.
Le courtage SGI, la rétrocession BRVM, les frais DC/BR et les taxes font 2,5
à 3,5 % l'aller-retour — des POURCENTS, là où les places développées
comptent en points de base. Tout résultat de ce module se lit donc contre sa
référence, jamais contre zéro.

Deux outils pour cela, et le second est le plus utile :

- `backtester(scores=...)` rejoue N'IMPORTE QUEL signal, et non plus le seul
  composite de la configuration. C'était un angle mort : `prediction.py`,
  le module dont on veut le plus savoir s'il gagne de l'argent, n'était pas
  backtestable. On mesurait son IC, jamais ce qu'il en reste après le
  courtier.

- `seuil_frais(...)` rend le NIVEAU DE FRAIS auquel la stratégie cesse de
  battre la simple détention du même univers. « Ça ne survit pas aux
  frais » est vrai et inutilisable : le lecteur ne sait pas s'il en est loin
  de 10 % ou d'un facteur dix. Le seuil, lui, se compare au devis d'une SGI.

CE QUE LES DEUX DONNENT SUR L'ARCHIVE, et il faut le lire en entier :

                                  écart sans frais   seuil   réel
    composite de la configuration        -5,42 %      aucun   1,50 %
    choc de volume                       +3,37 %     0,69 %   1,50 %

Le composite PERD contre l'univers équipondéré même à frais nuls : ce n'est
pas le courtier qui le condamne, c'est le signal. Le choc de volume, lui,
gagne réellement avant frais — mais son seuil vaut 0,69 % par sens quand le
marché en coûte 1,50 %. Il manque un facteur deux, et la relation de Grinold
(alpha = IC × dispersion × écart de score) donne indépendamment 0,43 % : deux
méthodes, le même ordre de grandeur, le même verdict.

Il ne manque donc pas un réglage. La zone tampon a été essayée pour réduire
la rotation — voir `tampon` dans `backtester` — et aucun réglage n'est
positif hors échantillon.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import dividende, features, scoring
from .config import charger

AVERTISSEMENTS = (
    "univers restreint aux sociétés cotées aujourd'hui (biais du survivant)",
    "dividendes non pris en compte",
    "frais et impact estimés, non relevés",
)

# Le même jeu, quand le dividende EST pris en compte. Le deuxième
# avertissement change de nature plutôt que de disparaître : la
# correction est partielle et approximée, et le taire serait pire que
# l'ancien aveu d'ignorance.
AVERTISSEMENTS_AVEC_DIVIDENDES = (
    "univers restreint aux sociétés cotées aujourd'hui (biais du survivant)",
    "dividende réparti sur l'exercice faute de date de détachement, et "
    "connu sur une partie seulement de la période",
    "frais et impact estimés, non relevés",
)

# Le jeu servi quand le calendrier daté couvre la période. Le deuxième
# avertissement disparaît alors — non par optimisme, mais parce qu'il
# décrivait une approximation qui n'a plus lieu d'être. En garder la trace
# après coup serait aussi trompeur que l'avoir tue avant.
AVERTISSEMENTS_DATES = (
    "univers restreint aux sociétés cotées aujourd'hui (biais du survivant)",
    "dividende détaché à sa date réelle quand le calendrier la donne, "
    "réparti sur l'exercice sinon",
    "frais et impact estimés, non relevés",
)

# Frais par sens essayés par `seuil_frais`, en pourcent, frais et impact
# confondus.
NIVEAUX = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)

COLONNES = ["date_decision", "date_entree", "date_sortie", "positions",
            "rendement", "dividende", "rotation", "cout", "valeur",
            "valeur_reference"]


def _perte_max(valeurs: pd.Series) -> float:
    """Plus forte baisse depuis un sommet, en proportion.

    Le chiffre qui décide si une stratégie est tenable : un rendement
    annuel de 15 % assorti d'une perte maximale de 60 % ne se garde pas
    jusqu'au bout, et une stratégie qu'on abandonne au creux ne rapporte
    pas ce que le backtest annonce.
    """
    if valeurs.empty:
        return float("nan")
    sommets = valeurs.cummax()
    return float((valeurs / sommets - 1).min())


def _annualiser(valeur_finale: float, seances: int) -> float:
    if seances <= 0 or valeur_finale <= 0:
        return float("nan")
    return float(valeur_finale ** (features.SEANCES_PAR_AN / seances) - 1)


def backtester(
    cours: pd.DataFrame,
    referentiel: pd.DataFrame | None = None,
    reglages: dict | None = None,
    fondamentaux: pd.DataFrame | None = None,
    dividendes: pd.DataFrame | None = None,
    scores: pd.DataFrame | None = None,
) -> dict:
    """Rejoue un classement dans le temps. Renvoie mesures et journal.

    Le journal (`etapes`) porte une ligne par rééquilibrage, avec les dates
    de décision, d'entrée et de sortie : c'est lui qu'on relit quand un
    résultat paraît trop beau.

    `scores` — une matrice dates × tickers — REMPLACE le score composite
    pour l'ordre du classement. `scoring.noter` continue de décider QUI est
    éligible (liquidité, traits mesurables) ; le score fourni décide
    seulement dans quel ordre. La séparation compte : sans elle, changer de
    signal changerait aussi l'univers, et deux signaux ne seraient plus
    comparables.

    POURQUOI CE PARAMÈTRE EXISTE. Ce module ne savait rejouer qu'une seule
    chose, le composite de la configuration — et `prediction.py`, qui est le
    module dont on veut le plus savoir s'il gagne de l'argent, n'était donc
    pas backtestable. On mesurait son IC, jamais ce qu'il en reste après le
    courtier. La question « ce signal survit-il aux frais ? » ne pouvait
    littéralement pas être posée. Ses scores hors échantillon sont rendus par
    `prediction.valider`, sous `scores_hors_echantillon`.

    LE REJEU COMMENCE À LA PREMIÈRE DATE DE `scores`. Le calendrier garde
    son départ, mais les décisions antérieures sont sautées, et
    l'annualisation part de la première décision prise. Sans cela, un
    signal qui ne note rien au début — les scores hors échantillon du
    modèle appris, muets pendant la première tranche d'apprentissage —
    laisserait le composite décider à sa place : c'était un dixième des
    décisions du « rejeu du modèle » documenté. Le rejeu mixte donnait un
    écart sans frais plus bas que le modèle seul, mais des frais plus doux,
    le composite tournant moins.
    """
    conf = reglages or charger()
    bt = conf.get("backtest", {})
    positions = int(bt.get("positions", 10))
    pas = int(bt.get("pas_rebalancement", 20))
    delai = int(bt.get("delai_execution", 1))
    tampon = float(bt.get("tampon", 1.0))
    cout_unitaire = (
        float(bt.get("frais_pourcent", 1.0)) + float(bt.get("impact_pourcent", 0.5))
    ) / 100.0

    prix = features.serie(cours)
    dates = list(prix.index)
    # Le dividende vaut 7 à 10 % l'an sur ce marché quand le cours en rend
    # 2,8 : l'ignorer ne biaise pas le résultat à la marge, il en change
    # l'ordre de grandeur. `accroissement` le crédite à sa VRAIE DATE de
    # détachement quand le calendrier la donne, et le répartit sur
    # l'exercice sinon — voir `dividende` pour ce que chaque convention
    # rend et ce qu'elle ne peut pas rendre.
    a_du_dividende = (
        (fondamentaux is not None and not fondamentaux.empty)
        or (dividendes is not None and not dividendes.empty)
    )
    accru = dividende.accroissement(cours, fondamentaux, dividendes) \
        if a_du_dividende else None
    couverture = dividende.couverture(cours, fondamentaux, dividendes) \
        if accru is not None else None
    date = (AVERTISSEMENTS_DATES
            if dividendes is not None and not dividendes.empty else None)
    avertissements = (AVERTISSEMENTS if accru is None
                      else date or AVERTISSEMENTS_AVEC_DIVIDENDES)
    besoin = int(conf.get("analyse", {}).get("fenetre_momentum", 250)) + 1

    vide = {
        "etapes": pd.DataFrame(columns=COLONNES),
        "seances": len(dates),
        "seances_requises": besoin + delai + pas,
        "avertissements": avertissements,
        "couverture_dividende": couverture,
    }
    if len(dates) < besoin + delai + pas:
        return vide

    # Une seule passe glissante, comme dans prediction : le backtest
    # recalculait sinon tous les traits à chaque rééquilibrage.
    matrices = features.traits_glissants(cours, conf)

    # Première décision : celle du calendrier qui tombe sur une date notée
    # par `scores`, s'il y en a — voir la docstring.
    debut = besoin - 1
    if scores is not None and not scores.empty:
        premiere = scores.index.min()
        while debut < len(dates) and dates[debut] < premiere:
            debut += pas

    etapes: list[dict] = []
    detenu: set[str] = set()
    # Les décisions dont l'ordre vient bien de `scores`. Les autres suivent
    # le composite, faute de ligne pour leur date : une séance trop creuse
    # écartée de l'échantillon du modèle, par exemple. Un rejeu « du
    # modèle » qui en contient doit le dire.
    notees = 0
    valeur = 1.0
    valeur_prix = 1.0
    valeur_reference = 1.0

    for i in range(debut, len(dates) - delai - 1, pas):
        entree = i + delai
        sortie = min(i + delai + pas, len(dates) - 1)
        if sortie <= entree:
            break

        # Décision : les traits de la date `i` ne sont fabriqués que de
        # cours antérieurs ou égaux, par construction des fenêtres
        # glissantes. Rien de ce qui suit ne peut influencer le choix.
        traits = pd.DataFrame(
            {nom: matrices[nom].loc[dates[i]]
             for nom in ["cloture", *features.TRAITS]}
        )
        traits.index.name = "ticker"
        # ON NE DÉCIDE QUE SUR UNE COTATION RÉELLE. Les traits se calculent
        # sur des cours reportés — il le faut, sinon la moitié illiquide du
        # marché sort du classement, voir l'en-tête de `features`. Mais
        # choisir une valeur sur son cours reporté, c'est la choisir sur un
        # prix que personne n'a traité ce jour-là. `prediction` applique la
        # même règle ; les deux modules ne peuvent donc pas diverger sur
        # l'univers.
        cotee = matrices["cotee"].loc[dates[i]]
        traits = traits[cotee.reindex(traits.index).fillna(False).astype(bool)]
        classement = scoring.noter(traits, referentiel, conf)
        if classement.empty:
            continue

        eligibles = list(classement["ticker"])
        notee = scores is not None and dates[i] in scores.index
        if notee:
            # L'éligibilité reste celle de `noter` ; seul l'ordre change.
            ordre = (scores.loc[dates[i]].reindex(eligibles).dropna()
                     .sort_values(ascending=False))
            eligibles = list(ordre.index)
        if not eligibles:
            continue

        # ZONE TAMPON. Une ligne détenue est conservée tant qu'elle reste
        # dans les `positions × tampon` premiers, au lieu d'être vendue dès
        # qu'elle quitte les `positions` premiers. À 1, c'est le
        # comportement d'origine.
        #
        # MESURÉE, ELLE NE SAUVE PAS LE SIGNAL, et c'est écrit ici pour que
        # personne ne la retente en espérant mieux. Écart annualisé contre
        # l'univers éligible, signal du choc de volume, frais réels :
        #
        #     tampon   tout   1re moitié   2nde moitié   rotation
        #        1,0  -3,86 %    -5,58 %      -4,60 %      64 %
        #        1,5  -0,59 %    -0,43 %      -3,43 %      48 %
        #        2,0  -2,98 %    -0,22 %      -1,25 %      35 %
        #        3,0  +0,46 %    +1,13 %      -4,56 %      17 %
        #
        # Lire la dernière ligne lentement. Sur l'historique entier, 3,0 est
        # le seul réglage POSITIF, et il est le meilleur sur la première
        # moitié — donc celui qu'on choisirait. Sur la seconde, jamais
        # consultée, il est parmi les PIRES. Le +0,46 % n'existe pas : c'est
        # la meilleure case d'une grille, et une grille a toujours une
        # meilleure case.
        #
        # La rotation baisse bien, de 64 % à 17 %, mais l'avantage baisse
        # avec elle. La raison est mesurable ailleurs : le choc de volume
        # retombe au pur hasard en deux périodes (voir
        # `features.TRAITS_PREDICTION`). On ne peut pas détenir pour amortir
        # un frais quand ce qu'on détient a cessé d'être bon — et il faudrait
        # détenir dix mois pour amortir un aller-retour à 3 %.
        #
        # Le défaut reste donc 1,0. Le réglage existe pour qu'on puisse
        # refaire la mesure, pas pour qu'on l'utilise.
        large = int(round(positions * max(1.0, tampon)))
        gardes: list[str] = []
        if tampon > 1.0 and detenu:
            gardes = [t for t in eligibles[:large] if t in detenu][:positions]
        choisis = gardes + [t for t in eligibles if t not in gardes]
        choisis = choisis[:positions]

        depart = prix.iloc[entree]
        arrivee = prix.iloc[sortie]
        rendements = (arrivee / depart - 1).replace([np.inf, -np.inf], np.nan)

        gain_prix = float(rendements.reindex(choisis).dropna().mean())
        if np.isnan(gain_prix):
            continue

        # Le dividende accru pendant la détention, de l'entrée à la sortie.
        gain_dividende = 0.0
        appoint_reference = 0.0
        if accru is not None:
            tranche = accru.iloc[entree:sortie]
            gain_dividende = float(tranche[choisis].sum().mean())
            appoint_reference = float(
                tranche[[t for t in eligibles if t in tranche.columns]]
                .sum().mean())
        gain = gain_prix + gain_dividende

        gain_reference = float(rendements.reindex(eligibles).dropna().mean())
        if not np.isnan(gain_reference):
            gain_reference += appoint_reference

        # Chaque ligne remplacée est vendue puis rachetée : deux passages
        # de frais sur la fraction renouvelée.
        nouveaux = set(choisis)
        rotation = (
            len(nouveaux - detenu) / len(nouveaux) if nouveaux else 0.0
        )
        cout = rotation * cout_unitaire * 2
        detenu = nouveaux
        notees += int(notee)

        valeur *= 1 + gain - cout
        valeur_prix *= 1 + gain_prix - cout
        valeur_reference *= 1 + (
            gain_reference if not np.isnan(gain_reference) else 0.0
        )

        etapes.append({
            "date_decision": dates[i],
            "date_entree": dates[entree],
            "date_sortie": dates[sortie],
            "positions": ", ".join(choisis),
            "rendement": gain_prix,
            "dividende": gain_dividende,
            "rotation": rotation,
            "cout": cout,
            "valeur": valeur,
            "valeur_reference": valeur_reference,
        })

    journal = pd.DataFrame(etapes, columns=COLONNES)
    if journal.empty:
        return vide

    seances = len(dates) - debut
    return {
        "etapes": journal,
        "seances": len(dates),
        "rebalancements": len(journal),
        # None sans `scores` : la question ne se pose pas.
        "decisions_notees": None if scores is None else notees,
        "rendement_total": valeur - 1,
        "rendement_annualise": _annualiser(valeur, seances),
        "rendement_prix": valeur_prix - 1,
        "rendement_prix_annualise": _annualiser(valeur_prix, seances),
        "apport_dividende": valeur - valeur_prix,
        "reference_total": valeur_reference - 1,
        "reference_annualisee": _annualiser(valeur_reference, seances),
        "perte_max": _perte_max(journal["valeur"]),
        "perte_max_reference": _perte_max(journal["valeur_reference"]),
        "rotation_moyenne": float(journal["rotation"].mean()),
        "cout_cumule": float(journal["cout"].sum()),
        "avertissements": avertissements,
        "couverture_dividende": couverture,
    }


def seuil_frais(
    cours: pd.DataFrame,
    referentiel: pd.DataFrame | None = None,
    reglages: dict | None = None,
    fondamentaux: pd.DataFrame | None = None,
    dividendes: pd.DataFrame | None = None,
    scores: pd.DataFrame | None = None,
    niveaux: tuple[float, ...] = NIVEAUX,
) -> dict:
    """À partir de quels frais la stratégie cesse-t-elle de battre l'univers ?

    POURQUOI CETTE FONCTION VAUT MIEUX QU'UN VERDICT. « Ça ne survit pas aux
    frais » est vrai et inutilisable : le lecteur ne sait pas s'il en est
    loin de 10 % ou d'un facteur dix, ni ce que changerait un courtier moins
    cher. Le seuil, lui, est actionnable — et il se compare directement au
    devis d'une SGI.

    `niveaux` est en POURCENT PAR SENS, frais et impact confondus : c'est la
    grandeur que facture un intermédiaire. L'aller-retour vaut le double.

    Ce que la fonction rend, sur l'archive et pour le signal du choc de
    volume — le seul du projet dont le pouvoir prédictif tienne :

        seuil mesuré        0,25 à 0,50 % par sens selon la moitié
                            d'historique retenue
        seuil théorique     0,43 % par sens, par la relation de Grinold
                            (alpha = IC × dispersion × écart de score)
        réel               1,50 % par sens dans la configuration

    Deux méthodes indépendantes, le même ordre de grandeur, et le même
    verdict : il manque un facteur trois à six. Ce n'est pas un réglage à
    trouver, c'est un marché trop cher pour ce signal.
    """
    conf = reglages or charger()
    base = conf.get("backtest", {})
    lignes = []
    # Les avertissements sont repris du backtest RÉELLEMENT exécuté, et non
    # figés ici : ils changent selon que le dividende a pu être compté et
    # daté, et un avertissement qui décrit autre chose que le calcul rendu
    # est pire que pas d'avertissement.
    avertissements = AVERTISSEMENTS
    # Les décisions ne dépendent pas des frais : le premier rejeu suffit à
    # les compter.
    rebalancements, notees = 0, None
    for niveau in niveaux:
        # `frais` porte tout : séparer frais et impact n'aurait de sens que
        # si on cherchait lequel des deux mord, et ils mordent pareil.
        essai = {**conf, "backtest": {**base, "frais_pourcent": float(niveau),
                                      "impact_pourcent": 0.0}}
        resultat = backtester(cours, referentiel, essai, fondamentaux,
                             dividendes, scores=scores)
        if resultat["etapes"].empty:
            continue
        avertissements = resultat["avertissements"]
        rebalancements = resultat["rebalancements"]
        notees = resultat["decisions_notees"]
        ecart = (resultat["rendement_annualise"]
                 - resultat["reference_annualisee"])
        lignes.append({
            "frais_par_sens": niveau / 100.0,
            "aller_retour": 2 * niveau / 100.0,
            "rendement_annualise": resultat["rendement_annualise"],
            "reference_annualisee": resultat["reference_annualisee"],
            "ecart": ecart,
            "rotation_moyenne": resultat["rotation_moyenne"],
        })

    table = pd.DataFrame(lignes)
    vide = {"niveaux": table, "seuil": float("nan"),
            "ecart_sans_frais": float("nan"), "reel": None,
            "rebalancements": 0, "decisions_notees": None,
            "avertissements": avertissements}
    if table.empty:
        return vide

    reel = (float(base.get("frais_pourcent", 1.0))
            + float(base.get("impact_pourcent", 0.5))) / 100.0
    return {
        "niveaux": table,
        "seuil": _seuil(table),
        "ecart_sans_frais": float(table.iloc[0]["ecart"]),
        "reel": reel,
        "rebalancements": rebalancements,
        "decisions_notees": notees,
        "avertissements": avertissements,
    }


def _seuil(table: pd.DataFrame) -> float:
    """Le niveau de frais où l'écart change de signe, NaN s'il n'en change pas.

    Dernier niveau où l'écart est encore positif, interpolé linéairement
    avec le premier où il ne l'est plus. L'interpolation n'est pas de la
    précision — c'est pour ne pas faire croire que le seuil est l'un des
    niveaux qu'on a choisi de tester.
    """
    positifs = table[table["ecart"] > 0]
    negatifs = table[table["ecart"] <= 0]
    if not positifs.empty and not negatifs.empty:
        bas = positifs.iloc[-1]
        haut = negatifs.iloc[0]
        largeur = haut["ecart"] - bas["ecart"]
        part = bas["ecart"] / (bas["ecart"] - haut["ecart"]) if largeur else 0.0
        return float(bas["frais_par_sens"]
                     + part * (haut["frais_par_sens"] - bas["frais_par_sens"]))
    if not positifs.empty:
        # Positif partout, jusqu'au niveau le plus élevé testé : on le dit
        # comme une borne, pas comme un seuil.
        return float(positifs.iloc[-1]["frais_par_sens"])
    return float("nan")


def decalages(pas: int, calendriers: int) -> list[int]:
    """Séances retirées en tête de l'archive, une par calendrier.

    Les départs sont espacés régulièrement dans un pas : 0, 10 … 50 pour six
    calendriers à soixante séances ; 0, 3 … 18 pour sept à vingt ; 0 … 4
    pour cinq à cinq. Au-delà de `pas` calendriers, on ne ferait que rejouer
    les mêmes dates de décision amputées de la première : le nombre est donc
    borné à `pas`.
    """
    pas = max(1, int(pas))
    nombre = max(1, min(int(calendriers), pas))
    ecart = max(1, round(pas / nombre))
    if (nombre - 1) * ecart >= pas:
        # L'arrondi par excès ferait sortir le dernier départ du pas, où il
        # retomberait sur un calendrier déjà rejoué.
        ecart = pas // nombre
    return [k * ecart for k in range(nombre)]


def seuil_frais_decale(
    cours: pd.DataFrame,
    referentiel: pd.DataFrame | None = None,
    reglages: dict | None = None,
    fondamentaux: pd.DataFrame | None = None,
    dividendes: pd.DataFrame | None = None,
    scores: pd.DataFrame | None = None,
    niveaux: tuple[float, ...] = NIVEAUX,
    calendriers: int = 1,
) -> dict:
    """`seuil_frais` sur plusieurs calendriers de rééquilibrage décalés.

    UN SEUL CALENDRIER EST UN SEUL TIRAGE. Tourner toutes les soixante
    séances ne tire qu'une quarantaine de dates de décision sur l'archive,
    et le résultat dépend de LESQUELLES : décaler le départ de dix en dix
    séances fait passer le modèle appris de -4,0 % à +5,4 % l'an sans frais.
    C'est ainsi qu'un « +8,0 % sans frais, seuil 1,40 % » s'est glissé dans
    la configuration — un calendrier favorable, pris pour une mesure.

    Chaque calendrier retire les `k` premières séances de `cours` avant
    d'appeler `seuil_frais` ; les dates de décision glissent d'autant. Les
    `scores`, eux, ne bougent pas : ils ont été calculés une fois, sur
    l'archive entière.

    Ce que la fonction rend :

        calendriers     une ligne par calendrier : départ, décisions, écart
                        sans frais, seuil
        niveaux         l'écart MOYEN par niveau de frais, et son étendue
        seuil           celui de l'écart moyen, interpolé comme ailleurs
        seuil_min/max   l'étendue des seuils des calendriers qui en ont un
        sans_seuil      les calendriers qui ne battent pas l'univers, même
                        sans frais
    """
    conf = reglages or charger()
    pas = int(conf.get("backtest", {}).get("pas_rebalancement", 20))
    dates = sorted(cours["date"].unique())

    lignes: list[dict] = []
    tables: list[pd.DataFrame] = []
    avertissements = AVERTISSEMENTS
    reel = None
    for decalage in decalages(pas, calendriers):
        if decalage >= len(dates):
            break
        tranche = cours[cours["date"] >= dates[decalage]]
        resultat = seuil_frais(tranche, referentiel, conf, fondamentaux,
                               dividendes, scores=scores, niveaux=niveaux)
        reel = resultat["reel"] if resultat["reel"] is not None else reel
        if resultat["niveaux"].empty:
            continue
        avertissements = resultat["avertissements"]
        lignes.append({
            "decalage": decalage,
            "rebalancements": resultat["rebalancements"],
            "decisions_notees": resultat["decisions_notees"],
            "ecart_sans_frais": resultat["ecart_sans_frais"],
            "seuil": resultat["seuil"],
        })
        tables.append(resultat["niveaux"].assign(decalage=decalage))

    par_calendrier = pd.DataFrame(lignes)
    if par_calendrier.empty:
        return {"calendriers": par_calendrier, "niveaux": pd.DataFrame(),
                "pas": pas, "seuil": float("nan"), "seuil_min": float("nan"),
                "seuil_max": float("nan"), "sans_seuil": 0,
                "ecart_sans_frais": float("nan"), "reel": reel,
                "avertissements": avertissements}

    # Chaque calendrier retenu porte tous les niveaux : qu'un rejeu soit vide
    # ne dépend pas des frais. La moyenne se fait donc toujours sur la même
    # population, d'une ligne du tableau à l'autre.
    tout = pd.concat(tables, ignore_index=True)
    moyenne = tout.groupby("frais_par_sens", sort=True).agg(
        aller_retour=("aller_retour", "first"),
        rendement_annualise=("rendement_annualise", "mean"),
        reference_annualisee=("reference_annualisee", "mean"),
        ecart=("ecart", "mean"),
        ecart_min=("ecart", "min"),
        ecart_max=("ecart", "max"),
        rotation_moyenne=("rotation_moyenne", "mean"),
    ).reset_index()

    seuils = par_calendrier["seuil"].dropna()
    return {
        "calendriers": par_calendrier,
        "niveaux": moyenne,
        "pas": pas,
        "seuil": _seuil(moyenne) if not moyenne.empty else float("nan"),
        "seuil_min": float(seuils.min()) if len(seuils) else float("nan"),
        "seuil_max": float(seuils.max()) if len(seuils) else float("nan"),
        "sans_seuil": int(par_calendrier["seuil"].isna().sum()),
        "ecart_sans_frais": (float(moyenne.iloc[0]["ecart"])
                             if not moyenne.empty else float("nan")),
        "reel": reel,
        "avertissements": avertissements,
    }


def expliquer_seuil(resultat: dict) -> str:
    """Rendu texte du seuil de frais. Le réel à côté du seuil, toujours."""
    if resultat["niveaux"].empty:
        return ("Seuil de frais incalculable : pas assez de séances pour un "
                "seul rééquilibrage.")
    seuil, reel = resultat["seuil"], resultat["reel"]
    lignes = [
        f"Écart contre l'univers éligible, SANS frais : "
        f"{resultat['ecart_sans_frais']:+.2%} l'an.",
        "",
        f"  {'frais par sens':>15}{'aller-retour':>14}{'écart':>10}{'rotation':>10}",
        f"  {'-' * 15}{'-' * 14}{'-' * 10}{'-' * 10}",
    ]
    for ligne in resultat["niveaux"].itertuples():
        marque = "  ←" if reel and abs(ligne.frais_par_sens - reel) < 1e-9 else ""
        lignes.append(
            f"  {ligne.frais_par_sens:>15.2%}{ligne.aller_retour:>14.1%}"
            f"{ligne.ecart:>+10.2%}{ligne.rotation_moyenne:>10.0%}{marque}")
    lignes.append("")
    if seuil != seuil:  # NaN
        lignes.append("Aucun seuil dans la plage testée : l'écart ne change "
                      "pas de signe.")
    else:
        lignes.append(
            f"SEUIL : {seuil:.2%} par sens. Au-delà, la stratégie rend moins "
            f"que la simple détention du même univers.")
    lignes += _comparer_au_reel(seuil, reel)
    lignes += _decisions_hors_signal(resultat.get("rebalancements", 0),
                                     resultat.get("decisions_notees"))
    lignes += ["", "À retenir avant de citer ces chiffres :"]
    lignes += [f"  - {a}" for a in resultat["avertissements"]]
    return "\n".join(lignes)


def _comparer_au_reel(seuil: float, reel: float | None) -> list[str]:
    if reel is None or seuil != seuil:
        return []
    if reel > seuil:
        return [f"Les frais réels valent {reel:.2%} par sens, soit "
                f"{reel / seuil:.1f} fois le seuil. Il ne manque pas un "
                "réglage, il manque un courtier."]
    return [f"Les frais réels ({reel:.2%}) sont sous le seuil — "
            "vérifiez la rotation et les avertissements avant d'y croire."]


def _decisions_hors_signal(rebalancements: int, notees: int | None) -> list[str]:
    """Les décisions que le signal fourni n'a pas ordonnées, s'il y en a.

    Le rejeu commence à la première date du signal, mais le signal peut
    avoir des trous ensuite : une séance trop creuse est écartée de
    l'échantillon du modèle appris, et la décision de ce jour-là suit le
    composite. Le taire ferait passer un rejeu mixte pour celui du signal.
    """
    if notees is None or notees >= rebalancements:
        return []
    return ["", f"{rebalancements - notees} décision(s) sur {rebalancements} "
                "tombent hors des dates notées par le signal et suivent le "
                "composite."]


def expliquer_seuil_decale(resultat: dict) -> str:
    """Rendu texte du seuil moyenné sur des calendriers décalés.

    La moyenne ne circule jamais sans son étendue : c'est l'écart entre le
    pire et le meilleur calendrier qui dit ce que vaut un calendrier seul.
    """
    par_calendrier = resultat["calendriers"]
    if par_calendrier.empty:
        return ("Seuil de frais incalculable : pas assez de séances pour un "
                "seul rééquilibrage.")
    pas, reel = resultat["pas"], resultat["reel"]
    departs = list(par_calendrier["decalage"])
    enumeration = (", ".join(map(str, departs)) if len(departs) <= 4 else
                   f"{departs[0]}, {departs[1]} … {departs[-1]}")
    sans_frais = par_calendrier["ecart_sans_frais"]
    lignes = [
        f"Rééquilibrage toutes les {pas} séances, moyenne sur "
        f"{len(departs)} calendrier(s) décalé(s) — départs {enumeration}.",
        f"Écart contre l'univers éligible, SANS frais : "
        f"{resultat['ecart_sans_frais']:+.2%} l'an en moyenne, de "
        f"{sans_frais.min():+.2%} à {sans_frais.max():+.2%} selon le "
        "calendrier.",
        "",
        f"  {'frais par sens':>15}{'aller-retour':>14}{'écart moyen':>13}"
        f"{'le pire':>10}{'le meilleur':>13}{'rotation':>10}",
        f"  {'-' * 15}{'-' * 14}{'-' * 13}{'-' * 10}{'-' * 13}{'-' * 10}",
    ]
    for ligne in resultat["niveaux"].itertuples():
        marque = "  ←" if reel and abs(ligne.frais_par_sens - reel) < 1e-9 else ""
        lignes.append(
            f"  {ligne.frais_par_sens:>15.2%}{ligne.aller_retour:>14.1%}"
            f"{ligne.ecart:>+13.2%}{ligne.ecart_min:>+10.2%}"
            f"{ligne.ecart_max:>+13.2%}{ligne.rotation_moyenne:>10.0%}{marque}")

    lignes.append("")
    seuil, sans_seuil = resultat["seuil"], resultat["sans_seuil"]
    if seuil != seuil:
        lignes.append("Aucun seuil pour l'écart moyen : il ne change pas de "
                      "signe dans la plage testée.")
    else:
        lignes.append(f"SEUIL de l'écart moyen : {seuil:.2%} par sens.")
    if sans_seuil == len(departs):
        lignes.append("Aucun calendrier ne bat l'univers, même sans frais.")
    else:
        bas = ("aucun" if sans_seuil else f"{resultat['seuil_min']:.2%}")
        precision = (f" ({sans_seuil} fois sur {len(departs)})"
                     if sans_seuil else "")
        lignes.append(f"Seuil selon le calendrier : {bas}{precision} à "
                      f"{resultat['seuil_max']:.2%}.")
    lignes += _comparer_au_reel(seuil, reel)

    notees = par_calendrier["decisions_notees"]
    avec_signal = notees.notna().all()
    lignes += ["", "Calendrier par calendrier :",
               f"  {'départ':>8}{'décisions':>11}"
               + (f"{'notées':>8}" if avec_signal else "")
               + f"{'sans frais':>12}{'seuil':>9}"]
    for ligne in par_calendrier.itertuples():
        seuil_ligne = ("aucun" if ligne.seuil != ligne.seuil
                       else f"{ligne.seuil:.2%}")
        lignes.append(
            f"  {ligne.decalage:>8}{ligne.rebalancements:>11}"
            + (f"{int(ligne.decisions_notees):>8}" if avec_signal else "")
            + f"{ligne.ecart_sans_frais:>+12.2%}{seuil_ligne:>9}")
    if avec_signal and (notees < par_calendrier["rebalancements"]).any():
        lignes += ["", "Les décisions non notées tombent hors des dates du "
                       "signal et suivent le composite."]

    lignes += ["", "À retenir avant de citer ces chiffres :"]
    lignes += [f"  - {a}" for a in resultat["avertissements"]]
    return "\n".join(lignes)


def expliquer(resultat: dict) -> str:
    """Rendu texte, avertissements compris — ils ne sont pas optionnels."""
    if resultat["etapes"].empty:
        return (
            f"Backtest impossible : {resultat['seances']} séances en base, "
            f"{resultat['seances_requises']} nécessaires. Le momentum se "
            "mesure sur un an ; il faut au moins cela avant la première "
            "décision, plus une période à mesurer ensuite."
        )

    pct = lambda x: "—" if pd.isna(x) else f"{x:+.1%}"  # noqa: E731
    lignes = [
        f"{resultat['rebalancements']} rééquilibrages sur "
        f"{resultat['seances']} séances",
        "",
    ]
    couverture = resultat.get("couverture_dividende")
    if couverture:
        lignes += [
            f"Dividende compté sur {couverture['part']:.0%} des séances "
            f"(exercices {', '.join(couverture['exercices'])}) ; il apporte "
            f"{pct(resultat.get('apport_dividende'))} au total.",
            f"Sans lui, la stratégie rendrait "
            f"{pct(resultat.get('rendement_prix_annualise'))} l'an au lieu de "
            f"{pct(resultat['rendement_annualise'])}.",
            "",
        ]
    lignes += [
        f"{'':<22}{'stratégie':>12}{'référence':>12}",
        f"{'rendement total':<22}{pct(resultat['rendement_total']):>12}"
        f"{pct(resultat['reference_total']):>12}",
        f"{'annualisé':<22}{pct(resultat['rendement_annualise']):>12}"
        f"{pct(resultat['reference_annualisee']):>12}",
        f"{'perte maximale':<22}{pct(resultat['perte_max']):>12}"
        f"{pct(resultat['perte_max_reference']):>12}",
        "",
        f"rotation moyenne       {resultat['rotation_moyenne']:.0%}",
        f"coût cumulé            {resultat['cout_cumule']:.1%}",
        "",
        "La référence est l'univers éligible équipondéré : c'est elle qu'il",
        "faut battre, pas zéro.",
        "",
        "À retenir avant de citer ces chiffres :",
    ]
    lignes += [f"  - {a}" for a in resultat["avertissements"]]
    return "\n".join(lignes)
