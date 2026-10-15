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
`time(2026)`, `geo(48.85..48.87,2.28..2.30)`, `in(paris)`, `about(x)` and
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
  undo. The one base dependency (`>=0.24.0`). Its brief is `ONBOARDING.md`.
- **swarmfs**: the one route to Bee: local-first stores and their sync,
  postage selection, feeds, and the shared signer `swarmfs.signer`. In the
  `swarm` extra (`swarmfs[feeds]>=0.15.0`).
- **ontodag-fs**: an OntoDAG store as a mountable filesystem. It pins a
  floor and a ceiling (`>=0.33.0,<0.34.0` since its 0.9.0); raise the ceiling by hand once ontodag's release job has run
  its suite against the candidate, then release it.
- **loopmarket**: the marketplace, and the main consumer of dimensions. It
  pins only a floor (`>=0.31.0`), and its suite runs in ontodag's release
  gate. Its offer ids hash canonical spellings, so stores made under
  another registry version need the `ontodag.migrate` replay before mixing.
- **ontodag-core**: builds the `core` pack and the ten domain packs by
  consensus over WordNet, SUMO, Wikidata and others, and regenerates
  `src/ontodag/core_ontology.py` and `src/ontodag/domain/*.py`. Its rules
  and rulings are in its `docs/UPPER.md` and `align/`.
- **factbond**: bonded assertions and adjudication. It consumes the
  contract; ontodag never imports it.
- **categorio** (categor.io): a website over ontodag (`>=0.31.0`), the
  driver of `sharing` and `keyplan`. Its live site updates by the admin's
  ssh step (its `docs/ADMIN.md`).

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
  old store through `put`. `browser.py`: the Pyodide bridge, with the
  organiser page's `Organiser`. `folders.py`: a folder's files and
  single files filed as documents with their contents as versions (BROWSER.md
  §17); `capture.py`, when and where a photo or a video was taken, from
  its own metadata (EXIF, MP4 and MOV), standard library only.
  `suggest.py` and `core_words.py`
  (generated in ontodag-core from WordNet; `NOTICE` carries its licence):
  suggestions while typing. `_extras.py`: teaching errors for a missing
  extra.

Elsewhere: `tests/` (fixtures in `tests/fixtures/`), `scripts/`
(`release_smoke.py`, `repin_golden_roots.py`, `browser_check.py`, a
Playwright check outside the suite), `experiments/` (one-off probes, and
`cgagviz.py`, the October 2024 prototype that came out of `mypip/`, a
virtualenv committed by accident and untracked by question 22),
`demo/pyodide/` (the in-browser page) and `paper/` (two manuscripts).

## Tests, lint and CI

- `python3 -m pytest` from the repo root runs everything. `conftest.py`
  puts `src/` on the path and points `$ONTODAG_HOME` at a temporary
  directory; pyproject's `python_files = ["test*.py"]` also collects
  `testdag.py`, `testitem.py` and `testowl.py`. About 1,400 tests, about
  6 minutes on this laptop.
- `CI=1 python3 -m pytest` also checks the test count README.md states
  (passed plus skipped). Run it before any tag.
- Gated: `tests/test_swarm_bee.py` needs `BEE_API` and `BEE_BATCH`, and
  `BEE_SIGNER` for its feed test (see "Bee integration status"); the
  larger packs' golden roots and the union need `ONTODAG_SLOW_TESTS=1`.
- `tests/test_invariants.py` and `tests/test_boundaries.py` must always
  pass. `tests/test_reference.py` pins `docs/REFERENCE.md` to the code: a
  new command, setting, kind, MCP tool, extra or pack goes there too.
- Lint: `git ls-files -- '*.py' | xargs python3 -m pyflakes`
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

Contract 0.6 (`docs/CONTRACT.md`, `tests/test_contract.py`):

- **G1** equal knowledge, equal root (a semantic canonical form), whether
  it came by `put` or by a merge. A value is kept only while something is
  filed under it or it is filed under an ordinary category.
- **G2** merge is monotone: true stays true, answers only grow (a removal
  loses to a concurrent re-add; a value nothing is filed under any more
  leaves the `get` answers it was listed in, an item never).
- **G3** the same root and context give the same answers on any replica.
- **G4** `is_below` is fail-closed.
- **G5** writers who sync each other's roots converge byte for byte,
  except for values a merge left that cannot all hold (listed by `odag
  status`).
- **G6** `get_overlapping` is complete for possibility, silent on
  satisfaction.
- **G7** within one contract major and one registry major, a newer
  ontodag never takes an answer away. Its fixture (`tests/fixtures/g7.od`)
  is never regenerated to make a failure pass.
- **G8** a spelling or a stored form changes only with the registry minor,
  with the migrate step named in CHANGELOG. Regenerate its fixture
  (`make_g8.py`) only together with a registry bump.
- **G9** replays are order-free; single writes are checked as they come.

Versions now: contract 0.7, prelude 5, surface 0.2, all released since
0.32.0; registry 6.0 on main (5.0 released). Consumers compare majors.

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
- A new kind must retire complexity elsewhere and bring its oracle and
  measurements (DIMENSIONS.md §13). Keep every cache and flag declared in
  `_declare_state`, and index through `_on_node_added`, never beside it.
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
- Identity in the browser (option A, Peter, 2026-10-11): one key, the
  same in every client. It owns the user's feeds, signs, and does the
  sharing ECDH. For now it is a random key in a plain file, and the node's
  batches pay, as with `odag` and `loop`. A wallet signature (dappdata) or
  Swarm ID will later carry that same key to new devices, so nothing
  changes owner (questions 37 and 38, 2026-10-13, BROWSER.md §14.3); a
  password-protected key file comes later too. ontodag keeps its own access
  control (`keyplan`), not the node's ACT. A page reaches Swarm through
  four calls on chunks, with one adapter per client: Freedom, Weeb-3, an
  HTTP node, a gateway (BROWSER.md §10–§12, SHARING_ON_SWARM.md §2). Where
  a client hands over whole blobs (a node, a gateway), the page reads them
  whole with `/bytes`, checked by recomputing the address; Freedom reads
  chunks (Peter, 2026-10-15, BROWSER.md §10.1).
  Freedom requests #647, #648 and #722 (a whole-blob read) are filed, and
  freedom-hq/ant#187 (its README); for local files, Freedom #671 (fixed in
  their nightly of 2026-10-15)
  and Brave #59862 (BROWSER.md §14). The read-only page
  (`demo/freedom/`) runs in Freedom Browser (BROWSER.md §13). JSPI
  (`run_sync`) carries Python's store calls in Chromium-based browsers, so
  recordstore and `LazyOntoDAG` run unchanged; `swarm.js` joins and checks
  chunks in the page; `LazyOntoDAG(prefetch=True)` reads a level per round
  trip. It needs recordstore's `get_many`, unreleased: the page bundles
  recordstore's main. Where JSPI cannot suspend Python (Pyodide on iOS,
  whose function-pointer trampoline is JavaScript), the pages read by
  retrying: Python reads only fetched blobs, and the page fetches what a
  call needed and runs it again (BROWSER.md §15).
- The browser page as a personal organiser (Peter, 2026-10-13,
  BROWSER.md §17): your store first; the packs behind a "Vocabularies"
  menu and offered as suggestions while filing; a folder read, never
  written, its files tagged by type in a layer rebuilt on each opening;
  any combination of stores shown together, only yours written.
  Question 39 decided A: a vocabulary's category enters your store as a
  name only, and the vocabulary shown alongside supplies its places.
  Question 40 decided B in its document form: a filed file is a document
  node named by its file name, with each content it has had below it as
  a version named by its SHA-256, each version with its modification
  time. Question 41 decided C: the store and the list of hashes are kept
  in the browser's storage, encrypted with the person's key, wherever
  the page runs; Save stays the copy the person owns. Question 42
  decided B: Publish encrypts by default (the `rs:` stores' AES-SIV, a
  key derived from the key file, so devices still converge), "readable
  by anyone" a choice per store; `swarm:` stores in `odag` must learn the
  same. Question 43 decided A: the installed version gets it too, as one
  Python core built and measured with `odag` commands first, then the
  page on it. Question 44 decided B: a contact detail goes under
  `about(person)` and a class (`+447700900123 ⊑ about(alice),
  phone-number`; `signal-id ⊑ identifier, about(signal-messenger)`),
  never below the person, whose classes it would inherit. Question 45
  decided B with the draft rule: a quick note is a `.md` file in a notes
  folder, kept as a draft in the page's encrypted storage only until it
  is saved; the store never holds file bytes. The layout went into the
  page first (Peter, 2026-10-13), with core's WordNet words as a finding
  aid, never names (`ontodag.suggest`, `ontodag.core_words`,
  `ontodag.browser.Organiser`); folders, documents and versions follow
  the Python core, now built with `odag folder` and `odag file`, and in
  the page as Files… (2026-10-15).
  Question 46 decided B: on a screen an answer folds a document's
  versions into its line; a pipe gets every name. A mockup shows the
  whole design (BROWSER.md §17).
- Redundancy (question 47, decided C by Peter, 2026-10-15, BROWSER.md
  §13): every upload names its level, never the node's default: level 1
  for a blob up to 4 KB (two copies of it, its reference unchanged),
  level 0 above, so a reference is always computable from Swarm's own
  rules (a chunk's address, the plain tree) and never from Bee's coding.
  We build no trees and keep no records small on purpose. Protection for
  large records is revisited when the organiser makes them.
- A role of `geo` takes its rectangle without `geo(…)`, written and stored
  so, as time roles take their time: one rule for every kind, a
  parameter naming a filed node is that node and anything else a value
  (question 50, decided C by Peter, 2026-10-15, BROWSER.md §17). Built on
  main as registry 6.0, a major (Peter: A), with its migrate step
  (DIMENSIONS.md §23); re-put once G7 held again, the major was kept
  (Peter: A, 2026-10-15), so an older reader refuses a newer store or
  offer by its major. loopmarket's `from`/`to` follow on its branch
  `ontodag-0.34`. The capture heads proposed there are built too
  (`folders.HEADS`).
- Capture places (question 49, decided by Peter, 2026-10-15, BROWSER.md
  §17): stored in your store and in what you publish encrypted; the
  choice "include where photos were taken" (off by default) is made at
  sharing and for public versions, and today's readable Publish counts as
  one; `odag` warns before putting them into a readable `swarm:` store.
  Order: capture metadata (with question 50), encrypted Publish
  (question 42), then the choice at sharing. Step 1 built 2026-10-15:
  `odag` keeps places in local stores and leaves them out of a `swarm:`
  one unless `--places`; the page keeps them out of its store until
  Publish encrypts, since its Publish is a readable copy of the store.
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
  11. The kinds get a complexity budget: a new kind must retire complexity
      elsewhere (DIMENSIONS.md §13); every cache and flag is declared in
      `_declare_state`, and every new node passes the base class's
      `_on_node_added` hook (item 14). Built.
  12. Every replay (merge, sync, loading an unmarked file) folds an item's
      overlapping values of one head into their meet, as `put` does;
      contradicting values stay as they arrive and `odag status` lists
      them; contract 0.6, registry 4.4 (item 18). Built. It found item 21:
      question 24, decided A (a value is kept only while something is
      filed under it; for this change only, older stores get no
      allowance). Built: a write forgets the values it leaves unused, a
      bare value put is refused, a value is below its head whether or not
      its node exists, and G7's test states the one exception.
  13. A role term whose name meets a category outside its dimension reads
      as the value when stored, is refused when written or typed;
      `name_clashes()` and `odag status` list such clashes (item 19).
      Built.
  14. In a role a bare word is a filed place and a value is written by
      its base's name, `from(geo(...))` (item 20). Built in ontodag and in
      loopmarket 0.15.0; since registry 5.0 the value is a rectangle and a
      bare word is never read as a cell, in a query either; since registry
      6.0 the rectangle is written bare, `from(48..49,2..3)` (question 50).
  15. loopmarket: one matching engine, ontodag's index, for simple
      matches and the aggregation search, no threshold; the default
      solver kept apart from the rest of loopmarket (item 2). Built
      (boundary B3 in loopmarket).
  16. loopmarket: matching and clearing refuse an offer whose registry or
      contract major differs from the installed ontodag's (item 4).
      Built.
  17. loopmarket: the fold re-checks every clearing book's loops, and
      where a chain is configured only on-chain fills hide an offer
      (item 9). Built; building it raised question 25, decided A: on a
      chain, `propose` takes only makers' records, the fold records rival
      loops instead of failing, and `watch` hands off only after a
      finalized beat records the fill. Built.
  18. loopmarket: `cli.py` split by area, with a `Reads` object and a
      `LegRecord` type; built first among loopmarket's items (item 10).
      Built (the settings half in loopmarket 0.15.0).
  19. loopmarket: durations and relative times in ontodag's units (`min`,
      `wk`); a bare `m` or `w` is refused with the fix named (item 11).
      Built.
  20. loopmarket: v1/v2 offers retired (circulator's benchmark and the
      tests move to v4+ first; old records stay readable), `MockClearing`
      renamed `BookClearing` (item 12). Built, circulator's benchmark
      first.
  21. loopmarket: its phase gates rewritten for what they still guard
      (the format freeze gates a public launch, factbond's scored Phase 0
      gates selling insurance from a pool); factbond's plans aligned at
      once (item 17). Done.
  22. `mypip/` untracked and ignored, its prototype `cgagviz.py` moved to
      `experiments/` first (§4). Done.
  23. The review's test suggestions 1–5 and 9, each written before the
      decided item it guards (§7). Done in both repositories.
  24. loopmarket: one key per writer for notices, cures and cases
      (`notice/<loop>/<give>/<writer>` and the like); the fold admits a
      key only from its writer's own book; old keys are not read, a clean
      break (item 23, question 26). Built.
  25. loopmarket: a statement's deposit comes from whoever stands behind
      it, its subject or its issuer (read so that a dentist may back an
      attestation about himself, as the gate's solo form does), step 6
      counts only what the escrow has free, and the clearing reserves the
      floor per relying leg, as D1 says (item 24, question 27). Built.

- Places (questions 29 and 30, decided 2026-10-11): a named place is
  declared (`in(paris)`) and gets no geometry in the core; a `geo` value is
  a rectangle in degrees with exact bounds, its longitude arc less than
  half the circle or all of it (a query may be any width); a position is
  the rectangle its written precision covers; `geo(48.8584,2.2945±500m)` is
  500 m either way, turned into bounds once by a fixed rule and rounded
  outwards; geohash names go, a registry major; unions of rectangles later
  (DIMENSIONS.md §22; the poles are a known limit there). Another body is
  another head of the rectangle kind, `±` on `geo` only for now (question
  33, decided A). Built on main (contract 0.7, registry 5.0, prelude 5),
  and in loopmarket on its branch `ontodag-0.32`.
- Relative times (question 31, decided A on 2026-10-11, without a
  refusal step): `today`, `tomorrow`, `now` and `+N`/`-N` in ontodag's
  duration units are taken in `time(...)` only where a person or an agent
  types (the `odag` command, the agent tool, the web console,
  `surface.elaborate(..., now=)`), turned into absolute UTC with the clock
  or the `now` setting; the core and every replay never see them; `today`
  is the UTC day; `..` keeps ontodag's open end, and `loop` takes that
  meaning (DIMENSIONS.md §22). Built on main (surface 0.2, the `now`
  setting).
- Negative values (question 32, decided A on 2026-10-11): a linear head
  declared a position (by a marker node, as a head is pinned to a family)
  takes negative values, as `altitude` will in core; a value's meaning
  stays computable from its name, an open lower end stays zero (so
  `..-120m` is refused as empty), and counts and sizes keep their own
  refusals (DIMENSIONS.md §22). Floors are named parts of their building
  (core's `floor`, local labels), with no number head for now. Built
  on main (registry 4.5); `altitude` as a head is ontodag-core's.

## Bee integration status

- The node: the light node Swarm Desktop made (overlay `bd5da217…`), at
  `localhost:1633` on Gnosis mainnet, run since 2026-10-15 by Bee 2.8.3
  (a security release) from the `bee` package's `/usr/bin/bee` with
  Swarm Desktop's own config: `bee start --config "~/.local/share/Swarm
  Desktop/config.yaml"`, log in `~/bee-logs/`. Peter's choice: Swarm
  Desktop's bundled Bee (2.8.2) is left as it is, and Desktop stays
  closed, since it would start that Bee on the same data. After a
  reboot the node must be started again that way. The package's own
  service (`bee.service`, a separate empty node in `/var/lib/bee`) is
  disabled: enabled, it took port 1633 when Desktop restarted. A cold
  backup of the 2.8.2 data is in `~/bee-backups/`. Another node manager
  can hold the same port, so `curl /health`, `/addresses` and `/stamps`
  before believing anything about a batch.
- Every batch, its size, duration and contents: `../STAMPS.md` (keep it
  current with each purchase and each upload worth keeping).
- The batch: `c931c8a5…`, depth 22, TTL 26.5 days on 2026-10-14 (about
  2026-11-09; the date moves with the storage price). Buy,
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
- Swarm Desktop sets `cors-allowed-origins: '*'` without `restricted`, so
  any website open on this laptop can reach the node's API and its
  batches (BROWSER.md §14.2).
- Not yet tested on a real node: postage expiry and garbage collection
  (they need a batch nobody minds losing).
- Last run: 2026-10-15, on Bee 2.8.3 with the day's releases: swarmfs's
  live tests (its ACT round trip once its own test was fixed),
  recordstore's whole suite live (224 passed, 2 skipped), ontodag's two
  Bee tests, loopmarket's three live tests, and both page checks with
  publishing all passed; the pages' timings were back to 2026-10-13's.
  Before it, 2026-10-11, after the 0.32.0 releases: core and the ten
  domain packs republished keyless (prelude 5 re-pinned their roots),
  every root equal to its pinned `SWARM_GOLDEN_ROOTS` entry, retrievable,
  and read back by its root alone to the identical root; then ontodag's
  two gated tests (48 s) and loopmarket's three live tests (5 min, places
  as rectangles for the first time on a real node) passed. Then, through
  `api.gateway.ethswarm.org`, a clean reader with only released packages
  (recordstore 0.22.3 no longer asks a reader for a batch) folded a
  maker's offer announced on Gnosis from the chain key (one standing
  announcement per owner: afterwards the offer was withdrawn and the
  key's v5-gate clearing book re-announced; on Peter's word that
  announcement was then retracted, tx `41b3c97d…`, so a fresh fold no
  longer lists its old loops as rejected, and only the test maker's book
  stands). Then two machines: Peter's second laptop, with its own Bee
  node (`74f7e74f…`), folded a test maker's announced offer to the same
  book root as this laptop's reader, byte for byte; loopmarket's P1 launch
  item passes. Every run since July, with what each taught, is in the
  journal.

## State (2026-10-15)

- **Reminder for Peter, due before 2026-11-01:** the batch `c931c8a5…`
  expires around 2026-11-09 and takes with it the packs, their cone
  summaries, both read-only pages and the shared Pyodide. Decide what to
  keep and on which batch (`../STAMPS.md`; Pyodide alone was decided D on
  2026-10-12: no batch of its own for now). Raise it at the start of any
  session from 2026-10-25 on.
- Released 2026-10-15 on Peter's word, each verified from PyPI: swarmfs
  0.15.0, then recordstore 0.24.0, then ontodag 0.33.1 (question 47's
  upload levels; ontodag's floors `recordstore>=0.24.0` and
  `swarmfs[feeds]>=0.15.0`; every workflow job green, the downstream gate
  included; `release_smoke.py --pypi` 28/28; a fresh `ontodag[swarm]`
  resolves to both). Unchanged: loopmarket 0.17.1, ontodag-fs 0.9.0.
- On main, not released (2026-10-15): registry 6.0 (question 50) and
  when and where photos were taken (question 49's step 1). A release is
  Peter's word; with it loopmarket's branch `ontodag-0.34` merges (its
  floor to `ontodag>=0.34.0`), its live offers are re-posted under
  registry major 6 (the Rome offer `75337293…`, and the page maker's
  book is empty), and the packs' cone summaries, made under registry 5
  and so not used by 6, are republished.
- Released 2026-10-14 on Peter's word, each verified from PyPI:
  recordstore 0.23.0 (`get_many`, and an unreachable trie node read as
  unavailable), then ontodag 0.33.0 (`odag folder` and `odag file`,
  suggestions with core's WordNet words, the organiser page; floor
  recordstore>=0.23.0; every workflow job green, the downstream gate
  included; `release_smoke.py --pypi` 28/28), then ontodag-fs 0.9.0
  (`>=0.33.0,<0.34.0`; its first publish run met PyPI's index lag and
  passed on a rerun). The first 0.33.0 tag failed CI on a browser test
  that expected the error recordstore 0.23 now wraps (this laptop had
  recordstore 0.22.2), fixed and tagged again before anything was
  published. Unchanged: swarmfs 0.14.0, loopmarket 0.17.1.
- Released 2026-10-11 on Peter's word, each verified from PyPI: ontodag
  0.32.0 (contract 0.7, registry 5.0, prelude 5, surface 0.2: questions
  29–33, geo as rectangles, signed values, relative times; every workflow
  job green, the downstream gate included; `release_smoke.py --pypi`
  27/27), loopmarket 0.16.0 (its `ontodag-0.32` branch merged before
  ontodag's tag; floor `ontodag>=0.32.0`; both examples clear from the
  PyPI install), ontodag-fs 0.8.0 (`>=0.32.0,<0.33.0`), then recordstore
  0.22.3 (a store that only reads never asks for a postage batch, found
  reading through the public gateway) and loopmarket 0.16.1 (a missing
  extra is one line, not a traceback), then loopmarket 0.17.0 (one-line
  install script, `loop setup`, `loop categories`, the registry on Gnosis
  read by default; its questions 34–36; installed from PyPI by the script
  in fresh homes, with and without a node), and loopmarket 0.17.1 (`loop
retract`). Unchanged: swarmfs 0.14.0. The packs whose Swarm roots
  prelude 5 re-pinned (core and the ten domain packs) are republished
  (Bee integration status).
- categor.io's live site runs its main (ba92cf9, updated 2026-10-11):
  ontodag 0.32 (floor `ontodag>=0.32.0`). Sharing from a store made
  before 0.30 declares the audience head alone, since merging prelude 5
  into a store whose `geo` is a prefix head is refused; old stores keep
  their own vocabulary, new ones get prelude 5. circulator's main writes v4 offers (its CI has been red
  since 2026-09-21 on a test comparing its own copy of the baseline).
- On Swarm: the Freedom page (`demo/freedom/`): since 2026-10-13 the organiser (§17),
  which also publishes your store through a node under a key file (§16)
  and helps a person save where they want (§14.1), `bzz://edbd8713…`
  behind `ontodag.gwei` and `ontodag.eth` (feed update 9, 2026-10-15 on
  Peter's word: the 0.33.1 release with whole-blob reads; before it
  `480d23a7…`); loopmarket's market page (`browser/`,
  `bzz://56f9ce1b…` behind `loopmarket.gwei` and `loopmarket.eth`; both load one shared Pyodide;
  a version that also makes, publishes and withdraws your offers and
  announces your book, signing with this page's `publish.js`,
  `bzz://adf2e955…`, not behind the names until Peter has tried it; it
  announced a book live on 2026-10-14, loopmarket's BROWSER.md §5c).
  Question 47 (the redundancy level, BROWSER.md §13) is decided C and
  released (swarmfs 0.15.0, recordstore 0.24.0, ontodag 0.33.1, the page's
  update 8). Both pages run in real Freedom
  Browser and through the public gateway (BROWSER.md §13).
- When Freedom 0.8.8 is released: turn the file pickers on by default in
  Freedom in both pages (`pickers:` in `demo/freedom/app.js` and
  loopmarket's `browser/app.js`), then a feed update on Peter's word
  (question 48, decided B; BROWSER.md §14.1). Watch
  solardev-xyz/freedom-browser's releases.
- ontodag issue #13 (opening a store at a chosen residency) belongs on
  `Store`.
- Watch coincurve on Python 3.14 (loopmarket's CLAUDE.md, "Upstream to
  watch"): until a release supports 3.14, the `swarm` extra here and
  loopmarket's `swarm`/`sig` do not install on Ubuntu 26.04's Python;
  `uv tool install --python 3.12` is the workaround, and we keep coincurve.
- Decided and built while Peter was away (2026-10-10): questions 11–23.
  Records in `docs/plans/REVIEW_2026-10.md` §8; the night's story in
  `docs/plans/JOURNAL.md`. Questions 24–27, decided with Peter the same
  day, are built in both repositories (the journal's next entry).

## Open questions for Peter

None open now: questions 37 to 50 are decided, and question 47 is
released. The smaller open points are in
BROWSER.md §17; next for the organiser: encrypted Publish (question 42,
step 2 of question 49's order), then the choice at sharing and public
versions (step 3), and the list of hashes kept between visits (question
41).
Polygons and unions of rectangles: not now. None open from the review: questions 24–28 are decided and built
(`docs/plans/REVIEW_2026-10.md` items 21–25).

Older, not urgent: a publisher key for the packs on
Swarm (published without one, so no feed yet; PACKS.md); the browser's
open points (BROWSER.md §11: which message the wallet signs, dappdata as
the shared layer, which clients first); ontodag-core's doubtful list
(its UPPER.md §9).

Parked behind a discussion or a tripwire (in `docs/plans/`, some only in
the journal): the
surface layer (and ROLES §9 step 6), bundles (BINDING), an ordinal kind and
the top ontology (EVOLUTION), computed values, a contract clause for
self-declared truncation, MCP reads through overlays, a query log outside
the web app, the postage-expiry experiment, and how an arbitrator gets
evidence from third parties such as witnesses and experts (Peter,
2026-10-10, raised with question 28: probably off chain; factbond's and
loopmarket's).

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
