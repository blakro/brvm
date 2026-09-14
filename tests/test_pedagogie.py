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


def test_chaque_onglet_offre_son_depliant():
    """Un onglet sans glossaire est un onglet qu'un novice ne peut pas lire.

    L'exigence est simple et structurelle : les cinq onglets emploient tous du
    vocabulaire de métier, donc les cinq doivent offrir de quoi le traduire.
    « Données » n'en avait aucun — et c'est celui qui parle le plus de
    séances, d'archive et de référentiel, trois mots que rien ne définissait.

    Le test lit la source de l'application plutôt que son rendu : un onglet
    fermé n'est pas exécuté, donc aucun test de rendu ne peut couvrir les
    cinq d'un coup.
    """
    import re

    source = (RACINE / "streamlit_app.py").read_text(encoding="utf-8")
    lignes = source.splitlines()
    bornes = [(i, int(re.search(r"\[(\d)\]", l).group(1)))
              for i, l in enumerate(lignes)
              if re.match(r"\s*with onglets\[\d\]:", l)]
    assert bornes, "aucun bloc « with onglets[i] » trouvé : le test ne teste rien"

    sans = set()
    couverts = set()
    for rang, (debut, onglet) in enumerate(bornes):
        fin = bornes[rang + 1][0] if rang + 1 < len(bornes) else len(lignes)
        corps = "\n".join(lignes[debut:fin])
        if "_glossaire(" in corps:
            couverts.add(onglet)
        else:
            sans.add(onglet)
    # Un onglet peut être servi par plusieurs blocs — « Classement » en a
    # trois : il suffit qu'un seul porte le dépliant.
    manquants = sorted(sans - couverts)
    assert not manquants, f"onglets sans glossaire : {manquants}"
    assert couverts == {0, 1, 2, 3, 4}, sorted(couverts)


def test_le_glossaire_refuse_un_terme_inconnu():
    """Ignorer l'entrée manquante laisserait le lecteur devant le mot qu'il
    ne comprenait justement pas."""
    try:
        pedagogie.glossaire("momentum", "cours_de_bourse_magique")
    except KeyError as erreur:
        assert "cours_de_bourse_magique" in str(erreur)
    else:
        raise AssertionError("un terme inconnu doit lever, pas être sauté")


# Les mots qu'une définition ne doit pas employer. Ce ne sont pas des mots
# interdits dans l'application — ils y sont partout, et c'est leur place. Mais
# une DÉFINITION qui les emploie renvoie le lecteur à un deuxième glossaire,
# et un lecteur qu'on renvoie deux fois abandonne.
#
# La liste est volontairement courte et concrète : elle contient ce qui a
# réellement été écrit dans une définition puis retiré, pas tout le
# vocabulaire imaginable.
JARGON = (
    "IC", "IR", "Spearman", "quantile", "z-score", "écart-type",
    "corrélation", "transversal", "surajust", "hors échantillon",
    "entraînement", "glissant", "logistique", "régression", "composite",
    "intervalle de confiance", "erreur-type", "p-valeur", "Benjamini",
    "Grinold", "Ornstein", "point-in-time",
)


def test_aucune_definition_n_emploie_le_jargon_qu_elle_doit_remplacer():
    """LA RÈGLE QUE L'EN-TÊTE DU MODULE ÉNONÇAIT SANS QUE RIEN NE LA VÉRIFIE.

    « Une définition qui appelle un deuxième glossaire n'en est pas une »,
    dit le module depuis le début. Trois définitions ajoutées récemment la
    violaient — celle de l'IR renvoyait à l'IC, celle du calibrage parlait
    d'entraînement — et rien ne l'a signalé.

    Une définition est le bout de la chaîne : c'est là que le lecteur doit
    pouvoir s'arrêter.
    """
    import re

    fautes = []
    for cle, texte in pedagogie.GLOSSAIRE.items():
        for mot in JARGON:
            # La clé peut apparaître dans sa propre définition : « les frais
            # de transaction » définissant `frais` est correct.
            if mot.lower() in cle.lower():
                continue
            # LIMITES DE MOTS, ET CASSE EXACTE POUR LES SIGLES. Une première
            # version cherchait la sous-chaîne sans casse : « IC » se
            # trouvait dans « difficile », « IR » dans « dire » et dans
            # « aller-retour », et le test accusait dix-neuf définitions
            # irréprochables. Un test qui crie partout ne se lit plus.
            motif = rf"\b{re.escape(mot)}\b"
            drapeaux = 0 if mot.isupper() else re.IGNORECASE
            if re.search(motif, texte, drapeaux):
                fautes.append(f"{cle} emploie « {mot} »")
    assert not fautes, "définitions qui renvoient à un autre jargon :\n  " \
        + "\n  ".join(fautes)


def test_chaque_definition_se_lit_sans_formule():
    """Pas de symbole mathématique dans une définition.

    Une formule est exacte et illisible ; elle a sa place dans les
    docstrings des modules de calcul, jamais dans le dépliant que lit
    quelqu'un qui découvre le mot.
    """
    for cle, texte in pedagogie.GLOSSAIRE.items():
        for symbole in ("×", "÷", "√", "²", "Σ", "±", "≈", "=", "/ ("):
            assert symbole not in texte, f"{cle} contient « {symbole} »"


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
