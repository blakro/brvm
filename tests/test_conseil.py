"""Conseil : ce qu'un module qui dit « achetez » doit prouver avant d'oser.

Les autres modules se trompent au pire d'un chiffre. Celui-ci se traduit en
ordres de bourse, et son erreur la plus probable n'est pas de mal calculer :
c'est de recommander d'agir. Une rotation se facture, un immobilisme non —
donc tout défaut de ce module coûte de l'argent dans un seul sens.

D'où la forme des tests qui suivent. Ils vérifient surtout des REFUS :

  - refus d'arbitrer quand la preuve ne le permet pas ;
  - refus de compter un gain deux fois entre les deux jambes d'un échange ;
  - refus de traiter le rang comme une unité, ce qu'il n'est pas.

Et un seul test de l'inverse — que le module sache dire oui quand le calcul
le justifie — sans quoi un module qui refuse tout passerait pour prudent.

    python tests/test_conseil.py
    pytest tests/test_conseil.py
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

from brvm import conseil  # noqa: E402

# Dix valeurs, frais nuls par défaut : chaque test met les frais qui
# l'intéressent, et aucun n'hérite d'un coût qu'il n'a pas choisi.
REGLAGES = {
    "backtest": {"positions": 3, "frais_pourcent": 0.0, "impact_pourcent": 0.0},
}


def _classement(n: int = 10) -> pd.DataFrame:
    return pd.DataFrame({
        "ticker": [f"T{i:02d}" for i in range(1, n + 1)],
        "nom": [f"Société {i}" for i in range(1, n + 1)],
        "rang": range(1, n + 1),
    })


def _reglages(frais: float = 0.0, positions: int = 3) -> dict:
    return {"backtest": {"positions": positions, "frais_pourcent": frais,
                         "impact_pourcent": 0.0}}


def _mesure(ic: float, erreur: float = 0.0) -> dict:
    return {"ic": ic, "erreur_type": erreur, "t": ic / erreur if erreur else 0.0,
            "dates": 1000, "dates_independantes": 40, "significatif": False}


# --- le rang n'est pas une unité -----------------------------------------

def test_le_score_normalise_ecarte_les_extremes_plus_que_le_milieu():
    """Passer de la 3e à la 1re place ne vaut pas passer de la 20e à la 18e.

    Si le module traitait le rang comme une unité, il sous-estimerait les
    arbitrages qui comptent — ceux qui touchent les extrêmes — et
    surestimerait ceux du milieu, qui sont du bruit. C'est la propriété qui
    rend le gain attendu additionnable.
    """
    z = conseil.scores_normalises(pd.Series(range(1, 41)))
    ecarts = z.diff().abs().dropna()
    # L'écart entre deux rangs voisins est plus grand aux bords qu'au centre.
    assert ecarts.iloc[0] > ecarts.iloc[len(ecarts) // 2] * 2
    assert ecarts.iloc[-1] > ecarts.iloc[len(ecarts) // 2] * 2
    # Monotone décroissant, et symétrique autour de zéro.
    assert z.is_monotonic_decreasing
    assert abs(z.iloc[0] + z.iloc[-1]) < 1e-9
    assert abs(z.mean()) < 1e-9


def test_le_quantile_normal_tient_sans_scipy():
    """L'approximation doit valoir le vrai quantile : c'est elle qui sert si
    scipy manque, et une erreur y déplacerait tous les gains attendus."""
    attendus = {0.5: 0.0, 0.75: 0.6744898, 0.95: 1.6448536,
                0.99: 2.3263479, 0.025: -1.9599640}
    for p, attendu in attendus.items():
        assert abs(conseil._quantile_normal(p) - attendu) < 1e-4, p
    assert np.isnan(conseil._quantile_normal(0.0))
    assert np.isnan(conseil._quantile_normal(1.0))


# --- les refus ------------------------------------------------------------

def test_sans_preuve_aucun_arbitrage_ne_passe():
    """LE test de ce module.

    L'IC mesuré sur l'archive a un intervalle à 95 % qui contient zéro.
    L'estimation prudente est donc négative, et un coût certain ne s'engage
    pas contre un gain qu'on n'a pas établi. Le module doit refuser de faire
    tourner le portefeuille — refuser, pas seulement conseiller mollement.
    """
    mesure = _mesure(0.045, erreur=0.031)          # borne basse négative
    resultat = conseil.conseiller(
        _classement(), detenu=["T09", "T10"], mesure=mesure,
        dispersion_=0.216, reglages=_reglages(frais=1.5), prudence=True)

    assert resultat["ic"] < 0
    assert resultat["ecart_minimal"] == float("inf")
    assert resultat["arbitrages"] == 0
    assert set(resultat["lignes"]["action"]) == {"conserver"}
    rendu = conseil.expliquer(resultat)
    assert "NE RIEN FAIRE" in rendu
    # ET LA RAISON, EN CLAIR. Sans avantage démontré, le lecteur doit savoir
    # que ce n'est pas son courtier qui est en cause : changer d'intermédiaire
    # ne rendrait pas le classement plus juste.
    assert "N'EST PAS UNE QUESTION DE FRAIS" in rendu
    assert "Même sans frais du tout" in rendu


def test_des_frais_assez_hauts_interdisent_tout_arbitrage():
    """Le même classement et la même preuve, seuls les frais changent.

    C'est la propriété que l'utilisateur vient chercher : la réponse dépend
    de SON intermédiaire, et le module doit basculer sur ce seul paramètre.
    """
    mesure = _mesure(0.10)
    commun = dict(classement=_classement(), detenu=["T09", "T10"],
                  mesure=mesure, dispersion_=0.216, prudence=False)

    bon_marche = conseil.conseiller(reglages=_reglages(frais=0.1), **commun)
    cher = conseil.conseiller(reglages=_reglages(frais=5.0), **commun)

    assert bon_marche["arbitrages"] > 0
    assert cher["arbitrages"] == 0
    # Et le seuil exigé monte avec les frais, proportionnellement.
    assert cher["ecart_minimal"] > bon_marche["ecart_minimal"] * 10


def test_un_arbitrage_n_est_accepte_qu_au_dela_de_son_cout():
    """Le seuil doit mordre exactement là où l'arithmétique le place.

    On calcule le gain du meilleur échange possible, puis on fixe les frais
    juste en dessous et juste au-dessus. Un module qui accepterait des deux
    côtés — ou refuserait des deux — aurait un seuil décoratif.
    """
    classement = _classement()
    z = conseil.scores_normalises(classement["rang"])
    ecart = float(z.iloc[0] - z.iloc[-1])          # T01 contre T10
    ic, disp = 0.10, 0.216
    gain = ic * disp * ecart

    for frais, attendu in ((gain / 2 * 0.9, 1), (gain / 2 * 1.1, 0)):
        resultat = conseil.conseiller(
            classement, detenu=["T10"], mesure=_mesure(ic), dispersion_=disp,
            reglages=_reglages(frais=frais * 100), prudence=False)
        assert resultat["arbitrages"] == attendu, (frais, resultat)


def test_les_deux_jambes_d_un_echange_portent_le_meme_net():
    """L'erreur de présentation qui faisait mentir une arithmétique juste.

    Porter la moitié du coût sur chaque jambe affichait des « net -0,65 % »
    sur des lignes que le module venait de recommander. Un arbitrage a deux
    jambes et une seule décision : les deux doivent montrer le net de la
    paire, et l'aller-retour complet.
    """
    resultat = conseil.conseiller(
        _classement(), detenu=["T10"], mesure=_mesure(0.10), dispersion_=0.216,
        reglages=_reglages(frais=0.1), prudence=False)
    assert resultat["arbitrages"] == 1

    jambes = resultat["lignes"][
        resultat["lignes"]["action"].isin(["acheter", "vendre et remplacer"])]
    assert len(jambes) == 2
    assert jambes["net"].nunique() == 1, jambes
    assert jambes["gain_attendu"].nunique() == 1
    assert (jambes["net"] > 0).all()
    # Chaque jambe désigne l'autre : la paire est lisible sans deviner.
    assert set(jambes["paire"]) == set(jambes["ticker"])
    # Et le coût porté est l'aller-retour, pas un seul passage.
    assert abs(jambes["cout"].iloc[0] - 2 * 0.001) < 1e-12


def test_les_arbitrages_s_arretent_au_premier_qui_ne_paie_pas():
    """La boucle apparie la pire ligne détenue à la meilleure candidate.

    L'écart de score ne peut que diminuer ensuite — la sortante suivante est
    meilleure, l'entrante suivante est moins bonne. S'arrêter au premier
    refus n'est donc pas une heuristique, c'est une conséquence. Le test
    vérifie qu'aucun échange accepté n'a un écart plus petit qu'un échange
    refusé.
    """
    resultat = conseil.conseiller(
        _classement(20), detenu=[f"T{i:02d}" for i in range(11, 21)],
        mesure=_mesure(0.08), dispersion_=0.216,
        reglages=_reglages(frais=0.3, positions=10), prudence=False)

    lignes = resultat["lignes"]
    echanges = lignes[lignes["action"] == "vendre et remplacer"]
    conserves = lignes[lignes["action"] == "conserver"]
    if echanges.empty or conserves.empty:
        return
    # Tout ce qui est échangé est plus mal classé que tout ce qui est gardé.
    assert echanges["rang"].min() > conserves["rang"].max(), lignes


# --- le oui, et les cas de bord -----------------------------------------

def test_un_portefeuille_vide_s_achete_sans_aller_retour():
    """Il faut bien commencer, et l'on ne sort de rien : un seul passage de
    frais, pas deux."""
    resultat = conseil.conseiller(
        _classement(), detenu=[], mesure=_mesure(0.10), dispersion_=0.216,
        reglages=_reglages(frais=1.0, positions=3), prudence=False)

    lignes = resultat["lignes"]
    assert set(lignes["action"]) == {"acheter"}
    assert list(lignes["ticker"]) == ["T01", "T02", "T03"]
    assert (lignes["cout"] == 0.01).all(), "l'aller-retour a été facturé"
    # Les gains décroissent avec le rang : le classement est respecté.
    assert lignes["gain_attendu"].is_monotonic_decreasing


def test_constituer_n_est_pas_arbitrer():
    """Le rendu se contredisait, et la cause était un compteur partagé.

    Un achat initial ne remplace rien : il n'a pas d'aller-retour à amortir,
    et il ne se juge donc pas au seuil d'arbitrage. Les compter ensemble
    faisait afficher « aucun arbitrage ne peut se payer » puis « 10
    arbitrages couvrent leurs frais » dans le même rendu.
    """
    resultat = conseil.conseiller(
        _classement(), detenu=[], mesure=_mesure(0.045, erreur=0.031),
        dispersion_=0.216, reglages=_reglages(frais=1.5, positions=3),
        prudence=True)

    assert resultat["arbitrages"] == 0
    assert resultat["constitution"] == 3
    rendu = conseil.expliquer(resultat)
    assert "constituer le portefeuille" in rendu
    assert "NE RIEN FAIRE" not in rendu, "message d'arbitrage sur une création"
    # Et quand la preuve manque, la concentration n'est pas recommandée non
    # plus : le classement est présenté comme un ordre, pas un avantage.
    assert "NE JUSTIFIE DE SE CONCENTRER" in rendu


def test_une_ligne_sortie_de_l_univers_se_vend_sans_arbitrage():
    """Le seul « vendre » qui ne soit pas un échange.

    Une valeur qui n'est plus classée est devenue trop illiquide, ou ne cote
    plus. Le motif n'est pas un gain attendu — il n'y en a pas à calculer —
    c'est qu'on risque de ne plus pouvoir en sortir du tout.
    """
    resultat = conseil.conseiller(
        _classement(), detenu=["T02", "DISPARUE"], mesure=_mesure(0.0),
        dispersion_=0.216, reglages=_reglages(frais=1.0), prudence=True)

    lignes = resultat["lignes"].set_index("ticker")
    assert lignes.loc["DISPARUE", "action"] == "vendre"
    assert "univers" in lignes.loc["DISPARUE", "motif"]
    assert np.isnan(lignes.loc["DISPARUE", "gain_attendu"])
    assert pd.isna(lignes.loc["DISPARUE", "rang"])
    assert "quitté l'univers" in conseil.expliquer(resultat)


def test_un_classement_vide_ne_conseille_rien():
    """Le cas normal tant que l'historique est trop court : on rend vide et
    on dit pourquoi, plutôt qu'un tableau qui aurait l'air d'un conseil."""
    resultat = conseil.conseiller(pd.DataFrame(), detenu=["T01"],
                                  mesure=_mesure(0.05), dispersion_=0.216)
    assert resultat["lignes"].empty
    assert "Aucun conseil" in conseil.expliquer(resultat)


def test_l_ecart_minimal_est_infini_sans_ic_exploitable():
    """Diviser par un IC nul ou négatif n'a pas de sens : le seuil est
    infini, ce qui interdit tout arbitrage — la bonne réponse."""
    assert conseil.ecart_minimal(0.0, 0.2, 0.01) == float("inf")
    assert conseil.ecart_minimal(-0.05, 0.2, 0.01) == float("inf")
    assert conseil.ecart_minimal(0.05, 0.0, 0.01) == float("inf")
    fini = conseil.ecart_minimal(0.05, 0.2, 0.01)
    assert np.isfinite(fini) and fini > 0
    # Proportionnel aux frais, inversement proportionnel à l'IC.
    assert abs(conseil.ecart_minimal(0.05, 0.2, 0.02) - 2 * fini) < 1e-12
    assert abs(conseil.ecart_minimal(0.10, 0.2, 0.01) - fini / 2) < 1e-12


def test_le_rendu_ne_montre_jamais_une_action_sans_son_seuil():
    """Un « achetez » nu se retient et se cite ; le seuil qui le justifie,
    non. Les coller ensemble est le seul moyen d'empêcher le premier de
    voyager seul."""
    resultat = conseil.conseiller(
        _classement(), detenu=["T09", "T10"], mesure=_mesure(0.10),
        dispersion_=0.216, reglages=_reglages(frais=0.2), prudence=False)
    rendu = conseil.expliquer(resultat)
    # LES DEUX NOMBRES QUI DÉCIDENT, DANS LA MÊME UNITÉ, AVANT TOUT LE RESTE.
    # Une version précédente menait par « Écart de score minimal : 3,06 », qui
    # ne veut rien dire pour qui découvre l'application. Ce qui doit se lire
    # en premier est ce que ça coûte et ce que ça rapporte, en pourcents.
    assert "coûte" in rendu and "rapporte" in rendu
    tete = rendu.split("CONSEIL")[0]
    assert "%" in tete, "le rendu ne commence pas par des pourcentages"
    # Le vocabulaire vient après, pour qui veut savoir d'où ça sort — mais il
    # vient : une action sans ce qui la justifie se cite toute seule.
    assert "D'où viennent ces deux nombres" in rendu
    assert "places de classement" in rendu
    # Et les avertissements, qui ne sont pas optionnels.
    assert "pas un conseil d'investissement" in rendu


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
