"""Exogènes et rendement du dividende, sur données fabriquées.

Deux mécaniques y sont vérifiées, et chacune protège d'une erreur qui ne se
verrait pas autrement :

  - une série exogène versée telle quelle dans un modèle de CLASSEMENT
    n'apporte rien, puisqu'elle vaut la même chose pour toutes les valeurs
    d'une même séance. Le test le démontre plutôt que de l'affirmer, puis
    montre que l'interaction avec le secteur, elle, porte le signal ;
  - un retour à la moyenne trop lent pour l'horizon de détention n'est pas
    un signal. La demi-vie est estimée et sert de refus.

    python tests/test_exogene.py
    pytest tests/test_exogene.py
"""

from __future__ import annotations

import os
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

from brvm import dividende, exogene  # noqa: E402

SECTEUR_A = "Consommation de Base"
SECTEUR_B = "Services Financiers"

REGLAGES = {
    "exogenes": {
        "fenetre_variation": 10, "retard": 5,
        "correspondance": {"caoutchouc_tsr20": SECTEUR_A},
    },
    "prediction": {"horizon": 20},
}


def _dates(n):
    return [f"{2020 + i // 336:04d}-{1 + (i % 336) // 28:02d}-{1 + i % 28:02d}"
            for i in range(n)]


def _referentiel():
    return pd.DataFrame(
        [{"ticker": f"A{i}", "nom": f"A{i}", "secteur": SECTEUR_A} for i in range(4)]
        + [{"ticker": f"B{i}", "nom": f"B{i}", "secteur": SECTEUR_B} for i in range(4)]
    )


def test_une_serie_exogene_seule_ne_distingue_aucune_valeur():
    """La raison d'être du module, démontrée plutôt qu'affirmée.

    Le cours du caoutchouc à une date donnée est le même pour les 47
    sociétés : sa variance À L'INTÉRIEUR d'une séance est nulle. Versé tel
    quel dans un modèle de classement, il ne peut donc pas départager deux
    valeurs — l'IC ne bougerait pas et on en conclurait à tort que les
    commodités n'expliquent rien.
    """
    dates = _dates(40)
    brut = pd.DataFrame({"date": dates, "serie": "caoutchouc_tsr20",
                         "valeur": np.linspace(100, 200, len(dates))})
    alignees = exogene.aligner(brut, dates)

    # Une seule valeur par date : rien à comparer entre deux tickers.
    assert alignees.shape[1] == 1
    for date in dates[:5]:
        assert alignees.loc[date].nunique() <= 1


def test_l_interaction_avec_le_secteur_cree_la_variance_utile():
    """Croisée avec l'appartenance sectorielle, la même série discrimine.

    La colonne vaut la variation pour les valeurs du secteur visé et zéro
    pour les autres : elle varie donc bien à l'intérieur d'une séance,
    ce qui est la condition pour qu'un modèle de classement l'exploite.
    """
    dates = _dates(40)
    brut = pd.DataFrame({"date": dates, "serie": "caoutchouc_tsr20",
                         "valeur": np.linspace(100, 200, len(dates))})
    croisees = exogene.traits(brut, dates, _referentiel(), REGLAGES)

    assert not croisees.empty
    assert "exo_caoutchouc_tsr20" in croisees.columns

    tardif = croisees[croisees["date"] == dates[-1]].set_index("ticker")
    valeurs_a = tardif.loc[["A0", "A1", "A2", "A3"], "exo_caoutchouc_tsr20"]
    valeurs_b = tardif.loc[["B0", "B1", "B2", "B3"], "exo_caoutchouc_tsr20"]

    assert (valeurs_a != 0).all(), "le secteur visé doit porter la variation"
    assert (valeurs_b == 0).all(), "les autres secteurs doivent rester à zéro"
    assert tardif["exo_caoutchouc_tsr20"].nunique() > 1


def test_le_report_ne_regarde_pas_la_publication_suivante():
    """Report de la dernière valeur connue, jamais d'interpolation.

    Interpoler entre deux publications mensuelles fabriquerait des valeurs
    intermédiaires que personne n'observait — et qui dépendraient de la
    publication SUIVANTE, donc du futur. La fuite serait invisible.
    """
    dates = _dates(10)
    brut = pd.DataFrame({"date": [dates[0], dates[5]],
                         "serie": "taux_bceao", "valeur": [3.0, 5.0]})
    alignees = exogene.aligner(brut, dates)

    entre_deux = alignees.loc[dates[1]:dates[4], "taux_bceao"]
    assert (entre_deux == 3.0).all(), (
        f"valeurs {list(entre_deux)} : une interpolation a anticipé la "
        "publication du {dates[5]}"
    )
    assert alignees.loc[dates[5], "taux_bceao"] == 5.0


def test_le_retard_empeche_d_utiliser_le_jour_meme():
    """À la date t, seule la variation arrêtée en t-retard est visible."""
    dates = _dates(30)
    valeurs = np.ones(len(dates)) * 100.0
    valeurs[20:] = 200.0  # saut net à la 21e séance
    brut = pd.DataFrame({"date": dates, "serie": "caoutchouc_tsr20",
                         "valeur": valeurs})

    alignees = exogene.aligner(brut, dates)
    variation = exogene.variations(alignees, fenetre=5, retard=5)

    # Le saut a lieu en position 20 ; avec 5 de fenêtre et 5 de retard il ne
    # peut pas apparaître avant la position 25.
    avant = variation["caoutchouc_tsr20"].iloc[:25]
    assert (avant.fillna(0) == 0).all(), "le saut a été vu trop tôt"
    assert variation["caoutchouc_tsr20"].iloc[25:].max() > 0.5


def test_couverture_signale_ce_qui_manque():
    """Une série trop courte doit se voir avant qu'on s'étonne des vides."""
    dates = _dates(6)
    brut = pd.DataFrame({"date": dates, "serie": "sucre", "valeur": range(6)})
    resume = exogene.couverture(brut).set_index("serie")
    assert resume.loc["sucre", "points"] == 6
    assert resume.loc["sucre", "debut"] == dates[0]
    assert exogene.couverture(pd.DataFrame()).empty


# --- Rendement du dividende ----------------------------------------------


def test_ou_retrouve_les_parametres_qu_on_lui_a_donnes():
    """Simulation d'un Ornstein-Uhlenbeck de paramètres connus.

    C'est la seule façon de vérifier un estimateur : sur données réelles,
    personne ne connaît la bonne réponse.
    """
    rng = np.random.default_rng(0)
    theta_vrai, mu_vrai, sigma = 0.05, 0.06, 0.002
    y = [0.10]
    for _ in range(2000):
        y.append(y[-1] + theta_vrai * (mu_vrai - y[-1]) + rng.normal(0, sigma))

    mu, theta = dividende.ajuster_ou(pd.Series(y))
    assert abs(mu - mu_vrai) < 0.01, f"équilibre {mu:.4f}, attendu {mu_vrai}"
    assert abs(theta - theta_vrai) < 0.02, f"vitesse {theta:.4f}"

    attendue = np.log(2) / theta_vrai
    assert abs(dividende.demi_vie(theta) - attendue) < 5


def test_une_serie_sans_retour_a_la_moyenne_est_refusee():
    """Une marche aléatoire n'a pas de moyenne où revenir.

    L'estimateur doit rendre NaN plutôt qu'un paramètre absurde : ajusté de
    force, il produirait un équilibre et une demi-vie qui n'existent pas, et
    le signal en découlerait tout aussi faux.
    """
    rng = np.random.default_rng(1)
    marche = pd.Series(np.cumsum(rng.normal(0, 0.01, 500)) + 0.05)
    mu, theta = dividende.ajuster_ou(marche)
    assert np.isnan(theta) or theta <= 0 or dividende.demi_vie(theta) > 200


def test_le_taux_de_faux_positifs_reste_celui_d_un_test_a_5_pour_cent():
    """Le contrôle qui a révélé le bug, gardé comme non-régression.

    Les moindres carrés appliqués à une marche aléatoire rendent presque
    toujours un coefficient légèrement négatif — le biais de Dickey-Fuller.
    Sans test de significativité, ce code « détectait » un retour à la
    moyenne sur 162 marches aléatoires sur 200, et aurait donc inventé un
    équilibre et une demi-vie à des séries qui n'en ont pas.

    Mesurer le taux plutôt que vérifier un cas isolé : un seul tirage peut
    passer par chance, une proportion sur deux cents ne le peut pas.
    """
    faux = 0
    for graine in range(200):
        rng = np.random.default_rng(graine)
        marche = pd.Series(np.cumsum(rng.normal(0, 0.01, 500)) + 0.05)
        _, theta = dividende.ajuster_ou(marche)
        if np.isfinite(theta) and dividende.demi_vie(theta) <= 200:
            faux += 1

    assert faux <= 20, (
        f"{faux}/200 marches aléatoires déclarées à retour à la moyenne — "
        "le test de significativité ne joue plus"
    )


def test_un_retour_trop_lent_n_est_pas_exploitable():
    """Le garde-fou qui distingue le modèle d'un simple « ça a baissé ».

    Un rendement qui met des années à revenir à sa moyenne ne dit rien pour
    un horizon de trois mois : le retour aura lieu après qu'on aura vendu.
    """
    dates = _dates(400)
    rng = np.random.default_rng(2)
    # θ minuscule : demi-vie de plusieurs centaines de séances.
    y = [0.10]
    for _ in range(len(dates) - 1):
        y.append(y[-1] + 0.001 * (0.05 - y[-1]) + rng.normal(0, 0.0005))

    prix = pd.DataFrame({
        "date": dates, "ticker": "LENT",
        "cloture": [100.0 / v * 0.05 for v in y],
        "volume_titres": 100.0, "volume_fcfa": 1e6,
    })
    divs = pd.DataFrame([{"ticker": "LENT", "date_detachement": dates[0],
                          "montant": 5.0, "exercice": "2020"}])

    tableau = dividende.signal(prix, divs, reglages={"prediction": {"horizon": 60}})
    if not tableau.empty and np.isfinite(tableau.iloc[0]["demi_vie"]):
        assert not tableau.iloc[0]["exploitable"], (
            f"demi-vie {tableau.iloc[0]['demi_vie']:.0f} séances déclarée "
            "exploitable sur un horizon de 60"
        )


def test_sans_dividendes_le_module_se_tait():
    """Aucun dividende en base est l'état normal aujourd'hui : le module
    doit rendre vide et le dire, pas lever."""
    dates = _dates(30)
    prix = pd.DataFrame({"date": dates, "ticker": "AAAA", "cloture": 100.0,
                         "volume_titres": 10.0, "volume_fcfa": 1000.0})
    tableau = dividende.signal(prix, pd.DataFrame(columns=[
        "ticker", "date_detachement", "montant", "exercice"]))
    assert tableau.empty
    assert "importer-dividendes" in dividende.expliquer(tableau)


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
