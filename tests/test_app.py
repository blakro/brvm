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
2. chacun des cinq onglets se rend, et va au bout de son contenu ;
3. la séance lue en direct TIENT à travers les relances ;
4. l'onglet ouvert et la société affichée tiennent aussi, y compris quand
   la session est vidée et que seule l'URL subsiste ;
5. l'échéance choisie pour la prévision, le mois ou le trimestre, tient
   d'un onglet à l'autre ;
6. une échéance dont l'avance n'est pas démontrée est signalée sur la
   fiche d'une action comme dans l'onglet Prédictions.

Le réseau n'est jamais touché : `brvm_org.lire_cote` est remplacé par une
séance fabriquée, comme le reste de la suite travaille sur les captures de
`tests/donnees`. Un test qui échouerait parce que brvm.org est injoignable
ne dirait rien du code qu'il prétend vérifier.

    pytest tests/test_app.py
"""

from __future__ import annotations

import os
import re
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
    ("predictions", "🔮 Prédictions"),
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


def _textes(at: AppTest) -> str:
    return " ".join(bloc.value for bloc in at.markdown)


def test_la_fiche_d_une_action_va_au_bout(lanceur):
    """La fiche, le simulateur et la prévision sont rendus l'un après
    l'autre : une erreur dans le premier emporterait les suivants sans
    que l'onglet entier lève forcément."""
    at = _app(lanceur)
    at.query_params["onglet"] = "action"
    at.query_params["valeur"] = "SNTS"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    textes = _textes(at)
    for attendu in ("Facile à revendre ?", "Pire chute (1 an)",
                    "Prix pour ne rien perdre", "Et dans les mois qui viennent ?",
                    "Le mois qui vient · 20 séances",
                    "Le trimestre qui vient · 60 séances"):
        assert attendu in textes, f"« {attendu} » absent de la fiche"
    assert not re.search(r"\bnan\b", textes, re.IGNORECASE), \
        "une valeur manquante s'affiche « nan »"


def test_aucune_valeur_manquante_ne_s_affiche_nan_sur_l_accueil(lanceur):
    at = _app(lanceur).run()
    assert not re.search(r"\bnan\b", _textes(at), re.IGNORECASE)


@pytest.mark.parametrize("horizon, echeance, cadence", [
    (None, "le mois qui vient (20 séances)", "chaque mois"),
    (60, "le trimestre qui vient (60 séances)", "chaque trimestre"),
])
def test_l_onglet_predictions_montre_le_bilan_et_les_frais(
        lanceur, horizon, echeance, cadence):
    """La prévision ne se montre jamais sans son bilan passé ni sans le
    coût des frais : c'est ce qui la garde réaliste.

    Et cela vaut pour CHAQUE échéance. Le bilan, l'avance et les frais
    d'un mois ne disent rien de ceux d'un trimestre : une page qui
    changerait la météo sans changer le reste afficherait la prévision de
    l'une sous la garantie de l'autre.
    """
    at = _app(lanceur)
    at.query_params["onglet"] = "predictions"
    at.run()
    if horizon is not None:
        at.segmented_control(key="horizon").set_value(horizon).run()
    assert not at.exception, [str(e) for e in at.exception]
    textes = _textes(at)
    for attendu in ("Bonnes réponses", "pile ou face", "Le piège des frais",
                    "Plutôt favorable", "Plutôt défavorable",
                    f"La météo du devin pour {echeance}",
                    f"en suivant ses favorites {cadence}"):
        assert attendu in textes, f"« {attendu} » absent de l'onglet Prédictions"
    assert "semaine prochaine" not in textes
    colonnes = [set(d.value.columns) for d in at.dataframe]
    assert any({"ticker", "probabilite", "incertitude"} <= c for c in colonnes), \
        "le détail des probabilités, avec leur incertitude, est absent"


def test_l_echeance_choisie_tient_d_un_onglet_a_l_autre(lanceur):
    """Le corps d'un onglet fermé ne s'exécute pas : sans `persist_state`,
    le choix du trimestre retombait sur le mois au premier détour par un
    autre onglet."""
    at = _app(lanceur)
    at.query_params["onglet"] = "predictions"
    at.run()
    at.segmented_control(key="horizon").set_value(60).run()

    at.session_state["onglet"] = "🎓 Comprendre"
    at.run()
    at.session_state["onglet"] = "🔮 Prédictions"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.segmented_control(key="horizon").value == 60
    assert "le trimestre qui vient (60 séances)" in _textes(at)


def test_la_fiche_et_l_onglet_predictions_font_la_meme_reserve(lanceur):
    """Une échéance dont l'avance n'est pas démontrée l'est sur les deux
    onglets, ou sur aucun.

    Le constat dépend des données — sur l'archive d'octobre 2026, le
    trimestre n'est pas démontré et le mois l'est —, le test ne fige donc
    pas lequel : il exige que la fiche dise ce que dit l'onglet. Sans
    quoi une carte ☀️ au trimestre se lirait, dans la fiche, comme un avis
    aussi solide que celui du mois.
    """
    at = _app(lanceur)
    at.query_params["onglet"] = "action"
    at.query_params["valeur"] = "SNTS"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    legendes = " ".join(c.value for c in at.caption)
    trouve = re.search(r"À l'échéance d'(.+?), même l'avance", legendes)
    dans_la_fiche = trouve.group(1) if trouve else ""

    at.session_state["onglet"] = "🔮 Prédictions"
    at.run()
    for horizon, duree in ((20, "un mois"), (60, "un trimestre")):
        at.segmented_control(key="horizon").set_value(horizon).run()
        assert not at.exception, [str(e) for e in at.exception]
        alertes = " ".join(w.value for w in at.warning)
        dans_l_onglet = (f"À l'échéance d'{duree}, l'avance des favorites "
                         "n'est pas démontrée" in alertes)
        assert dans_l_onglet == (duree in dans_la_fiche), (
            f"{duree} : l'onglet Prédictions "
            f"{'émet' if dans_l_onglet else 'n’émet pas'} la réserve, la "
            f"fiche {'non' if dans_l_onglet else 'si'}")


def test_le_glossaire_se_filtre(lanceur):
    """Chercher un mot ne garde que les définitions qui le contiennent."""
    at = _app(lanceur)
    at.query_params["onglet"] = "comprendre"
    at.run()
    at.text_input(key="glossaire").set_value("dividende").run()
    assert not at.exception, [str(e) for e in at.exception]
    textes = _textes(at)
    assert "Dividende</h4>" in textes
    assert "Volatilité</h4>" not in textes
