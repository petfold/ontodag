# CLAUDE.md

Guidance for Claude Code in this repository: what is true now, and which
rules hold. Keep it that way. When the state, a rule or a decision changes,
edit its line here in the same commit, and put the story elsewhere:
`CHANGELOG.md` for what a release changes, a design record for why, and
`docs/plans/JOURNAL.md` for what a session did and measured. The journal
holds this file's diary up to 2026-10-09, moved there unchanged.

## What this project is

OntoDAG is a category store. Items are filed under categories in a
multi-parent DAG, and a query returns the intersection of the descendant
cones of its terms: everything below all of them. The root `*` is above
every top-level node. It is a subsumption-only ontology kept in
transitively reduced form, and since the reduction of a DAG is unique, the
stored form is canonical. That is what makes a store content-addressable
(equal knowledge, equal root), comparable, mergeable without coordination
(merge is a CRDT) and provable. Keeping the invariants exact is the point
of the project, not polish.

Typed values extend the order without adding reasoning: `mass(3kg)`,
`time(2026)`, `geo(u2e4)`, `in(paris)`, `about(x)` and
`shared-with(alice)` are categories ordered by computation on their names,
under a fixed set of kinds (`docs/DIMENSIONS.md`). Agents are the priority
consumer (`docs/CONTRACT.md`, `docs/AGENT_SURFACE.md`). One store is
reachable from the `odag` CLI, the web app, `odag-mcp` and Python, and
persists as a text file (`.od`), a local record store (`rs:PATH`) or on
Swarm (`swarm:NAME`).

## The family of repositories

All checked out beside this one in `/home/test/projects`, all on
github.com/petfold.

- **recordstore**: a versioned key-to-record store over content-addressed
  blobs: canonical roots, snapshots, three-way merge, proofs, history and
  undo. The one base dependency (`>=0.22.2`). Its brief is `ONBOARDING.md`.
- **swarmfs**: the one route to Bee: local-first stores and their sync,
  postage selection, feeds, and the shared signer `swarmfs.signer`. In the
  `swarm` extra (`swarmfs[feeds]>=0.13.0`).
- **ontodag-fs**: an OntoDAG store as a mountable filesystem. It pins a
  ceiling (`<0.31.0`); raise it by hand once ontodag's release job has run
  its suite against the candidate, then release it.
- **loopmarket**: the marketplace, and the main consumer of dimensions. It
  pins only a floor (`>=0.30.6`), and its suite runs in ontodag's release
  gate. Its offer ids hash canonical spellings, so stores made under
  another registry version need the `ontodag.migrate` replay before mixing.
- **ontodag-core**: builds the `core` pack and the ten domain packs by
  consensus over WordNet, SUMO, Wikidata and others, and regenerates
  `src/ontodag/core_ontology.py` and `src/ontodag/domain/*.py`. Its rules
  and rulings are in its `docs/UPPER.md` and `align/`.
- **factbond**: bonded assertions and adjudication. It consumes the
  contract; ontodag never imports it.
- **categorio** (categor.io): a website over ontodag (`>=0.30.1`), the
  driver of `sharing` and `keyplan`.

## Map of the code

`src/ontodag/`:

- `dag.py`: `Item`, `DAG`, `OntoDAG`. Reduction, counts by delta, the query
  planner, `is_below`, the dimension machinery (kinds, hop indexes,
  re-reduction, re-spelling), put/remove/reclassify/rename/merge. About
  5,000 lines in one class; review item 14 is about that.
- `dimensions.py`: the term grammar and the registry: kinds, unit
  families, exact arithmetic, canonical spellings, `REGISTRY_VERSION`.
- `native.py`: the `.od` text format (`#:canonical` mark, direct load,
  merge-of-lines load for unmarked files).
- `eager.py`: `EagerOntoDAG`, an OntoDAG over a record store, hydrated
  whole; `commit` writes what changed, `sync` is the merge rule.
- `lazy.py`: `LazyOntoDAG` (read-only, fetches as a query walks) and
  `SparseOntoDAG` (a partially resident writer).
- `cones.py`: published cone summaries. `certificates.py`:
  `prove_below`/`verify_below`. `provenance.py`: signed claim records in a
  sibling store. `compare.py`: what two stores differ in (`odag diff`).
- `surface.py`: readable output (`render`, `elaborate`). `browse.py`: the
  refinement rule behind the web page.
- `prelude.py`, `packs.py`, `core_ontology.py`, `domain/`: the prelude (v4)
  and the shipped packs.
- `sharing.py`, `keyplan.py`, `act.py`: who a store shares with (the cone
  of `shared-with(person)`), the key plan derived from it, and Bee-ACT
  primitives.
- `encstore.py`: encrypted `rs:` stores (AES-SIV).
- `settings.py`, `stores.py`, `_streams.py`: the settings table and its
  rule; the backends (file, `rs:`, `swarm:`) and `Store` (`ontodag.open`).
- `__main__.py`: the `odag` CLI; it keeps the old names of what moved out
  as aliases of the same objects. `mcp.py`: `odag-mcp` (stdio JSON-RPC).
  `web/`: the Flask app.
- `viz.py`, `owl.py`: Graphviz and OWL (extras). `migrate.py`: replays an
  old store through `put`. `browser.py`: the Pyodide bridge. `_extras.py`:
  teaching errors for a missing extra.

Elsewhere: `tests/` (fixtures in `tests/fixtures/`), `scripts/`
(`release_smoke.py`, `repin_golden_roots.py`, `browser_check.py`, a
Playwright check outside the suite), `experiments/` (one-off probes),
`demo/pyodide/` (the in-browser page), `paper/` (two manuscripts), and
`mypip/`, a virtualenv committed by accident (see the open questions).

## Tests, lint and CI

- `python3 -m pytest` from the repo root runs everything. `conftest.py`
  puts `src/` on the path and points `$ONTODAG_HOME` at a temporary
  directory; pyproject's `python_files = ["test*.py"]` also collects
  `testdag.py`, `testitem.py` and `testowl.py`. About 1,350 tests, about
  5 minutes on this laptop.
- `CI=1 python3 -m pytest` also checks the test count README.md states
  (passed plus skipped). Run it before any tag.
- Gated: `tests/test_swarm_bee.py` needs `BEE_API` and `BEE_BATCH`, and
  `BEE_SIGNER` for its feed test (see "Bee integration status"); the
  larger packs' golden roots and the union need `ONTODAG_SLOW_TESTS=1`.
- `tests/test_invariants.py` and `tests/test_boundaries.py` must always
  pass. `tests/test_reference.py` pins `docs/REFERENCE.md` to the code: a
  new command, setting, kind, MCP tool, extra or pack goes there too.
- Lint: `git ls-files -- '*.py' ':!mypip/**' | xargs python3 -m pyflakes`
  with pyflakes 3.4.0. It ignores `# noqa`, so try an optional import with
  `importlib.import_module`, declare a re-export in `__all__`, and put a
  fixture that several test modules share in a `conftest.py`.
- CI: `tests.yml` on every push (the suite on Python 3.11 and 3.12 with
  `[test,web]` and Graphviz, plus the lint job); `publish.yml` on a `v*`
  tag (next section).

## Releasing

Only on Peter's word. Pushing a `v*` tag publishes to PyPI; never dispatch
`publish.yml` by hand.

1. **Docs before publish** (Peter's rule), never as a follow-up: README.md
   (it is the PyPI page, test count included), `docs/USER_GUIDE.md` with
   executed snippets, HOW_IT_WORKS, REFERENCE, the help text, the
   CHANGELOG entry, and a grep for stale claims.
2. Bump `version` in pyproject.toml; re-run anything that prints it.
3. `python3 scripts/release_smoke.py`: build the wheel, install it in a
   throwaway venv and use it. A green suite is not evidence the artifact
   works (0.10.0 shipped unable to draw a store with a typed date).
4. Push the tag `vX.Y.Z`. `publish.yml` checks the tag against the
   version, runs the suite, builds, smoke-tests the wheel, runs the
   downstream matrix (ontodag-fs's and loopmarket's main against the
   candidate), uploads by trusted publishing (`skip-existing`) and
   smoke-tests what PyPI serves. By hand instead: `twine upload`
   (`~/.pypirc`), then step 5.
5. Verify from PyPI, never from disk: `scripts/release_smoke.py --pypi
   X.Y.Z`. The index lags; the script refuses to test the wrong version.

- Removing or renaming public API makes a minor release, and ontodag-fs's
  ceiling must then be raised and released.
- Release upstream first: recordstore and swarmfs, then ontodag, then its
  consumers.
- A pack rename or sense correction never propagates by merge: release it
  promptly, and republish the packs to Swarm from a fresh home
  (`odag -f swarm:pack-NAME pack NAME`), each root equal to its pinned
  `SWARM_GOLDEN_ROOTS` entry and retrievable.

## Invariants, boundaries and the contract

`tests/test_invariants.py`:

- **I1** acyclic: an edge that would close a cycle is refused.
- **I2** transitively reduced: no edge that another path implies.
- **I3** order-independent: `put(X, [A, B])` and `put(X, [B, A])` build
  the same graph.
- **I4** no aliasing: a derived DAG shares no `Item` with its source.
- **I5** exact counts: `descendant_count` is the number reachable by
  stored edges. The computed order is never counted or stored.
- **I6** iterative: traversals never recurse.
- **I7** merge is commutative and idempotent.

`tests/test_boundaries.py`:

- **B1** `import ontodag` and the core work with no optional dependency
  and no network; recordstore (pure Python, no dependencies of its own) is
  the only base dependency, and the metadata says so too. Optional modules
  (surface, viz, mcp, compare, encstore and others) never load with plain
  `import ontodag`.
- **B2** recordstore never depends on ontodag.

Contract 0.5 (`docs/CONTRACT.md`, `tests/test_contract.py`):

- **G1** equal knowledge, equal root (a semantic canonical form).
- **G2** merge is monotone: true stays true, answers only grow (a removal
  loses to a concurrent re-add).
- **G3** the same root and context give the same answers on any replica.
- **G4** `is_below` is fail-closed.
- **G5** writers who sync each other's roots converge byte for byte.
- **G6** `get_overlapping` is complete for possibility, silent on
  satisfaction.
- **G7** within one contract major and one registry major, a newer
  ontodag never takes an answer away. Its fixture (`tests/fixtures/g7.od`)
  is never regenerated to make a failure pass.
- **G8** a spelling or a stored form changes only with the registry minor,
  with the migrate step named in CHANGELOG. Regenerate its fixture
  (`make_g8.py`) only together with a registry bump.
- **G9** replays are order-free; single writes are checked as they come.

Versions now: contract 0.5, registry 4.3, prelude 4, surface 0.1.
Consumers compare majors.

## Standing rules

### Identity

- Names are the identity at every boundary: the API takes a string
  wherever it takes an `Item`, serialization is by name, and an `Item` or a
  pointer never crosses from one DAG instance to another (that leak was the
  `intersection_dag` aliasing bug). Inside one DAG, edges stay object
  references; don't turn `neighbors` into sets of strings.
- A node is a class of items, and below is inclusion (HOW_IT_WORKS §1).
  There is no class/instance distinction.
- The user's spelling is never stored. Input is elaborated to the
  canonical name, so two spellings of one fact reach one root, and
  `elaborate(render(t)) == t`.

### The core's semantics

- The core gains no further expressiveness. The one scoped exception is
  dimensions over nodes, with kinds fixed in code (CONTRACT §5.1): users
  declare heads, never rules. A new kind is a contract change; a new head
  never is.
- Admissible means monotone and computable from names. Negation, defaults
  and closed-world reasoning fight merge; they belong to a layer above that
  answers against a pinned root.
- Only exact arithmetic enters the order. The computed order is never
  stored as edges.
- `in` is for places and parts. Membership goes under kinds
  (`alice ⊑ sales-employee`), because `in` chains into location.
- A term of a relation or graph kind goes only under its head. Filed
  anywhere else it states a rule, which made evaluation exponential, so it
  is refused.
- Every query term is a containment term; an overlap query mode was built
  and withdrawn. Before building an operator a consumer asks for, ask what
  reading of the data needs it.
- A node filed under A and B is not their meet. Never route `get` through
  such nodes (SEMANTIC_CODES §10).
- Removing, moving, undoing and retracting are local: a peer that still
  holds the old fact brings it back on merge. A mergeable file carries
  additions only (`diff --additions`; never call it a patch).
- Replays (merge, sync, load, ingest) are order-free, and merge, sync and
  load never refuse; single writes are checked as they come (G9).

### Scale and measurement

- Exponential is out of the question; graphs will be very large. Every
  operation's work must grow with its output: filing is flat per put, and
  a query costs its answer. Pin that with count-based tests, and check each
  mechanism by switching it off.
- Measure, don't guess. A tuning constant is swept against the real thing
  (fresh data, both orders), the table is shown, and Peter picks.
- The planner's estimates steer time, never correctness. Never memoize an
  answer computed while a re-entrancy guard tripped.

### Units, vocabulary and packs

- Canonical values are reduced rationals of the SI coherent anchor.
  Built-in units are physical and digital measurement only; if a unit's
  importance can change, it belongs in a pack (UNITS.md §7). Measured
  values are intervals, definitional values points (§12).
- The prelude holds only the names the interpreter dereferences; anything
  else is a pack. A pack is a store, and adopting it is a merge. Names stay
  identity: collisions are detected, not prevented.
- Changing the prelude's or a pack's declarations bumps its version, and
  the golden roots are re-pinned (`scripts/repin_golden_roots.py [--swarm]
  [--union]`).
- A pack never takes an everyday word. A sense correction or a rename is
  an intervention (ontodag-core's UPPER.md).

### Surfaces and storage

- Output is canonical when stdout is not a terminal, so `odag get | odag
  put` round-trips (`--render` and `--raw` override). Stderr always
  renders.
- Answers and pictures read the view (the store plus overlays); writes and
  mergeable artifacts read the store alone. An excerpt never invents a node
  (it is imported again); a picture may draw the query's terms (it is
  thrown away).
- Settings resolve flag, then environment, then config file, then default
  (`ontodag.settings`); `set` validates when it sets.
- A `-m` message labels a transition in this replica's timeline, never the
  content: a root hashes state alone.
- The marker in a store decides whether it is encrypted; `store_key` only
  supplies the key.
- The CLI caps what it shows at 50 lines, on a terminal only, and says on
  stderr how many it held back. `odag count` and MCP answers are never
  capped by default (an agent cannot see a truncation).
- A `swarm:` store is open only while a load or a save runs, never held
  between them. No silent fallback to a local store, and no starting
  Bee.
- A missing extra or program is an instruction naming the command to run
  (`MissingExtra`), never a traceback. Gate a test on the program
  (`shutil.which("dot")`), not on its Python wrapper.
- A dependency earns a place in the base install only if it changes what
  the package is; anything that adds weight for one feature is an extra.

### Code and tests

- Comments and docstrings say what is true now. History goes to
  CHANGELOG.md, a design record or the journal, not into dated notes in
  the code.
- One concern per commit: an invariant, a design-record section, a
  decision.
- A bug's test must fail on the code before the fix.
- Tests patch `ontodag.stores.make_backend` and `_SYNC_TIMEOUT`, not the
  CLI's aliases (rebinding an alias changes nothing).
- A test that needs an optional dependency skips without it. Check by
  hiding the dependency (`dot` from `PATH`, for instance).
- A 200 is not a pass: check what came back.

### Working with Peter

- Peter decides; Claude records the decision and builds it. An open
  question is put on its own: the question, a concrete example, the
  options with pros and cons, and a recommendation with the reason.
- Commit and push when a piece is done; release only on Peter's word.
- Never print key material. Throwaway signers come from
  `python3 -c 'import secrets;print(secrets.token_hex(32))'`.
- Never commit in the same command that reads a validation result.
- Search the tracker and read the source before drafting an upstream
  issue.
- Kill a process by its PID: `pkill -f NAME` also kills the shell whose
  command line contains NAME.

## Decisions in force

Each line points to its record.

- Agents are the priority consumer, and the human interface stays decent
  (CONTRACT.md, AGENT_SURFACE.md).
- Writers converge by the CRDT merge (I7), never by locking
  (SWARM_DESIGN.md §5).
- Three tiers of store, each worth having on its own: a file (`.od`),
  `rs:PATH` (roots, history, certificates, sync; no node needed) and
  `swarm:NAME` (shared). `odag swarm` checks the way to the last.
- recordstore is the base dependency; everything else is an extra. All Bee
  traffic goes through swarmfs, with one shared signer
  (`swarmfs.signer`), 32 requests in flight (measured).
- Packs: PACKS.md Part II. Core v13 and ten domain packs ship in the wheel,
  built in ontodag-core.
- Units: UNITS.md (rational anchors; bare `C` and `F` are Celsius and
  Fahrenheit, `coulomb` and `farad` spelled out; counts start at 1).
- Roles and relations: ROLES.md §8. Prelude 4 says `mass`, pins heads to
  unit families, and carries `in`, `about` and `shared-with`, but not
  `from` and `to`.
- A graph-kind compound is stored as its parts; a relation-kind compound
  keeps its current spelling (DIMENSIONS.md §15–§16).
- Sharing: one model, the cone of `shared-with(person)` (SHARING.md).
- Provenance: signed claim records in a sibling store (PROVENANCE.md).
- Web: one page, browsing plus a console, where every click writes its
  command (WEB_UI.md). Its DAG lives in the server's memory per session.
- The 2026-10 review (`docs/plans/REVIEW_2026-10.md` §8), decided on
  2026-10-09:
  1. A category that terms name can't be removed from under them;
     `--with-terms` and `rename` are the ways on (item 16).
  2. Spellings: signal, don't freeze (G8; §5).
  3. Single writes strict, replays order-free (G9; item 15).
  4. Native files carry a canonical mark and load directly; other files
     load as a merge of their lines (item 8).
  5. A small public layer: `ontodag.open`, `ontodag.settings`,
     `parse_term`, `canonical`, `parents_of` (item 7).
  6. The query-by-file path is gone (item 3).
  7. A term nests at most 32 levels; `odag-mcp` survives any request (§4).
  8. A broad `about` query and other typed terms cost their answer
     (item 13).
  9. loopmarket in the release gate, its chain tests nightly, pyflakes in
     every repo (item 5).
  10. This file is a current-state guide, the diary a journal (item 6).

## Bee integration status

- The node: Swarm Desktop's bee 2.8.2 light node at `localhost:1633`, on
  Gnosis mainnet. Another node manager can hold the same port, so `curl
  /health` and `/stamps` before believing anything about a batch.
- The batch: `c931c8a5…`, depth 22, paid until 2026-11-15 12:00 UTC. Buy,
  top up or dilute only on Peter's word. The amount per chunk is price ×
  17,280 blocks a day × days, the cost that amount × 2^depth PLUR (1 xBZZ
  = 10^16 PLUR), and diluting one depth halves the time left.
- Always pass a real `BEE_BATCH` (nothing auto-buys) and a throwaway
  `BEE_SIGNER`.
- An upload that reports success may not have landed. Check every
  published root with `GET /stewardship/<ref>`, and upload again what is
  not retrievable (ethersphere/bee#5400).
- Bee's keys are encrypted with the password in its `config.yaml`; back
  that file up with the data directory.
- Not yet tested on a real node: postage expiry and garbage collection
  (they need a batch nobody minds losing).
- Last run: 2026-10-09, before the 0.30.8 release; ontodag's two gated
  tests and loopmarket's three live tests passed. Every run since July,
  with what each taught, is in the journal under this heading.

## State (2026-10-09)

- Released, each verified from PyPI: ontodag 0.30.8, recordstore 0.22.2,
  swarmfs 0.14.0, loopmarket 0.14.5, ontodag-fs 0.6.4.
- On main, not released: the review's decisions 1–9 and a fix for loading
  role terms from a native file (CHANGELOG "Unreleased"). Two public
  methods were removed, so the next release is a minor, 0.31.0, and needs
  ontodag-fs's ceiling raised. It waits for Peter's word.
- After 0.31.0: move loopmarket and ontodag-fs from the CLI aliases to the
  public names (each needs a release with the new floor), and make
  categor.io's "remove contact" pass `with_terms=True`. ontodag issue #13
  (opening a store at a chosen residency) belongs on `Store`.
- The sister repos' CI and lint changes are on their main branches, not
  released; none changes behaviour.

## Open questions for Peter

From the 2026-10 review (`docs/plans/REVIEW_2026-10.md` §8), not yet
decided:

- ontodag: **14**, a complexity budget for the kinds (an interpreter object
  of its own); **18**, whether a merge files canonically, folding
  overlapping values as `put` does; **19**, what a merge does with a role
  literal that meets a category of the same name outside the dimension.
- loopmarket: **2**, the indexed matcher in the solver; **4**, comparing
  offer pins with the installed ontodag; **9**, checking a clearing book's
  fills before the fold admits them; **10**, splitting `cli.py`; **11**,
  one duration grammar with ontodag (`90m`, `1w`); **12**, retiring v1/v2
  offers and renaming `MockClearing`; **17**, the build order against the
  README's gates.
- Also raised by the review: untracking `mypip/` (§4), and which of the
  remaining test suggestions to take up (§7, items 1–5, 7 and 9).

They are put to Peter one at a time in that order, numbered on from the
ten decided: item 14 is question 11, item 18 question 12, and so on.

Older, not urgent: the 0.31.0 release; a publisher key for the packs on
Swarm (published without one, so no feed yet; PACKS.md); BROWSER.md §7's
two questions about the in-browser node; ontodag-core's doubtful list
(its UPPER.md §9).

Parked behind a discussion or a tripwire (in `docs/plans/`, some only in
the journal): the
surface layer (and ROLES §9 step 6), bundles (BINDING), an ordinal kind and
the top ontology (EVOLUTION), computed values, a contract clause for
self-declared truncation, MCP reads through overlays, a query log outside
the web app, and the postage-expiry experiment.

## Documentation and history

- `docs/README.md` is the map: USER_GUIDE (tutorial and how-to, executed
  snippets), REFERENCE (pinned by tests), HOW_IT_WORKS (explanation),
  UNIT_TABLE (generated), the design records (CONTRACT, PROVENANCE,
  AGENT_SURFACE, DIMENSIONS, UNITS, CORE, SWARM_DESIGN,
  recordstore-interface) and `docs/plans/` (drafts and directions; nothing
  there is shipped). Check the map before adding a section anywhere.
- `paper/`: `main.tex` (the systems paper) and `ontodag-fca.tex` (the FCA
  companion); `make` builds them, and their numbers come from
  `paper/experiments/`.
- History: `CHANGELOG.md` (every release since 0.1.0),
  `docs/plans/JOURNAL.md`, the design records' update notes, and git.

## Starting a session

1. `git status` and `git log --oneline -5` here, and in any sister repo
   before touching it.
2. Read "State" and "Open questions for Peter" above.
3. Before changing code, run the suite (`python3 -m pytest`, about 5
   minutes) or the test files the change touches.
4. When the state, a rule or a decision changes, update its line here in
   the same commit.
