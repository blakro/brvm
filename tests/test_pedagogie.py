"""Les phrases affichées se testent comme les chiffres.

Une phrase fausse trompe aussi sûrement qu'un chiffre faux, et elle passe
plus facilement inaperçue : personne ne relit « 3ᵉ sur 47 » avec méfiance.
Trois choses sont vérifiées ici.

  - Les termes que l'app demande au glossaire y sont. Une clé absente ne se
    verrait qu'au moment où un lecteur ouvre le dépliant, en production, et
    seulement dans l'onglet concerné. Le test lit `streamlit_app.py` et
    confronte chaque appel au dictionnaire.
  - L'attente compte juste et n'invente pas de date quand elle ne peut pas
    en calculer une.
  - Les montants gardent leur ordre de grandeur. Se tromper d'un facteur
    mille sur un volume est l'erreur la plus facile à commettre et la plus
    difficile à voir.

    python tests/test_pedagogie.py
    pytest tests/test_pedagogie.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from brvm import pedagogie  # noqa: E402


def _termes_demandes_par_l_app() -> set[str]:
    """Les clés passées à `_glossaire(...)` dans le fichier de l'app."""
    arbre = ast.parse((RACINE / "streamlit_app.py").read_text(encoding="utf-8"))
    termes: set[str] = set()
    for noeud in ast.walk(arbre):
        if (isinstance(noeud, ast.Call)
                and isinstance(noeud.func, ast.Name)
                and noeud.func.id == "_glossaire"):
            for argument in noeud.args:
                assert isinstance(argument, ast.Constant), (
                    "les termes du glossaire doivent être des littéraux, "
                    "sinon ce test ne peut plus les vérifier"
                )
                termes.add(argument.value)
    return termes


def test_l_app_ne_demande_que_des_termes_definis():
    """La panne serait invisible jusqu'à ce qu'un lecteur ouvre le dépliant."""
    demandes = _termes_demandes_par_l_app()
    assert demandes, "aucun appel à _glossaire trouvé — le test ne teste rien"
    inconnus = demandes - set(pedagogie.GLOSSAIRE)
    assert not inconnus, f"termes absents du glossaire : {sorted(inconnus)}"


def test_le_glossaire_refuse_un_terme_inconnu():
    """Ignorer l'entrée manquante laisserait le lecteur devant le mot qu'il
    ne comprenait justement pas."""
    try:
        pedagogie.glossaire("momentum", "cours_de_bourse_magique")
    except KeyError as erreur:
        assert "cours_de_bourse_magique" in str(erreur)
    else:
        raise AssertionError("un terme inconnu doit lever, pas être sauté")


def test_chaque_definition_tient_en_une_phrase_lisible():
    """Une définition qui déborde n'est plus une définition, c'est un cours.

    La limite est arbitraire ; ce qu'elle protège ne l'est pas : le
    dépliant doit se lire d'un coup d'œil, sans défilement.
    """
    for cle, texte in pedagogie.GLOSSAIRE.items():
        assert 40 < len(texte) <= 260, f"{cle} : {len(texte)} caractères"
        assert texte[0].isupper() and texte.rstrip().endswith("."), cle


def test_l_attente_compte_juste_et_annonce_un_mois():
    """Le cas d'aujourd'hui : une séance en archive, 251 nécessaires."""
    etat = pedagogie.attente(1, 251, "2026-07-27")
    assert etat["manquantes"] == 250
    assert 0 < etat["part"] < 0.01
    # 250 séances ouvrées ≈ 350 jours calendaires.
    assert etat["mois_estime"] == "juillet 2027"
    assert "251 nécessaires" in etat["phrase"]
    assert "juillet 2027" in etat["phrase"]


def test_l_attente_satisfaite_ne_reclame_plus_rien():
    etat = pedagogie.attente(300, 251, "2026-07-27")
    assert etat["manquantes"] == 0 and etat["part"] == 1.0
    assert etat["mois_estime"] is None
    assert "manque" not in etat["phrase"]


def test_aucune_date_n_est_inventee_pour_les_observations():
    """Les observations n'arrivent pas à rythme fixe — une quarantaine par
    séance, mais seulement une fois l'historique assez long. Annoncer un
    mois serait une précision fabriquée."""
    etat = pedagogie.attente(40, 400, "2026-07-27", unite="observation")
    assert etat["mois_estime"] is None
    assert "vers" not in etat["phrase"]
    assert "40 observations sur les 400" in etat["phrase"]


def test_une_date_illisible_ne_fait_pas_tomber_l_attente():
    etat = pedagogie.attente(1, 251, "pas une date")
    assert etat["manquantes"] == 250 and etat["mois_estime"] is None


def test_les_montants_gardent_leur_ordre_de_grandeur():
    assert pedagogie.montant(12_345_678) == "12,3 M FCFA"
    assert pedagogie.montant(2_400_000_000) == "2,4 Md FCFA"
    assert pedagogie.montant(14_229) == "14 229 FCFA"
    assert pedagogie.montant(0) == "0 FCFA"
    assert pedagogie.montant(None) == "—"
    assert pedagogie.montant(float("nan")) == "—"
    assert pedagogie.montant(-5_000_000) == "-5,0 M FCFA"
    # Jamais de séparateur anglais : l'app affiche « 14 229 » ailleurs.
    assert "," not in pedagogie.montant(14_229)


def test_les_pourcentages_se_lisent_en_francais():
    """Une virgule décimale et une espace avant le signe : deux conventions
    dans la même phrase se remarquent, et distraient de ce qu'elle dit."""
    assert pedagogie.pourcentage(0.0213) == "+2,1\u202f%"
    assert pedagogie.pourcentage(-0.0821) == "-8,2\u202f%"
    assert pedagogie.pourcentage(0.30, signe=False) == "30,0\u202f%"
    assert pedagogie.pourcentage(None) == "—"
    assert "." not in pedagogie.pourcentage(0.5761)
    # Espace fine insécable : « 6,3 » et « % » ne doivent pas
    # se retrouver sur deux lignes.
    assert "\u202f" in pedagogie.pourcentage(0.063)


def test_les_dates_se_lisent_en_francais():
    """L'ISO est le bon format pour un fichier, pas pour une phrase."""
    assert pedagogie.jour("2026-07-27") == "27 juillet 2026"
    assert pedagogie.jour(None) == "—"
    # Une date illisible ressort telle quelle plutôt que de faire tomber
    # la page : c'est l'archive qu'il faudra corriger, pas l'affichage.
    assert pedagogie.jour("pas une date") == "pas une date"


def test_l_ordinal_se_lit_en_francais():
    assert pedagogie.ordinal(1) == "1ᵉʳ"
    assert pedagogie.ordinal(3) == "3ᵉ"
    assert pedagogie.ordinal(47) == "47ᵉ"


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
