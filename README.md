# OntoDAG

[![tests](https://github.com/petfold/ontodag/actions/workflows/tests.yml/badge.svg)](https://github.com/petfold/ontodag/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/ontodag)](https://pypi.org/project/ontodag/)
[![license](https://img.shields.io/badge/license-BSD--3--Clause-blue)](LICENSE)

Associative memory and categories based on a directed acyclic graph data structure

## Documentation

- **[User Guide](docs/USER_GUIDE.md)** — installation, tutorial, Python API,
  command line, web app/REST, file formats, troubleshooting. Start here.
- **[How It Works Inside](docs/HOW_IT_WORKS.md)** — the design in plain language
  (canonical form, query planning, content-addressed persistence).
- **[Roadmap](docs/ROADMAP.md)** — delivered, queued, parked, and research horizon.
- `docs/SWARM_DESIGN.md`, `docs/SEMANTIC_CODES.md` — engineering design documents.

See also **[ontodag-fs](https://github.com/petfold/ontodag-fs)**: any OntoDAG
store can be browsed as a filesystem — paths are category queries, files are
classified objects stored on Swarm, FUSE-mountable (`odag-fs`, which shares
odag's store settings).

## Specification

A Directed Acyclic Graph (DAG) associative storage and category manager in Python. You can store items into a ontodag and recall items from it. To store or "put" an item into a ontodag, you give it a name and a set of other names of already existing items that are its supercategories. To recall or "get", you specify a set of item names to get all items that are subcategories of all these items.

Categories can also carry **typed values**: declare `weight` as a dimension
and `weight(3kg)` becomes an ordinary category whose ordering OntoDAG
computes — `odag get 'weight(..5kg)'` finds the 3 kg parcel with no edge ever
stored between them, at any threshold, with exact integer arithmetic. Ranges
(`1kg..5kg`), timestamps and date ranges, hierarchical codes like geohash
cells, and does-it-fit size tuples all work the same way. See
[User Guide §4.7](docs/USER_GUIDE.md) and the design record
[docs/DIMENSIONS.md](docs/DIMENSIONS.md).

## Roadmap

The roadmap — what is done, what is queued next, what is parked and why — is in
**[docs/ROADMAP.md](docs/ROADMAP.md)**.
Longer-term goals for the database direction (and the features deliberately not
built yet) are in [docs/DATABASE_DIRECTION.md](docs/DATABASE_DIRECTION.md); the
day-to-day task list is in `CLAUDE.md`.

## Potential Applications
* Using the ontology graph for content categorization instead of folders
* Replace content tags with a more structured ontology
* Access control (ACT) groups
* Memberships in organizations and gate content based on membership
* Communication channel groups defined by the ontology
* Fostering deals within a universal marketplace for services and goods
