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

from brvm import prediction  # noqa: E402

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


def _cours(trajectoires: dict[str, list[float]]):
    lignes = []
    for ticker, prix in trajectoires.items():
        for rang, valeur in enumerate(prix):
            lignes.append({
                "date": f"{2020 + rang // 336:04d}-"
                        f"{1 + (rang % 336) // 28:02d}-{1 + rang % 28:02d}",
                "ticker": ticker, "cloture": float(valeur),
                "volume_titres": 100.0, "volume_fcfa": 5_000_000.0,
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
    assert "IC du modèle" in rendu and "IC du score composite" in rendu
    assert "écart" in rendu


class _sans_apprentissage:
    """Simule l'absence de scikit-learn sans avoir à la désinstaller."""

    def __enter__(self):
        self.avant = prediction.APPRENTISSAGE_DISPONIBLE
        prediction.APPRENTISSAGE_DISPONIBLE = False

    def __exit__(self, *_):
        prediction.APPRENTISSAGE_DISPONIBLE = self.avant


def test_sans_scikit_learn_le_composite_repond_encore():
    """L'apprentissage est la seule chose que l'absence doit coûter.

    Le score composite ne s'apprend pas : ses poids sont écrits dans la
    configuration. Il reste donc calculable, et c'est celui-là même qui part
    en production quand le modèle ne le devance pas.
    """
    cours = _marche_aleatoire(graine=7)
    # Les pondérations sont ce qui fait exister le composite : sans elles le
    # score est constant, et l'IC d'une constante n'est pas défini.
    reglages = {**REGLAGES,
                "ponderations": {"momentum": 0.5, "tendance": 0.3,
                                 "volatilite": -0.2}}

    with _sans_apprentissage():
        validation = prediction.valider(cours, reglages)
        rendu = prediction.expliquer(validation)
        vide = prediction.predire(cours, reglages)

        try:
            prediction._modele()
        except prediction.ApprentissageIndisponible:
            pass
        else:
            raise AssertionError("_modele doit refuser, pas renvoyer un objet")

    assert "scikit-learn" in validation["motif"]
    assert np.isfinite(validation["ic_composite"])
    assert "scikit-learn" in rendu and "composite" in rendu
    # Vide, et non une colonne de probabilités fabriquée : un rang composite
    # n'est pas une probabilité, et le présenter comme telle serait pire que
    # de ne rien présenter.
    assert vide.empty and list(vide.columns) == ["ticker", "probabilite"]


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
