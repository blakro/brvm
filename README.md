# brvm

Ingestion de la cote de la [Bourse Régionale des Valeurs Mobilières](https://www.brvm.org)
— les 47 sociétés cotées de l'UEMOA — dans une base SQLite locale.

## Installation

```bash
pip install -e ".[dev]"
```

Python 3.11 ou plus (le module lit sa configuration avec `tomllib`).

## Utilisation

```bash
python -m brvm verifier        # diagnostic des sélecteurs, sans rien écrire
python -m brvm ingerer         # enregistre la séance publiée
python -m brvm referentiel     # met à jour ticker / nom / secteur
python -m brvm etat            # ce que contient la base
```

`verifier` accepte un fichier, pour travailler sans réseau :

```bash
curl -sL https://www.brvm.org/fr/cours-actions/0 -o cote.html
python -m brvm verifier cote.html
```

C'est la commande à lancer en premier quand l'ingestion échoue : elle
imprime les colonnes reconnues et leur intitulé d'origine, ce qui dit
exactement quoi corriger dans `ALIAS_COLONNES` ou `SELECTEURS`.

## Configuration

Tout a un défaut utilisable ; `config.toml` à la racine est facultatif.
Voir `config.exemple.toml`. Deux variables d'environnement priment :

| Variable | Effet |
|---|---|
| `BRVM_CONFIG` | chemin d'un autre fichier de configuration |
| `BRVM_BASE` | chemin de la base SQLite |

## Ce que le code sait de brvm.org

Le site a plusieurs comportements qui produisent des données fausses mais
plausibles. Ils sont documentés dans `src/brvm/ingestion/brvm_org.py` et
verrouillés par des tests ; les résumer ici évite de les redécouvrir.

- **La cote n'est pas paginée.** `/fr/cours-actions/{n}` n'est pas un
  numéro de page mais un **identifiant de secteur** (194 à 200). Les 47
  sociétés tiennent sur `/0`.
- **Un identifiant inconnu ne renvoie pas 404** : le site sert la cote
  entière. Une vue sectorielle mal ciblée rangerait donc les 47 sociétés
  dans un seul secteur, sans qu'aucune erreur ne se déclenche.
- **L'URL demandée ne garantit pas le secteur servi.** Le 27/07/2026,
  `/fr/cours-actions/197` a rendu « Energie » puis « Industriels » à dix
  minutes d'intervalle. Le code ne croit donc que l'intitulé affiché par
  la page elle-même, et écarte toute vue qui ne se réclame pas du secteur
  demandé.
- **La page des sociétés cotées ne publie aucun symbole boursier.**
  `/fr/emetteurs/societes-cotees` est une vue en fiches — logo, adresse,
  téléphone. Le référentiel se lit donc sur la cote, seule page à porter
  « Symbole » et « Nom ». (`/fr/societes-cotees/0`, l'URL qu'on croirait
  bonne, renvoie une 404 habillée du thème complet.)
- **Les colonnes ne se rafraîchissent pas ensemble.** Même séance close,
  `clôture / veille - 1` ne redonne la variation publiée que pour environ
  la moitié des lignes. Le diagnostic le signale sans bloquer : ni
  `veille` ni `variation` ne sont enregistrées.
- **La date de séance vient de `#block-tools-date-maj`**, pas de la
  bannière du site — deux horodatages différents cohabitent sur la page.
  Aucun repli sur la date du jour : une séance mal datée fausserait tous
  les décalages J → J+1 sans être détectable.

## Base

SQLite, `data/brvm.db` par défaut. Trois tables, déclarées dans
`src/brvm/db.py` :

| Table | Clé | Contenu |
|---|---|---|
| `cours` | (date, ticker) | ouverture, haut, bas, clôture, volumes |
| `referentiel` | ticker | nom, secteur |
| `journal_ingestion` | — | trace de chaque exécution |

Réenregistrer une séance déjà présente la corrige au lieu de la dupliquer.

`data/referentiel_amorce.csv` est le filet de secours quand le scraping du
référentiel échoue. Il a été constitué à partir des captures du 27/07/2026
et couvre les 47 sociétés avec leur secteur.

## Tests

```bash
pytest -q                     # ou : python tests/test_brvm_org.py
```

Vingt-trois tests, tous hors ligne : ils travaillent sur les captures
réelles de `tests/donnees/`, y compris les pages pathologiques (la 404, la
vue en fiches, la vue sectorielle trompeuse). Un test qui dépend du réseau
échoue pour des raisons étrangères au code qu'il vérifie.

## Licence

MIT — voir [LICENSE](LICENSE).

## Ce qui n'existe pas encore

Les commentaires du scraper mentionnent `features.liquidite`, `scoring.py`
et `depot.PRECISION` : l'analyse en aval de l'ingestion reste à écrire.
Le module dégrade proprement en attendant — un secteur manquant vaut `NA`,
où le scoring appliquera la pondération par défaut.
