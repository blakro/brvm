"""L'app : ce qu'elle doit RETENIR d'une relance à l'autre.

POURQUOI CE FICHIER EXISTE. Streamlit rejoue tout le script à chaque clic,
et cette seule propriété produit une famille de défauts que la suite ne
voyait pas : les modules de `src/brvm` sont testés isolément, ils rendent
tous la bonne réponse, et l'app affiche pourtant la mauvaise chose parce
qu'une variable est retombée à sa valeur d'origine entre deux passages.

C'est arrivé en vrai, et c'est ce qui a motivé ce fichier. La cote relue
par le bouton « Actualiser » n'était versée qu'au passage où l'on
cliquait ; au suivant, l'écran revenait à la dernière séance de l'archive.
Le défaut a atteint la production et c'est l'utilisateur qui l'a vu.

Ce qui est testé ici est donc l'ÉTAT, pas le calcul :

1. l'app se rend sans lever, ce qui n'est pas acquis — un `st.tabs` mal
   employé lève au démarrage et emporte toute la page ;
2. chacun des quatre onglets se rend ;
3. la séance lue en direct TIENT à travers les relances ;
4. l'onglet ouvert et la société affichée tiennent aussi, y compris quand
   la session est vidée et que seule l'URL subsiste.

Le réseau n'est jamais touché : `brvm_org.lire_cote` est remplacé par une
séance fabriquée, comme le reste de la suite travaille sur les captures de
`tests/donnees`. Un test qui échouerait parce que brvm.org est injoignable
ne dirait rien du code qu'il prétend vérifier.

    pytest tests/test_app.py
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

import pytest  # noqa: E402

# L'interface est un extra : `pip install -e ".[web]"`. Son absence ne doit
# pas faire échouer la suite du paquet, qui ne dépend pas d'elle.
streamlit = pytest.importorskip("streamlit", reason="extra « web » absent")
pytest.importorskip("altair", reason="extra « web » absent")

from streamlit.testing.v1 import AppTest  # noqa: E402

from brvm import pedagogie  # noqa: E402

APP = RACINE / "streamlit_app.py"
SEANCE_SIMULEE = "2026-12-31"
# L'app n'écrit jamais une date ISO à l'écran : elle passe par
# `pedagogie.jour`. Chercher « 2026-12-31 » dans le rendu ne trouverait
# rien et ferait passer le test pour de mauvaises raisons.
SEANCE_AFFICHEE = pedagogie.jour(SEANCE_SIMULEE)

# Le premier rendu lit 6,7 Mo d'archive et trace plusieurs graphiques ; sur
# un runner partagé, trois secondes ne suffisent pas.
DELAI = 120


# Le lanceur est écrit sur disque plutôt que passé en fonction :
# `AppTest.from_function` réexécute la source dans un espace de noms neuf,
# où rien de ce que le test avait préparé n'existe plus. Il ne fait
# qu'exécuter l'app ; c'est la fixture qui écarte le réseau.
_LANCEUR = f'''
import sys
sys.path.insert(0, {str(RACINE / "src")!r})
_source = open({str(APP)!r}, encoding="utf-8").read()
exec(compile(_source, {str(APP)!r}, "exec"))
'''


@pytest.fixture
def lanceur(tmp_path, monkeypatch) -> str:
    """L'app prête à tourner, brvm.org remplacé par une séance fabriquée.

    LE REMPLACEMENT PASSE PAR `monkeypatch`, ET C'EST LA LEÇON D'UN DÉGÂT.
    Il vivait d'abord dans le lanceur — or `AppTest` exécute le script DANS
    LE PROCESSUS DU TEST : `brvm_org.lire_cote` restait remplacé pour toute
    la suite, et quatre tests de `test_brvm_org.py` tombaient plus loin,
    accusant un code intact. `monkeypatch` défait la substitution à la fin
    de chaque cas.
    """
    from brvm import db
    from brvm.ingestion import brvm_org

    socle = db.charger_archive("cours")
    veille = socle[socle["date"] == socle["date"].max()].copy()

    def cote_simulee():
        seance = veille.copy()
        seance["date"] = SEANCE_SIMULEE
        seance.attrs["heure_mise_a_jour"] = "15:30"
        return seance

    monkeypatch.setattr(brvm_org, "lire_cote", cote_simulee)

    chemin = tmp_path / "lanceur.py"
    chemin.write_text(_LANCEUR, encoding="utf-8")
    return str(chemin)


def _app(lanceur: str) -> AppTest:
    """L'app, avec brvm.org remplacé par une séance fabriquée.

    La séance porte une date volontairement lointaine : elle ne peut pas
    coïncider avec la dernière de l'archive, quelle que soit la date à
    laquelle la suite tourne. Sans quoi le test passerait pour de mauvaises
    raisons le jour où l'archive rattraperait le calendrier.
    """
    return AppTest.from_file(lanceur, default_timeout=DELAI)


def _seance_affichee(at: AppTest) -> str:
    """La date que porte la carte « Séance » de l'onglet Aujourd'hui."""
    for bloc in at.markdown:
        if 'class="label">Séance</div>' in bloc.value:
            return bloc.value
    return ""


def test_l_app_se_rend_sans_lever(lanceur):
    """Une erreur au démarrage emporte la page entière, pas un onglet."""
    at = _app(lanceur).run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["onglet"] == "🏠 Aujourd'hui"


@pytest.mark.parametrize("onglet, libelle", [
    ("action", "🔎 Une action"),
    ("dividendes", "💰 Dividendes"),
    ("comprendre", "🎓 Comprendre"),
])
def test_chaque_onglet_se_rend_sans_lever(lanceur, onglet, libelle):
    """Le corps des onglets fermés n'est pas exécuté : un rendu par défaut
    ne prouve rien des trois autres."""
    at = _app(lanceur)
    at.query_params["onglet"] = onglet
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["onglet"] == libelle


def test_la_seance_lue_en_direct_survit_aux_relances(lanceur):
    """LE DÉFAUT QUI A ATTEINT LA PRODUCTION.

    Après « Actualiser », l'app doit afficher la séance publiée sur le
    site, et continuer de l'afficher — y compris après un changement
    d'onglet, qui relance le script.
    """
    at = _app(lanceur).run()
    assert SEANCE_AFFICHEE not in _seance_affichee(at), (
        "l'archive ne devrait pas déjà porter la séance simulée"
    )

    at.button[0].click().run()
    assert SEANCE_AFFICHEE in _seance_affichee(at), (
        "« Actualiser » n'a pas affiché la séance lue en direct"
    )

    at.session_state["onglet"] = "🎓 Comprendre"
    at.run()
    at.session_state["onglet"] = "🏠 Aujourd'hui"
    at.run()
    assert SEANCE_AFFICHEE in _seance_affichee(at), (
        "la séance a été reperdue en changeant d'onglet"
    )


def test_l_onglet_ouvert_tient_d_une_relance_a_l_autre(lanceur):
    """Sans cela, toute interaction ramenait au premier onglet."""
    at = _app(lanceur).run()
    at.session_state["onglet"] = "💰 Dividendes"
    at.run()

    at.button[0].click().run()          # 🔄 Actualiser
    assert at.session_state["onglet"] == "💰 Dividendes"


def test_l_onglet_et_la_societe_se_relisent_dans_l_URL(lanceur):
    """Un rechargement de page vide la session : seule l'URL subsiste.

    C'est aussi ce qui rend une fiche partageable par son lien.
    """
    at = _app(lanceur)
    at.query_params["onglet"] = "action"
    at.query_params["valeur"] = "SNTS"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["onglet"] == "🔎 Une action"
    assert at.session_state["valeur"] == "SNTS"


def test_un_symbole_inconnu_dans_l_URL_ne_fait_pas_tomber_l_app(lanceur):
    """Un lien peut désigner une valeur radiée, ou mal recopiée."""
    at = _app(lanceur)
    at.query_params["onglet"] = "action"
    at.query_params["valeur"] = "CE_SYMBOLE_N_EXISTE_PAS"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["valeur"] != "CE_SYMBOLE_N_EXISTE_PAS"
