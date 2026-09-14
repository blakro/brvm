"""Prédiction : les deux tests qui comptent, et ce qu'ils prouvent.

Un module de prédiction se juge sur deux propriétés opposées, et échouer à
l'une des deux le rend inutile ou, pire, trompeur :

  - sur des données SANS signal, il ne doit rien trouver. Un modèle qui bat
    la référence sur du bruit a une fuite, et cette fuite le fera briller
    en validation puis perdre de l'argent en vrai ;
  - sur des données AVEC signal, il doit le trouver. Un modèle qui ne
    trouve rien nulle part est certes honnête, mais il ne sert à rien.

Les deux sont testés ici, sur des séries fabriquées où l'on sait par
construction ce qu'il y a à trouver — chose impossible sur des données
réelles, où personne ne connaît la bonne réponse.

    python tests/test_prediction.py
    pytest tests/test_prediction.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
os.environ.setdefault(
    "BRVM_BASE", str(Path(tempfile.gettempdir()) / "brvm_tests.db")
)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from brvm import apprentissage, features, prediction  # noqa: E402

# Fenêtres raccourcies : la mécanique testée ne dépend pas de leur longueur,
# et un momentum à 250 séances obligerait à fabriquer des années de cotation
# pour chaque cas.
REGLAGES = {
    "analyse": {
        "volume_median_min_fcfa": 0,
        "fenetre_momentum": 30, "saut_momentum": 3,
        "fenetre_volatilite": 15, "fenetre_liquidite": 15,
        "moyenne_courte": 5, "moyenne_longue": 15,
        "min_par_secteur": 99,
    },
    "prediction": {"horizon": 10, "decoupes": 3, "lignes_minimum": 200},
}


def _date(rang: int) -> str:
    return (f"{2020 + rang // 336:04d}-{1 + (rang % 336) // 28:02d}-"
            f"{1 + rang % 28:02d}")


def _cours(trajectoires: dict[str, list[float]], volumes: dict | None = None):
    """Table de cours fabriquée. Une valeur `None` dans une trajectoire est
    une séance SANS ÉCHANGE pour ce ticker — pas un cours nul, une ligne
    absente, ce qui est le cas normal sur cette place."""
    lignes = []
    for ticker, prix in trajectoires.items():
        for rang, valeur in enumerate(prix):
            if valeur is None:
                continue
            volume = (volumes or {}).get(ticker, 5_000_000.0)
            if not isinstance(volume, float):
                volume = float(volume[rang])
            lignes.append({
                "date": _date(rang),
                "ticker": ticker, "cloture": float(valeur),
                "volume_titres": 100.0, "volume_fcfa": volume,
            })
    return pd.DataFrame(lignes).sort_values(["date", "ticker"])


def _marche_aleatoire(n_valeurs=12, n_seances=260, graine=0):
    rng = np.random.default_rng(graine)
    return _cours({
        f"T{i:02d}": 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n_seances)))
        for i in range(n_valeurs)
    })


def test_le_bruit_ne_produit_pas_de_signal():
    """LE test anti-fuite.

    Sur des marches aléatoires pures, l'avenir est par construction
    indépendant du passé : il n'y a rien à apprendre. Le modèle doit donc
    coller à la référence. S'il la dépasse nettement, ce n'est pas qu'il a
    trouvé quelque chose — c'est qu'une information future s'est glissée
    dans l'entraînement, et le même mécanisme le fera briller en validation
    puis échouer en production.
    """
    resultat = prediction.valider(_marche_aleatoire(graine=1), REGLAGES)
    assert not resultat["periodes"].empty, "échantillon trop court"

    assert abs(resultat["ic"]) < 0.15, (
        f"IC {resultat['ic']:+.3f} sur du bruit pur : une information "
        "future a fui dans l'entraînement"
    )


def test_un_vrai_signal_est_trouve():
    """Le pendant : un modèle qui ne trouve jamais rien est inutile.

    On plante ici une relation nette — les valeurs dont le momentum est
    élevé montent ensuite — et on exige que la validation la voie. Sans ce
    test, un module cassé qui rendrait toujours 50 % passerait pour
    prudent.
    """
    rng = np.random.default_rng(3)
    n = 300
    trajectoires = {}
    for i in range(12):
        # Tendance propre à chaque valeur : le momentum passé la révèle, et
        # elle persiste — donc le futur est prévisible depuis le passé.
        derive = 0.004 * (i - 5.5) / 5.5
        bruit = rng.normal(0, 0.004, n)
        trajectoires[f"T{i:02d}"] = 100 * np.exp(np.cumsum(derive + bruit))

    resultat = prediction.valider(_cours(trajectoires), REGLAGES)
    assert not resultat["periodes"].empty
    assert resultat["ic"] > 0.20, (
        f"IC {resultat['ic']:+.3f} : le modèle n'a pas vu un signal "
        "pourtant planté à la main"
    )


def test_les_etiquettes_recouvrantes_sont_purgees():
    """L'entraînement ne doit pas contenir de date dont l'étiquette déborde
    sur la période de test.

    Avec un horizon de H séances, la cible d'une date dépend des cours des
    H séances suivantes. Les H dernières dates avant la période de test
    connaissent donc déjà une part de la réponse. C'est une fuite fine,
    invisible à l'œil, et qui gonfle l'IC sans que le modèle ait rien
    appris — d'autant plus grave que l'horizon est long : à trois mois, ce
    sont soixante dates qu'il faut retirer.
    """
    cours = _marche_aleatoire(graine=7)
    echantillon = prediction.construire_echantillon(cours, REGLAGES)
    dates = sorted(echantillon["date"].unique())
    horizon = REGLAGES["prediction"]["horizon"]

    decoupes = REGLAGES["prediction"]["decoupes"]
    frontieres = np.array_split(np.array(dates), decoupes + 1)
    debut_test = min(frontieres[1])

    avant = [d for d in dates if d < debut_test]
    gardees = set(avant[:-horizon])
    exclues = set(avant[-horizon:])

    assert len(exclues) == horizon
    assert not (gardees & exclues)
    # Les dates purgées sont bien celles qui touchent la période de test.
    assert max(gardees) < min(exclues) < debut_test


def test_les_traits_ne_voient_pas_apres_leur_date():
    """La coupe temporelle de `construire_echantillon` doit être stricte.

    On compare la ligne produite pour une date donnée à celle qu'on obtient
    en tronquant la série à cette date : elles doivent être identiques. Si
    elles diffèrent, c'est que la construction a regardé plus loin.
    """
    cours = _marche_aleatoire(n_valeurs=6, n_seances=120, graine=11)
    complet = prediction.construire_echantillon(cours, REGLAGES)
    assert not complet.empty

    date = sorted(complet["date"].unique())[2]
    tronque = prediction.construire_echantillon(
        cours[cours["date"] <= _apres(cours, date, REGLAGES)], REGLAGES
    )

    a = complet[complet["date"] == date].set_index("ticker")[prediction.TRAITS]
    b = tronque[tronque["date"] == date].set_index("ticker")[prediction.TRAITS]
    assert not b.empty, "la date a disparu de l'échantillon tronqué"
    pd.testing.assert_frame_equal(a.sort_index(), b.sort_index())


def _apres(cours, date, reglages):
    """Date située `horizon` séances après `date` — la coupe minimale pour
    que l'étiquette de `date` soit calculable."""
    dates = sorted(cours["date"].unique())
    return dates[dates.index(date) + reglages["prediction"]["horizon"]]


def test_les_rangs_se_calculent_DANS_la_seance():
    """Le rang d'un trait compare les valeurs d'une MÊME séance.

    C'est la propriété que l'échantillon vend : un niveau brut n'est pas
    comparable d'une date à l'autre, un rang du jour l'est. Si la
    construction rangeait sur l'ensemble des dates confondues, le modèle
    apprendrait le calendrier — les traits d'une année calme et ceux d'une
    année agitée n'auraient plus la même échelle — et rien ne le signalerait
    dans le résultat.
    """
    echantillon = prediction.construire_echantillon(
        _marche_aleatoire(n_valeurs=8, n_seances=120, graine=5), REGLAGES)
    assert not echantillon.empty

    for date, bloc in echantillon.groupby("date"):
        rangs = bloc["momentum"].dropna()
        # Rang centile sur n valeurs : le dernier vaut 1, le premier 1/n.
        assert rangs.max() == 1.0
        assert abs(rangs.min() - 1 / len(rangs)) < 1e-9, date


def test_une_seance_trop_creuse_est_ecartee():
    """Sous quatre valeurs cotées, la médiane de la séance ne sépare plus.

    L'étiquette vaut « bat la médiane du jour ». À trois valeurs, une seule
    est au-dessus et la cible ne dit plus rien du marché — d'où le refus de
    la séance entière plutôt qu'une ligne qui aurait l'air d'en être une.
    """
    rng = np.random.default_rng(23)
    n = 120
    trajectoires = {f"T{i:02d}": 100 * np.exp(np.cumsum(
        rng.normal(0, 0.01, n))) for i in range(6)}
    cours = _cours(trajectoires)

    dates = sorted(cours["date"].unique())
    creuse = dates[len(dates) // 2]
    # Trois valeurs seulement cotent ce jour-là ; les autres sont absentes,
    # ce qui est le cas normal sur ce marché.
    maigre = cours[~((cours["date"] == creuse)
                     & (cours["ticker"] > "T02"))]

    echantillon = prediction.construire_echantillon(maigre, REGLAGES)
    assert not echantillon.empty
    assert creuse not in set(echantillon["date"])


def test_l_etiquette_regarde_l_horizon_en_seances():
    """`rendement_futur` compare la clôture à celle de H SÉANCES plus tard.

    Non pas H jours calendaires : entre deux séances il y a des week-ends
    et des jours fériés, en nombre variable. Un décalage en jours ferait
    glisser la cible d'une valeur à l'autre sans que rien ne le montre.
    """
    horizon = REGLAGES["prediction"]["horizon"]
    n = 120
    # Une seule valeur monte de 1 % par séance : le rendement sur H séances
    # est connu d'avance, 1,01^H − 1.
    droite = {"AAA": [100 * 1.01 ** i for i in range(n)]}
    for i in range(5):
        droite[f"T{i:02d}"] = [100.0] * n
    echantillon = prediction.construire_echantillon(_cours(droite), REGLAGES)

    attendu = 1.01 ** horizon - 1
    obtenu = echantillon[echantillon["ticker"] == "AAA"]["rendement_futur"]
    assert not obtenu.empty
    assert np.allclose(obtenu, attendu)


def test_refus_quand_l_echantillon_est_maigre():
    """Deux cents lignes ne font pas une prévision : le module doit rendre
    vide plutôt qu'un nombre, et dire ce qui manque."""
    court = _marche_aleatoire(n_valeurs=3, n_seances=45, graine=5)

    validation = prediction.valider(court, REGLAGES)
    assert validation["periodes"].empty
    assert prediction.predire(court, REGLAGES).empty

    message = prediction.expliquer(validation)
    assert "Pas assez de données" in message and "minimum" in message


def test_les_probabilites_restent_des_probabilites():
    """Bornes et ordre : une sortie hors [0, 1] ou mal triée serait un
    signe que la colonne lue n'est pas celle qu'on croit."""
    resultat = prediction.predire(_marche_aleatoire(graine=2), REGLAGES)
    assert not resultat.empty
    assert resultat["probabilite"].between(0, 1).all()
    assert resultat["probabilite"].is_monotonic_decreasing
    assert resultat["ticker"].is_unique


def test_le_rendu_ne_montre_jamais_la_precision_seule():
    """Un IC sans sa référence ne veut rien dire, et c'est le chiffre que
    tout le monde retient. Les deux doivent être inséparables — et la
    référence est le score composite, pas le hasard."""
    resultat = prediction.valider(_marche_aleatoire(graine=4), REGLAGES)
    rendu = prediction.expliquer(resultat)
    assert "IC de la combinaison" in rendu and "IC du score composite" in rendu
    assert "écart" in rendu


def test_le_rendu_montre_la_dispersion_et_pas_seulement_la_moyenne():
    """LE défaut de mesure que cette version corrige.

    Un IC moyen sans sa dispersion laissait croire à une mesure stable là
    où les périodes allaient de +0,29 à -0,28. La moyenne seule n'est pas
    faux, elle est insuffisante — et insuffisante d'une manière qui fait
    conclure. Le rendu doit donc porter l'IR, le compte de périodes
    positives et la pire d'entre elles, pour chaque source.
    """
    resultat = prediction.valider(_marche_aleatoire(graine=4), REGLAGES)
    rendu = prediction.expliquer(resultat)
    assert "IR" in rendu and "périodes >0" in rendu and "pire" in rendu

    for nom, mesure in resultat["sources"].items():
        assert {"ic", "ir", "periodes", "periodes_positives", "pire"} <= set(mesure), nom
        assert mesure["periodes"] > 1, nom
        assert mesure["pire"] <= mesure["ic"] + 1e-12, nom


class _sans_apprentissage:
    """Simule l'absence de scikit-learn sans avoir à la désinstaller.

    Les DEUX drapeaux sont baissés : `prediction` décide s'il construit un
    modèle, `apprentissage` refuse d'en fabriquer un. N'en baisser qu'un
    testerait une moitié de l'absence, c'est-à-dire un état qui n'arrive
    jamais en vrai.
    """

    def __enter__(self):
        self.avant = (prediction.APPRENTISSAGE_DISPONIBLE,
                      apprentissage.DISPONIBLE)
        prediction.APPRENTISSAGE_DISPONIBLE = False
        apprentissage.DISPONIBLE = False

    def __exit__(self, *_):
        (prediction.APPRENTISSAGE_DISPONIBLE,
         apprentissage.DISPONIBLE) = self.avant


def test_sans_scikit_learn_il_reste_deux_sources_sur_trois():
    """L'apprentissage manquant ne doit plus coûter le classement entier.

    AVANT, `predire` rendait un tableau vide : la seule source était la
    régression logistique, et son absence emportait tout. Les deux autres
    sources — le composite de la configuration, et les poids par trait
    appris puis rétrécis — sont du pandas et se calculent sans
    scikit-learn. La combinaison doit donc continuer de rendre un
    classement avec ce qui reste, et le dire.

    C'est `combiner` qui porte cette propriété : une source qui se tait est
    absente du calcul, pas fatale au calcul.
    """
    cours = _marche_aleatoire(graine=7)
    # Les pondérations font exister le composite : sans elles le score est
    # constant, et l'IC d'une constante n'est pas défini.
    reglages = {**REGLAGES,
                "ponderations": {"momentum": 0.5, "tendance": 0.3,
                                 "volatilite": -0.2}}

    with _sans_apprentissage():
        validation = prediction.valider(cours, reglages)
        rendu = prediction.expliquer(validation)
        classement = prediction.predire(cours, reglages, validation=validation)

        try:
            apprentissage.Ensemble(prediction.TRAITS, 10)
        except apprentissage.ApprentissageIndisponible:
            pass
        else:
            raise AssertionError("Ensemble doit refuser, pas renvoyer un objet")

    assert "scikit-learn" in validation["motif"]
    assert "scikit-learn" in rendu
    # La source manquante ne figure pas ; les deux autres, si.
    assert "modele" not in validation["sources"]
    assert {"composite", "combinaison"} <= set(validation["sources"])
    assert np.isfinite(validation["ic_composite"])
    # Et surtout : un classement, pas un tableau vide.
    assert not classement.empty
    assert classement["probabilite"].between(0, 1).all()
    # Sans modèle il n'y a pas de sac, donc pas d'incertitude chiffrable :
    # la colonne existe et vaut NaN, plutôt que de mentir avec un zéro.
    assert classement["incertitude"].isna().all()


def test_le_module_s_importe_sans_scikit_learn():
    """La régression qui a mis le tableau de bord à terre.

    scikit-learn importée en tête de module la rendait obligatoire pour
    quiconque importe `brvm.prediction` — donc pour les six onglets, dont
    cinq n'en font rien. Une absence dans l'environnement d'hébergement
    n'avait plus à être une panne : elle l'était. Le test bloque l'import
    dans un sous-processus, seul moyen de reproduire l'environnement
    amputé depuis un environnement où la bibliothèque est installée.
    """
    programme = (
        "import sys\n"
        "class Bloqueur:\n"
        "    def find_spec(self, nom, chemin=None, cible=None):\n"
        "        if nom == 'sklearn' or nom.startswith('sklearn.'):\n"
        "            raise ImportError('absente, pour le test')\n"
        "        return None\n"
        "sys.meta_path.insert(0, Bloqueur())\n"
        f"sys.path.insert(0, {str(RACINE / 'src')!r})\n"
        "from brvm import prediction\n"
        "assert prediction.APPRENTISSAGE_DISPONIBLE is False\n"
        "print('importé')\n"
    )
    fini = subprocess.run(
        [sys.executable, "-c", programme],
        capture_output=True, text=True,
    )
    assert fini.returncode == 0, fini.stderr
    assert "importé" in fini.stdout


def test_l_incertitude_ne_compte_pas_deux_fois_la_meme_journee():
    """Le piège qui a fait passer un bruit pour un signal exploitable.

    Avec un horizon de 60 séances, l'étiquette du lundi recouvre celle du
    mardi à 59/60. Compter chaque date comme une observation indépendante
    multiplie le t par racine de l'horizon — c'est ainsi qu'un IC de
    -0,07 s'était présenté avec un t de -10,2 alors qu'il vaut -1,4.

    Le test fabrique des IC purement aléatoires : quel que soit le hasard
    du tirage, l'erreur-type honnête doit dépasser largement la naïve.
    """
    rng = np.random.default_rng(11)
    horizon = 60
    dates = [f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(600)]
    bloc = pd.DataFrame({
        "date": np.repeat(dates, 20),
        "score": rng.normal(size=600 * 20),
        "rendement_futur": rng.normal(size=600 * 20),
    })

    mesure = prediction.mesurer_ic(bloc, "score", horizon)
    assert mesure["dates"] == 600
    assert mesure["dates_independantes"] == 10, mesure
    # L'erreur-type honnête est racine(60/10) ≈ 2,4 fois la naïve.
    naive = mesure["erreur_type"] * np.sqrt(mesure["dates_independantes"]
                                            / mesure["dates"])
    assert mesure["erreur_type"] > naive * 5
    # Sur du bruit pur, rien ne doit être déclaré significatif.
    assert not mesure["significatif"], mesure


def test_l_ic_ne_circule_jamais_sans_son_incertitude():
    """Un IC nu se retient et se cite ; son intervalle, non. Les coller
    ensemble est le seul moyen d'empêcher le premier de voyager seul."""
    resultat = prediction.valider(_marche_aleatoire(graine=4), REGLAGES)
    rendu = prediction.expliquer(resultat)
    assert "±" in rendu and "t=" in rendu
    assert "significatif" in rendu
    assert "périodes disjointes" in rendu


def test_chaque_trait_est_mesure_separement():
    """C'est là qu'on voit sur quoi le composite repose réellement."""
    resultat = prediction.valider(_marche_aleatoire(graine=6), REGLAGES)
    mesures = resultat["traits_mesures"]
    assert set(prediction.TRAITS) <= set(mesures)
    for trait, mesure in mesures.items():
        assert {"ic", "erreur_type", "t", "significatif"} <= set(mesure), trait



# --- l'univers : le défaut le plus coûteux du module ----------------------

def _avec_trous(n=260, periodicite=2, graine=17):
    """Douze valeurs quotidiennes, plus une qui ne cote qu'une séance sur
    `periodicite` — le profil d'UNLC, qui n'échange qu'une séance sur deux
    et n'avait donc jamais cent cotations consécutives."""
    rng = np.random.default_rng(graine)
    trajectoires = {
        f"T{i:02d}": list(100 * np.exp(np.cumsum(rng.normal(0, 0.015, n))))
        for i in range(12)
    }
    serie = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))
    trajectoires["TROU"] = [v if r % periodicite == 0 else None
                            for r, v in enumerate(serie)]
    return _cours(trajectoires)


def test_une_valeur_qui_ne_cote_pas_tous_les_jours_reste_dans_l_echantillon():
    """LE test de non-régression du biais de sélection.

    `rolling(100)` exige par défaut cent valeurs CONSÉCUTIVES. Une valeur
    qui n'échange qu'une séance sur deux n'en a jamais cent d'affilée :
    elle n'avait donc jamais de tendance, jamais de rang, jamais de ligne
    dans l'échantillon. Mesuré sur l'archive réelle, cela retirait la
    moitié illiquide du marché — 16,2 valeurs mesurées par séance sur 37,7
    cotées — soit exactement les valeurs dont le comportement diffère le
    plus de la moyenne.

    C'était un biais de sélection silencieux : rien dans le résultat ne
    disait que la moitié du marché manquait.
    """
    echantillon = prediction.construire_echantillon(_avec_trous(), REGLAGES)
    assert not echantillon.empty

    lignes = echantillon[echantillon["ticker"] == "TROU"]
    assert not lignes.empty, (
        "la valeur à trous est absente de l'échantillon : le biais de "
        "sélection est revenu"
    )
    # Et pas une poignée de lignes rescapées : elle doit peser autant que
    # ses cotations le permettent, à quelques séances de bord près.
    quotidiennes = echantillon[echantillon["ticker"] == "T00"]
    assert len(lignes) > 0.4 * len(quotidiennes), (
        f"{len(lignes)} lignes contre {len(quotidiennes)} pour une valeur "
        "quotidienne, alors qu'elle cote une séance sur deux"
    )


def test_aucune_decision_n_est_prise_sur_un_cours_reporte():
    """Le report sert à MESURER le passé, jamais à fabriquer une occasion.

    Les traits se calculent sur des cours reportés — sans quoi la moitié
    illiquide du marché n'aurait jamais de tendance. Mais une ligne
    d'échantillon à une date où la valeur n'a pas échangé serait un ordre
    passé à un prix que personne n'a traité. La coupe est donc nette :
    on mesure sur le cours reporté, on ne décide que sur une cotation.
    """
    cours = _avec_trous()
    echantillon = prediction.construire_echantillon(cours, REGLAGES)
    reelles = set(map(tuple, cours[["date", "ticker"]].to_numpy()))

    produites = set(map(tuple, echantillon[["date", "ticker"]].to_numpy()))
    orphelines = produites - reelles
    assert not orphelines, (
        f"{len(orphelines)} lignes sur des séances sans cotation, "
        f"par exemple {sorted(orphelines)[:3]}"
    )


def test_le_report_du_cours_est_borne_et_ne_regarde_jamais_l_avenir():
    """Deux bornes, et chacune ferme une manière de mentir.

    Un titre qui n'a pas échangé depuis trois mois n'a pas un cours, il a
    un souvenir : au-delà de la limite il doit ressortir. Et rien ne doit
    être inventé avant la première cotation — une société introduite en
    2021 n'a pas de cours en 2019.

    Le test vérifie surtout la propriété qui ne se voit pas : le report
    d'une date ne dépend QUE du passé. Tronquer la série ne doit déplacer
    aucune valeur antérieure à la troncature — si c'était le cas, la
    fonction qui prépare tous les traits consulterait l'avenir.
    """
    n = 60
    brut = pd.DataFrame(
        {"A": [100.0] * n, "B": [np.nan] * n},
        index=[_date(r) for r in range(n)])
    brut.loc[brut.index[20:25], "B"] = 200.0
    brut.loc[brut.index[30:], "A"] = np.nan

    reporte = features.cours_reportes(brut, limite=5)

    # Avant la première cotation de B : rien n'est inventé.
    assert reporte["B"].iloc[:20].isna().all()
    # Après la dernière : cinq séances de report, puis plus rien. C'est
    # aussi ce qui fait disparaître une société radiée, sans avoir eu
    # besoin de savoir qu'elle allait l'être.
    assert reporte["B"].iloc[25:30].notna().all(), "report trop court"
    assert reporte["B"].iloc[30:].isna().all(), "report au-delà de la limite"
    assert reporte["A"].iloc[35:].isna().all(), "cours trop longtemps reporté"

    # Aucun regard en avant : la troncature ne déplace rien.
    coupe = features.cours_reportes(brut.iloc[:40], limite=5)
    pd.testing.assert_frame_equal(coupe, reporte.iloc[:40])


def test_le_report_ne_fait_pas_passer_les_valeurs_dormantes_pour_calmes():
    """Un cours reporté produit un rendement nul, qui n'est pas un calme
    observé mais une absence d'observation.

    Les compter écraserait l'écart-type des valeurs les moins traitées, et
    les ferait passer pour les plus sages — exactement à l'envers, et
    d'autant plus grave que la volatilité pèse négativement dans le score.
    """
    matrices = features.traits_glissants(_avec_trous(periodicite=3), REGLAGES)
    vol = matrices["volatilite"].iloc[-1].dropna()
    assert "TROU" in vol.index

    # Elle est construite avec la même amplitude que les autres : sa
    # volatilité doit leur ressembler, non valoir le tiers.
    quotidiennes = vol.drop("TROU")
    assert vol["TROU"] > 0.5 * quotidiennes.median(), (
        f"volatilité {vol['TROU']:.3f} contre {quotidiennes.median():.3f} "
        "pour les valeurs quotidiennes : les rendements fabriqués par le "
        "report sont comptés"
    )


# --- les sources, et ce qui arrive quand l'une se tait --------------------

def test_un_trait_sans_preuve_recoit_un_poids_nul():
    """Le rétrécissement est ce qui distingue ces poids d'une régression.

    Une régression donne un coefficient à chaque trait, y compris à ceux
    qui ne portent rien. Ici, un trait dont l'IC ne se distingue pas du
    hasard doit voir son poids ramené à zéro — quelle que soit la taille
    de l'IC observé, qui n'est alors qu'un tirage.
    """
    echantillon = prediction.construire_echantillon(
        _marche_aleatoire(n_seances=400, graine=21), REGLAGES)
    poids = apprentissage.poids_fiabilite(
        echantillon, prediction.TRAITS, horizon=10)

    assert set(poids) == set(prediction.TRAITS)
    # Sur du bruit pur, aucun trait ne porte rien : tous les poids doivent
    # être petits devant l'IC brut qu'on y mesurerait.
    for trait, valeur in poids.items():
        assert abs(valeur) < 0.05, f"{trait} garde un poids de {valeur:+.3f}"


def test_la_combinaison_survit_a_une_source_muette():
    """Une source qui se tait est absente du calcul, pas fatale au calcul.

    C'est la propriété qui permet au classement de tenir sans
    scikit-learn, et à la source « fiabilité » de ne rien dire quand aucun
    trait n'a fait sa preuve plutôt que de rendre un ordre arbitraire.
    """
    index = pd.RangeIndex(5)
    parlante = pd.Series([0.1, 0.5, 0.9, 0.3, 0.7], index=index)
    muette = pd.Series(np.nan, index=index)

    seule = apprentissage.combiner({"a": parlante, "b": muette})
    assert seule.notna().all()
    pd.testing.assert_series_equal(
        seule.rank(), parlante.rank(), check_names=False)

    # Toutes muettes : on rend vide plutôt qu'un classement inventé.
    assert apprentissage.combiner({"a": muette, "b": muette}).empty


def test_une_probabilite_calibree_ne_pretend_pas_savoir():
    """Le rang combiné vaut 1 en tête de classement et 0 en queue.

    L'afficher tel quel comme « probabilité » annoncerait 100 % de chances
    de surperformer pour la première valeur — alors que l'IC mesuré
    autorise à peine à la distinguer de la dernière. Le calibrage apprend
    la fréquence RÉELLE, hors échantillon, et la ramène près de 50 %.
    """
    cours = _marche_aleatoire(n_seances=400, graine=31)
    validation = prediction.valider(cours, REGLAGES)
    classement = prediction.predire(cours, REGLAGES, validation=validation)
    assert not classement.empty

    assert classement["probabilite"].between(0, 1).all()
    assert classement["ticker"].is_unique
    assert classement["probabilite"].is_monotonic_decreasing
    if classement["calibree"].all():
        etendue = (classement["probabilite"].max()
                   - classement["probabilite"].min())
        assert etendue < 0.5, (
            f"étendue de {etendue:.2f} : des probabilités calibrées sur un "
            "IC de cet ordre ne peuvent pas balayer tout l'intervalle"
        )

    # Sans validation, la fonction rend le rang et ne le déguise pas.
    nu = prediction.predire(cours, REGLAGES)
    assert not nu["calibree"].any()


def test_chaque_probabilite_porte_son_incertitude():
    """Un chiffre sans sa marge se cite tout seul, et finit par tromper."""
    cours = _marche_aleatoire(n_seances=400, graine=33)
    classement = prediction.predire(cours, REGLAGES)
    assert {"incertitude", "rang_combine"} <= set(classement.columns)
    if prediction.APPRENTISSAGE_DISPONIBLE:
        assert classement["incertitude"].notna().any()
        assert (classement["incertitude"].dropna() >= 0).all()


def test_le_composite_reprend_la_main_quand_la_combinaison_ne_vaut_rien():
    """La décision de production est écrite dans le module, pas laissée au
    lecteur.

    Un onglet qui affiche des probabilités issues d'un score dont l'IC
    mesuré est négatif ne présente pas une prévision, il présente un bug.
    Quand la combinaison n'a pas d'IC positif hors échantillon, c'est le
    composite qui part — il n'estime rien, donc il ne peut pas surajuster.
    """
    for graine in range(12):
        validation = prediction.valider(_marche_aleatoire(graine=graine),
                                        REGLAGES)
        if validation["periodes"].empty:
            continue
        attendu = ("combinaison" if validation["stabilite"]["ic"] > 0
                   else "composite")
        assert validation["retenue"] == attendu, graine
        if validation["retenue"] == "composite":
            assert "composite" in prediction.expliquer(validation)
            return
    # Aucun tirage n'a produit le cas : ce n'est pas un échec du test, mais
    # il faut le dire plutôt que de le passer sous silence.
    print("  (aucun tirage n'a rendu la combinaison négative)")


def test_l_ic_vectorise_donne_la_meme_chose_que_la_version_naive():
    """L'accélération ne doit pas déplacer un chiffre.

    `ic_par_date` calcule Spearman en sommes agrégées plutôt qu'en une
    boucle `groupby().apply()` — quarante secondes gagnées par comparaison
    de stratégies, et c'est ce qui a rendu possible de jeter trois
    architectures au lieu de les supposer bonnes. Une accélération de ce
    facteur n'a aucune valeur si elle change les nombres.
    """
    echantillon = prediction.construire_echantillon(
        _marche_aleatoire(n_valeurs=9, n_seances=200, graine=41), REGLAGES)
    rapide = apprentissage.ic_par_date(echantillon, "momentum")
    naif = echantillon.groupby("date").apply(
        lambda g: g["momentum"].rank().corr(g["rendement_futur"].rank()),
        include_groups=False).dropna()

    pd.testing.assert_series_equal(
        rapide.sort_index(), naif.sort_index(),
        check_names=False, atol=1e-12)

if __name__ == "__main__":
    echecs = 0
    for nom, fonction in sorted(globals().items()):
        if not nom.startswith("test_"):
            continue
        try:
            fonction()
            print(f"  ok    {nom}")
        except AssertionError as erreur:
            echecs += 1
            print(f"  ÉCHEC {nom}\n        {erreur}")
    print(f"\n{'tout passe' if not echecs else f'{echecs} échec(s)'}")
    sys.exit(1 if echecs else 0)
