"""Le balayage doit savoir ne rien trouver.

C'EST TOUTE LA DIFFICULTÉ. Une grille de huit prédicteurs, six segments et
trois horizons fait 144 tests. À 5 % de seuil, sept ressortent
significatifs alors que rien n'existe — c'est la définition du seuil, pas
un défaut. Un outil qui répond toujours « voici le meilleur modèle » est
donc un outil qui se trompe la plupart du temps, et il se trompe en
paraissant précis.

Les tests ci-dessous vérifient les deux propriétés opposées, comme pour
`prediction` :

  - sur des cours SANS structure, le balayage ne retient rien après
    correction. C'est le test qui compte ; sans lui, l'outil fabrique des
    découvertes ;
  - sur des cours où l'on a CACHÉ un signal, il le trouve. Sinon la
    prudence n'est que de l'aveuglement.

    python tests/test_recherche.py
    pytest tests/test_recherche.py
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

from brvm import recherche  # noqa: E402

HORIZONS = (20,)


def _cours(prix: dict[str, np.ndarray]) -> pd.DataFrame:
    """Matrice de prix → table longue, avec un volume toujours suffisant."""
    dates = pd.bdate_range("2016-01-04", periods=len(next(iter(prix.values()))))
    lignes = []
    for ticker, serie in prix.items():
        for date, valeur in zip(dates.strftime("%Y-%m-%d"), serie):
            lignes.append({
                "date": date, "ticker": ticker, "cloture": float(valeur),
                "haut": float(valeur) * 1.01, "bas": float(valeur) * 0.99,
                "volume_titres": 1000.0, "volume_fcfa": float(valeur) * 1000,
            })
    return pd.DataFrame(lignes)


def _marche_aleatoire(n_valeurs=12, n_seances=1500, graine=0):
    rng = np.random.default_rng(graine)
    return _cours({
        f"V{i:02d}": 1000 * np.exp(np.cumsum(rng.normal(0, 0.012, n_seances)))
        for i in range(n_valeurs)
    })


# --- Ne rien trouver quand il n'y a rien ----------------------------------

def test_le_bruit_ne_produit_aucune_decouverte():
    """Le test qui justifie l'existence de la correction.

    Douze marches aléatoires indépendantes : par construction, aucun
    prédicteur ne peut ordonner leurs rendements futurs. Le balayage doit
    rendre une grille pleine et une colonne `retenu` vide.
    """
    table = recherche.balayer(_marche_aleatoire(graine=3), None,
                              horizons=recherche.HORIZONS)
    assert not table.empty
    assert len(table) == len(recherche.PREDICTEURS) * len(recherche.HORIZONS)
    assert not table["retenu"].any(), table[table["retenu"]]


def test_le_meilleur_t_du_bruit_reste_flatteur():
    """Et c'est précisément pourquoi on ne le publie pas.

    Sur du bruit, la meilleure case d'un balayage dépasse régulièrement
    |t| = 2. Publier « le meilleur modèle » sans correction revient à
    publier ce tirage-là.
    """
    meilleurs = []
    for graine in range(6):
        table = recherche.balayer(_marche_aleatoire(graine=graine), None,
                                  horizons=recherche.HORIZONS)
        meilleurs.append(table["|t|"].max())
    # On n'exige pas qu'ils soient grands — seulement qu'aucun ne soit
    # retenu, ce que vérifie le test précédent. Ici on documente qu'ils
    # existent : la moitié au moins dépasse 1,5.
    assert sum(t > 1.5 for t in meilleurs) >= 2, meilleurs


def test_le_rendu_annonce_l_absence_de_decouverte():
    """Le verdict d'ensemble avant le détail, jamais l'inverse : un tableau
    trié par |t| se lit du haut, et sa première ligne paraît être une
    conclusion."""
    table = recherche.balayer(_marche_aleatoire(graine=5), None,
                              horizons=recherche.HORIZONS)
    rendu = recherche.expliquer(table)
    assert "AUCUNE CASE NE SURVIT" in rendu
    assert "loterie" in rendu


# --- Trouver ce qui est là ------------------------------------------------

def test_un_signal_cache_est_retrouve():
    """Sans cela, la prudence ne serait que de l'aveuglement.

    On fabrique un retournement à un mois : le rendement des 20 séances
    suivantes est construit à l'opposé de celui des 20 précédentes. C'est
    exactement ce que `retournement 1 mois` mesure.
    """
    rng = np.random.default_rng(7)
    n, k = 1500, 12
    rendements = rng.normal(0, 0.01, (n, k))
    for t in range(20, n - 20):
        # Une part du rendement futur est l'opposé du passé récent.
        rendements[t] -= 0.35 * rendements[t - 20:t].sum(axis=0) / 20
    prix = 1000 * np.exp(np.cumsum(rendements, axis=0))
    cours = _cours({f"V{i:02d}": prix[:, i] for i in range(k)})

    table = recherche.balayer(cours, None, horizons=(20,))
    retenues = table[table["retenu"]]
    assert not retenues.empty, table.head(4)
    assert "retournement" in retenues.iloc[0]["prédicteur"]
    assert retenues.iloc[0]["ic"] > 0


# --- Les briques ----------------------------------------------------------

def test_benjamini_hochberg_ne_retient_rien_sur_des_p_uniformes():
    """Sous l'hypothèse nulle, les p-valeurs sont uniformes."""
    rng = np.random.default_rng(1)
    p = pd.Series(rng.uniform(size=200))
    assert not recherche.benjamini_hochberg(p).any()


def test_benjamini_hochberg_retient_les_vrais_petits():
    p = pd.Series([1e-6, 1e-5, 1e-4] + list(np.linspace(0.2, 0.99, 197)))
    retenu = recherche.benjamini_hochberg(p)
    assert retenu.iloc[:3].all()
    assert not retenu.iloc[3:].any()


def test_l_incertitude_se_calcule_sur_les_periodes_disjointes():
    """La même correction que dans `prediction` : deux dates voisines
    partagent presque tout leur avenir."""
    rng = np.random.default_rng(2)
    dates = pd.bdate_range("2020-01-01", periods=600).strftime("%Y-%m-%d")
    valeurs = pd.DataFrame(rng.normal(size=(600, 10)), index=dates)
    futur = pd.DataFrame(rng.normal(size=(600, 10)), index=dates)
    mesure = recherche._ic_transversal(valeurs, futur, horizon=60)
    assert mesure["periodes"] == 10
    assert mesure["dates"] == 600
    assert abs(mesure["t"]) < 3


def test_le_rendement_futur_ne_regarde_que_devant():
    """Le contrôle qui empêche le regard en avant : la valeur d'une date
    doit se calculer avec des cours strictement postérieurs."""
    prix = pd.DataFrame({"A": [100.0, 110.0, 121.0, 133.1]})
    futur = recherche._rendement_futur(prix, 1)
    assert abs(futur["A"].iloc[0] - 0.10) < 1e-9
    assert pd.isna(futur["A"].iloc[-1])


def test_les_segments_ecartent_les_secteurs_trop_petits():
    """Un rang de Spearman sur trois points mesure l'arithmétique, pas le
    marché."""
    ref = pd.DataFrame({
        "ticker": ["A", "B", "C", "D", "E", "F", "G"],
        "secteur": ["Banques"] * 5 + ["Télécoms"] * 2,
    })
    trouves = recherche.segments(ref, list("ABCDEFG"))
    assert "Banques" in trouves and "Télécoms" not in trouves
    assert trouves["tout le marché"] == list("ABCDEFG")


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


# --------------------------------------------------------------------
# Le rendement du dividende comme facteur transversal
# --------------------------------------------------------------------

def _marche(n_societes=12, n_seances=800):
    """Un marché jouet. Chaque société suit sa propre pente : des cours
    strictement plats rendraient la corrélation indéfinie, ce qui teste
    autre chose que ce qu'on veut."""
    dates = pd.bdate_range("2020-01-01", periods=n_seances)
    lignes = []
    for i in range(n_societes):
        for j, d in enumerate(dates):
            lignes.append({"date": d.strftime("%Y-%m-%d"),
                           "ticker": f"T{i:02d}",
                           "cloture": 100.0 * (1 + (i - 6) * 0.0002) ** j,
                           "volume_fcfa": 1e6})
    return pd.DataFrame(lignes)


def test_rendement_transversal_ne_compte_que_les_societes_qui_detachent():
    """Le piège de pandas 3 : `.stack()` ne supprime plus les valeurs
    manquantes, et toutes les sociétés de la cote entraient — l'IC se
    calculait alors sur des rendements inexistants, sans rien signaler."""
    cours = _marche(n_societes=12)
    dates = sorted(cours["date"].unique())
    # Dix sociétés sur douze détachent — au-dessus du seuil de saison,
    # mais deux doivent rester hors du calcul.
    div = pd.DataFrame([
        {"ticker": f"T{i:02d}", "date_detachement": dates[10],
         "montant": 5.0 + i, "exercice": dates[0][:4]}
        for i in range(10)
    ])
    t = recherche.rendement_transversal(cours, div)
    assert not t.empty
    assert (t["societes"] == 10).all(), \
        "des sociétés sans dividende ont été comptées"


def test_rendement_transversal_refuse_une_saison_trop_maigre():
    """Sur cinq valeurs, une seule inversion fait changer l'IC de signe."""
    cours = _marche(n_societes=12)
    dates = sorted(cours["date"].unique())
    div = pd.DataFrame([
        {"ticker": f"T{i:02d}", "date_detachement": dates[10],
         "montant": 5.0, "exercice": dates[0][:4]}
        for i in range(recherche.SOCIETES_MINIMUM_SAISON - 1)
    ])
    assert recherche.rendement_transversal(cours, div).empty


def test_rendement_transversal_ne_regarde_que_l_apres():
    """Le rendement est daté de son détachement et ne prédit que la
    suite : le dividende de l'exercice N n'est pas connu en janvier N+1."""
    cours = _marche(n_societes=12, n_seances=400)
    dates = sorted(cours["date"].unique())
    # Un détachement à cinquante séances de la fin : la fenêtre de douze
    # mois ne tient pas, la saison est écartée plutôt qu'amputée.
    div = pd.DataFrame([
        {"ticker": f"T{i:02d}", "date_detachement": dates[-50],
         "montant": 5.0, "exercice": "2021"} for i in range(10)
    ])
    assert recherche.rendement_transversal(cours, div).empty


def test_rendement_transversal_sans_dividende_rend_un_tableau_vide():
    cours = _marche()
    vide = recherche.rendement_transversal(cours, pd.DataFrame())
    assert vide.empty and list(vide.columns) == ["saison", "societes", "ic"]


def test_une_saison_sans_variation_ne_rend_pas_un_ic_indefini():
    """Tous les cours identiques : la corrélation n'a pas de sens. La
    saison est retirée, pas rendue à NaN — un NaN contaminerait la
    moyenne de l'appelant au lieu d'en retirer une observation."""
    dates = pd.bdate_range("2020-01-01", periods=800)
    plat = pd.DataFrame([
        {"date": d.strftime("%Y-%m-%d"), "ticker": f"T{i:02d}",
         "cloture": 100.0, "volume_fcfa": 1e6}
        for i in range(12) for d in dates])
    jours = sorted(plat["date"].unique())
    div = pd.DataFrame([
        {"ticker": f"T{i:02d}", "date_detachement": jours[10],
         "montant": 5.0 + i, "exercice": jours[0][:4]} for i in range(10)])
    t = recherche.rendement_transversal(plat, div)
    assert t.empty or t["ic"].notna().all()
