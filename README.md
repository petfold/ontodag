# OntoDAG

[![tests](https://github.com/petfold/ontodag/actions/workflows/tests.yml/badge.svg)](https://github.com/petfold/ontodag/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/ontodag)](https://pypi.org/project/ontodag/)
[![license](https://img.shields.io/badge/license-BSD--3--Clause-blue)](LICENSE)

Associative memory and categories based on a directed acyclic graph data structure

## Documentation

- **[User Guide](docs/USER_GUIDE.md)** — tutorial and how-to: installation, Python,
  command line, web app/REST, AI agents, troubleshooting. Start here.
- **[Reference](docs/REFERENCE.md)** — every command, setting, kind, endpoint and
  tool, compact; its tables are pinned to the code by the test suite.
- **[How It Works Inside](docs/HOW_IT_WORKS.md)** — the design in plain language
  (canonical form, query planning, content-addressed persistence, verifiable answers).
- **[Changelog](CHANGELOG.md)** — what each release added, with registry migration notes.
- **[The contract](docs/CONTRACT.md)** — what programs (and AI agents) built on
  OntoDAG may rely on: the guarantees, versioned.
- **[docs/README.md](docs/README.md)** — the full documentation map: design records
  (`docs/`) and discussion drafts / future directions (`docs/plans/`, including the
  [Roadmap](docs/plans/ROADMAP.md)).

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
flights with no edge ever stored between them, at any range, with exact
arithmetic — values are rationals of the SI anchor units, so *every* exactly
defined unit works: all of SI, pounds and psi, TB and TiB, even Celsius and
Fahrenheit (mapped exactly onto the kelvin scale: `temperature(24C)`) built
in, and **unit packs one merge
away** (`odag pack crypto-core` for BTC/ETH/BZZ, `fiat-iso4217` for ~150 national
currencies, `crypto-majors` for the market's top coins — or declare your
own: vocabulary is graph data that travels with the store, no release
needed). `odag prelude` declares the everyday dimensions in one command. Weights and sizes (`weight(..5kg)`), hierarchical codes like geohash
cells, and does-it-fit tuples all work the same way. See
[User Guide §4.7](docs/USER_GUIDE.md) and the design record
[docs/DIMENSIONS.md](docs/DIMENSIONS.md).

Values are stored in an exact canonical form and shown to you in a friendly
one: on a terminal `odag` prints `time(2026)` and `weight(3kg)`, while pipes
and files always get the exact bytes, so `odag get ... | odag` round-trips
(`--render`/`--raw` override; `odag canon TERM` shows what any spelling
actually stores). The same split governs how much you get: a terminal stops
at 50 results with a note saying how many were withheld, a pipe is never
truncated. A query with no terms at all is the empty intersection — no
constraints, so every item (`odag count` gives just the size).

## Changing your mind

Filing things is the easy half. Categories move, projects finish, and mistakes
happen, so the operations that *unfile* are first-class:

```console
$ odag -m "archiving Q2" move ProjectA --from active --to archive
odag: moved: 2 items left active, 1 still in both active and archive (shared-spec.md)
$ odag remove Flight                              # the category goes, its contents stay
$ odag remove --cone Japan --dry-run              # the category AND its contents
Japan
Onsen
odag: would delete 2 items; kept 3 that hang elsewhere too (JAL JAL-cheap Ryokan)
```

Everything below a moved item travels with it — membership is reachability, so
there is no subtree to walk. Two things in that output are the point rather than
the detail. A move reports what ended up in **both** states: in a multi-parent
DAG a shared item really can be in two, because subsumption inherits and
exclusive status cannot, so it is named rather than silently decided. And a cone
deletion spares what hangs elsewhere — the rule is *deleted iff the root can no
longer reach it*, the only reading of "delete the subgraph" that does not quietly
destroy multi-parent members.

On a store that keeps history (see below) none of it is a one-way door:

```console
$ odag history
* 24f60cdef46b  2026-08-06 12:34:56  archiving Q2
  7cffeb02f241  2026-08-06 12:34:56  set up the projects
$ odag undo
odag: undid to 7cffeb02f241 — 2 classifications changed
$ odag get active
ProjectA
ProjectB
a-notes.md
shared-spec.md
```

A root is a hash of the whole state, so a past version is not a diff to be
replayed — it is a state that still exists, and undo *points* at it. `redo` comes
forward again, `-m` labels a state, and `odag status` says what is possible.

## Sending someone a piece of your store

```console
$ odag excerpt japan.od Travel Japan --context    # the answer, plus how it hangs
$ odag diff back.od Travel Japan                  # what came back changed
+ item Ryokan-Kyoto (Ryokan)
+ below JAL-cheap Ryokan
odag: +1/-0 items, +1/-0 claims listed; +6/-0 entailed claims over 8 names
```

`--context` is what makes the cut mergeable *and* diffable elsewhere; `diff
--additions` writes the additive half as a file `odag merge` applies — and
merging it lands on the byte-identical root that merging the whole store would,
which is why there is no patch format. Comparison decides by *meaning*: adding
one edge can prune others without losing anything, so a re-routed edge is never
reported as a deletion.

## Where a store lives

Three tiers, each paying for itself, and the same commands throughout:

```
file (.od)   a DAG that persists. Works anywhere, no dependencies.
rs:PATH      canonical roots, snapshots, version history, certificates. No node.
swarm:NAME   the same store, shared — content on Swarm, head in a signed feed.
```

`odag swarm` walks you through the last step and tells you what to fix next.
Equal knowledge always yields an equal root, whatever order it arrived in, which
is what makes stores diffable, mergeable between writers, and verifiable by
someone holding nothing but the root.

## In a browser

```bash
pip install "ontodag[web]" && cd web && python3 app.py   # localhost:5000
```

Browsing *is* querying, because in OntoDAG a path is a query: `/pet/dog` means
*pet AND dog*, and `/dog/pet` is the same place. So clicking a category appends
a term to a conjunction — and the page shows you that, by echoing every click
into a console as the command it means (`get Japan Flight`). Point at things
and you have learned the command language without looking anything up. The
**Refine by** list only offers categories that genuinely narrow what you are
looking at, with the count each click will leave; the graph is clickable; and a
`Commands` button lists all 26 OntoDAG commands, marking which of them a
browser can run and why the rest cannot.

The web app's DAG is server memory per session — a workbench and a demo, not a
front end onto your store.

## For AI agents

Serve any store to an agent over MCP with **`odag-mcp`**
(`claude mcp add odag -- odag-mcp`): query, fits-within, overlap candidates,
per-item description, canonical echo, and an `about` tool that says what the
store contains — read-only by default; `--write` adds a propose→confirm write
surface where every change carries a **signed provenance record** (who
asserted what, against which state) and a `review` tool computes each claim's
standing under *your* trust list: claims merge, acceptance is policy. Every answer cites the **root** — a fingerprint of the
store's entire content — and `is_below` answers can carry a **certificate**
that anyone holding only that fingerprint can verify, with no access to the
store (`ontodag.certificates.verify_below`). Equal knowledge yields an equal
fingerprint, so two parties can prove they agree — and a disagreement shows
up as structure, not prose. The guarantees an agent (or any program) may
rely on are written down and versioned in [docs/CONTRACT.md](docs/CONTRACT.md);
the tool shapes in [docs/AGENT_SURFACE.md](docs/AGENT_SURFACE.md).

## Roadmap

The roadmap — what is done, what is queued next, what is parked and why — is in
**[docs/plans/ROADMAP.md](docs/plans/ROADMAP.md)**.
Longer-term goals for the database direction (and the features deliberately not
built yet) are in [docs/plans/DATABASE_DIRECTION.md](docs/plans/DATABASE_DIRECTION.md); the
day-to-day task list is in `CLAUDE.md`.

## Potential Applications
* Using the ontology graph for content categorization instead of folders
* Replace content tags with a more structured ontology
* Access control (ACT) groups
* Memberships in organizations and gate content based on membership
* Communication channel groups defined by the ontology
* Fostering deals within a universal marketplace for services and goods
