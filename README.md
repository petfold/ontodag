# OntoDAG

[![tests](https://github.com/petfold/ontodag/actions/workflows/tests.yml/badge.svg)](https://github.com/petfold/ontodag/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/ontodag)](https://pypi.org/project/ontodag/)
[![license](https://img.shields.io/badge/license-BSD--3--Clause-blue)](LICENSE)

Associative memory and categories based on a directed acyclic graph data structure

## Documentation

- **[User Guide](docs/USER_GUIDE.md)** — installation, tutorial, Python API,
  command line, web app/REST, file formats, AI agents, troubleshooting. Start here.
- **[How It Works Inside](docs/HOW_IT_WORKS.md)** — the design in plain language
  (canonical form, query planning, content-addressed persistence, verifiable answers).
- **[Roadmap](docs/ROADMAP.md)** — delivered, queued, parked, and research horizon.
- **[The contract](docs/CONTRACT.md)** — what programs (and AI agents) built on
  OntoDAG may rely on: the guarantees, versioned.
- `docs/SWARM_DESIGN.md`, `docs/SEMANTIC_CODES.md`, `docs/AGENT_SURFACE.md` —
  engineering design documents.

See also **[ontodag-fs](https://github.com/petfold/ontodag-fs)**: any OntoDAG
store can be browsed as a filesystem — paths are category queries, files are
classified objects stored on Swarm, FUSE-mountable (`odag-fs`, which shares
odag's store settings).

## Specification

A Directed Acyclic Graph (DAG) associative storage and category manager in Python. You can store items into a ontodag and recall items from it. To store or "put" an item into a ontodag, you give it a name and a set of other names of already existing items that are its supercategories. To recall or "get", you specify a set of item names to get all items that are subcategories of all these items; alternatives are one word away (`odag get Flight Japan or Hotel`, `get_any` in Python).

File a flight confirmation under both `Flight` and `Japan`, the boarding pass
under the flight itself, and `odag get Japan` returns the whole trip — including
the boarding pass you never filed under the trip. No folder had to be chosen.

Categories can also carry **typed values**: declare `time` as a dimension
and `time(2026-08-15)` becomes an ordinary category whose ordering OntoDAG
computes — `odag get Flight 'time(2026-06-01..2026-08-31)'` finds last summer's
flights with no edge ever stored between them, at any range, with exact integer
arithmetic. Weights and sizes (`weight(..5kg)`), hierarchical codes like geohash
cells, and does-it-fit tuples all work the same way. See
[User Guide §4.7](docs/USER_GUIDE.md) and the design record
[docs/DIMENSIONS.md](docs/DIMENSIONS.md).

Values are stored in an exact canonical form and shown to you in a friendly
one: on a terminal `odag` prints `time(2026)` and `weight(3kg)`, while pipes
and files always get the exact bytes, so `odag get ... | odag` round-trips
(`--render`/`--raw` override; `odag canon TERM` shows what any spelling
actually stores).

## For AI agents

Serve any store to an agent over MCP, read-only, with **`odag-mcp`**
(`claude mcp add odag -- odag-mcp`): query, fits-within, overlap candidates,
per-item description, canonical echo, and an `about` tool that says what the
store contains. Every answer cites the **root** — a fingerprint of the
store's entire content — and `is_below` answers can carry a **certificate**
that anyone holding only that fingerprint can verify, with no access to the
store (`ontodag.certificates.verify_below`). Equal knowledge yields an equal
fingerprint, so two parties can prove they agree — and a disagreement shows
up as structure, not prose. The guarantees an agent (or any program) may
rely on are written down and versioned in [docs/CONTRACT.md](docs/CONTRACT.md);
the tool shapes in [docs/AGENT_SURFACE.md](docs/AGENT_SURFACE.md).

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
