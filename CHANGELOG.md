# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/); versions follow
[Semantic Versioning](https://semver.org/) (0.x: minor bumps may change
behavior; the **unit registry** carries its own MAJOR.MINOR compatibility
contract, noted per release).

Back-filled 2026-08-01 from the release history. Versions 0.8.0 and 0.9.0
were completed and tagged in the code but never reached PyPI (the tag-driven
publish workflow was bypassed and the manual uploads never ran); their
features first shipped to users in 0.10.0. They are kept as entries because
the version numbers appear in commit history and docs.

## [Unreleased]

### Added

- **`odag excerpt FILE [CAT…]`** — `export` scoped to a query: writes just
  that answer, keeping the edges among the answers, in any supported format.
  Both halves already existed in `dag.py` (`intersection_dag` is the live
  *view*, `copy_subdag` the materialized *excerpt*) and the web surface
  already exposed the query-scoped exports; the CLI had only whole-DAG ones.
  Query terms are deliberately **not** added as nodes — unlike the web
  *picture*, which may invent one to draw a constraint it then discards — so
  an excerpt stays importable without filing the constraint as knowledge.
  Answers with no parent inside the answer hang under the root, so the
  imported store sees them. With no categories the result is byte-identical
  to `export`.
- **`odag visualize [CAT…]`** — the drawn twin: with categories it renders
  just that query's answer, with the query *terms* drawn above the answers of
  their own disjunct. That is the deliberate difference from `excerpt`: a
  picture is discarded, so inventing a node to show the constraint costs
  nothing and is the only way to see a term the store has no node for (a
  virtual `weight(..5kg)`); a file that gets imported back must not carry it.
  The shaping moved out of the web app into `ontodag.viz.query_picture`, so
  the CLI and the web query image cannot drift into drawing different
  pictures of one answer.

### Fixed

- **`odag visualize` with no `--out` raised `AttributeError`** (since 0.12.0,
  when `rs:` stores removed `Session.path`). It now names the image after the
  store, for every backend spelling. No test had ever omitted `--out`.

## [0.15.0] — 2026-08-04

### Fixed

- **Transitive reduction is now complete, making stored form — and the
  multi-writer merge — order-independent.** `add_edge` pruned only edges
  from ancestors of the new parent into the new child; an existing edge
  whose only witness path runs *through* the new edge (`p→B` bypassed by
  adding `p→Z` with `Z⇝B`, computed hops included) was kept. Same
  knowledge could therefore hash to two different roots depending on
  insertion order, and two writers syncing each other's roots could land
  on *different* roots whenever the redundancy spanned them (an I7
  violation, verified before the fix). The prune now covers the full
  redundancy rectangle; verified against a brute-force reduction oracle
  over randomized replay orders, plus a seeded two-writer commutativity
  fuzz. All shipped golden roots (prelude, packs) are unchanged. A store
  that carries a bug-era non-reduced shape keeps its bytes (hydration is
  verbatim) and re-canonicalizes under an explicit `ontodag.migrate`
  replay — after this fix, re-filing the same knowledge yields the
  reduced root.
- **`migrate_record_store` crashed on every real store** (it replayed
  the store's own `*` root record back into `put`). Fixed and now
  tested; it is the sanctioned re-canonicalization path above.
- **A peer's concurrent delete no longer silently wins in the store.**
  Saving onto a moved head that deleted a record this session still
  holds used to stage nothing for it — the union (grow-only: a removal
  loses to a concurrent holder, same stance as remove-loses-to-readd)
  kept the node in memory while the committed root lost it. The fold now
  rebases the commit baseline onto the head it commits onto, so the
  surviving copy is re-staged.

### Changed

- **Merging a peer costs the divergence, never the store.**
  `EagerOntoDAG.sync` no longer hydrates the peer's entire root: the
  fold is driven by `RecordStore.diff` between the dag's own lineage and
  the peer's root (`merge_delta`), reading only the records that moved
  plus the ancestor cones the replayed edges touch. Union semantics are
  unchanged. This is the first consumer of recordstore's `diff`.

### Added

- **`SparseOntoDAG.sync`** — the partially-resident multi-writer fold.
  The same diff-driven union, expanding only what it touches, so a
  writer resident on a handful of records can fold a peer's divergence
  into a large store without hydrating it. The store handle must sit at
  the writer's own lineage (folding through a handle rebound to another
  root is refused with a teaching error — that flow belongs to
  `EagerOntoDAG`). Peer payloads survive the fold.

- **`swarm:` stores are local-first** (recordstore 0.19's
  `local_first_store`): commits land in a store directory under
  `~/.ontodag` instantly — the node being down no longer blocks a save —
  and a background syncer pushes them to Swarm and confirms
  peer-to-peer. The store is opened in **transient windows, never
  held**: the hydrated in-memory DAG serves the session, `load()` and
  `save()` each open-and-close (releasing the single-writer lock), so
  odag, a long-lived odag-fs mount, and the MCP server interleave
  freely — brief overlaps retry on `StoreLocked` for up to 5 s, and
  the `odag index` / MCP provenance stores get the same
  window discipline. Saving onto a head another writer moved **folds
  the moved head in with the CRDT DAG merge** (invariant I7 —
  commutative, idempotent union via `EagerOntoDAG.sync`), never
  last-writer-wins and never locking: same-node concurrent edits union
  their parents. The dag tracks `base_root` — the root of its own
  hydrate/commit lineage — and merges only when the head moved past
  it, so replace-shaped flows (`odag import`) still supersede rather
  than merge back what they replaced. `save()` adds a best-effort sync barrier (60 s)
  and prints a note when the commit will sync on a later run instead. With
  a signer the head publishes to the Swarm feed only after network
  confirmation, so the feed never points readers at content the network
  cannot serve yet. Pre-local-first stores migrate automatically: the
  old `NAME.root` head seeds the new store directory's `HEAD` on first
  open, and reads heal lazily from Swarm. The `swarm` extra is now
  `recordstore[swarm-only,local-first-swarm]>=0.19.0`.

## [0.14.1] — 2026-08-04

### Changed

- **Docs**: `docs/recordstore-interface.md` is now only the consumer-side
  view — recordstore (0.18.2+) and swarmfs (0.7.1+) ship their own
  authoritative `docs/REFERENCE.md`, each pinned against its code by a
  `tests/test_reference.py` (the pattern this repo's REFERENCE.md
  started), so the full-API half of the manual-sync burden is retired.
  The doc index, REFERENCE.md's install section, and CLAUDE.md point
  upstream accordingly. No code change.

## [0.14.0] — 2026-08-03

### Fixed

- **`odag help` works with the node down.** The store now opens lazily — on
  the first command that touches it, under the usual one-line error contract
  — instead of at startup. Before this, a configured `swarm:` store with an
  unreachable node made *every* invocation fail, including `odag help` (what
  you type to find the way out) and `odag set store <local>` (the way out
  itself). `set store` still validates eagerly at set time, and a failed
  switch still leaves the session on its old store. The help text also now
  ends with the documentation URL.

## [0.13.0] — 2026-08-03

### Added

- **A Reference Manual, and a documentation map.** `docs/REFERENCE.md` is the
  compact lookup side of the docs (every command, setting, store spec, kind,
  REST endpoint, MCP tool, extra and pack, definition-first) — and its tables
  are **pinned to the code** by `tests/test_reference.py`, so a feature that
  isn't referenced fails the suite (the pin caught its first omission,
  `get_by_dag`, on its first run). The User Guide stays the tutorial and
  drops the tables it had absorbed. `docs/README.md` maps every document's
  single job, and the discussion drafts and direction papers (ROADMAP,
  BINDING, EVOLUTION, PACKS, SURFACE_LAYER, DATABASE_DIRECTION, and friends)
  moved to **`docs/plans/`** — nothing in that folder is shipped.

- **The count kind (registry 4.1, prelude v3).** A fifth dimension kind,
  `count-dimension`: whole numbers ≥ 1 of discrete things — `count(3)`,
  `count(2..)` ("at least two"), `count(2dz)` (= 24). Three teaching
  refusals: `count(0)` (a zero multiplicity is an absence claim, which an
  open-world store cannot assert), fractions (continuous stuff has
  dimensional heads), and unit-bearing values. The floor is semantic:
  `count(..5) ⊑ count(1..)` is a theorem, and `count(1..)` coincides with
  the coordinate being absent. The prelude declares the kind and an
  everyday `count` head (v3, golden root re-pinned). Registry minor 4.0 →
  4.1: additive, interoperates with 4.0 stores; counts share linear's
  space tag so a bare-number linear head can be re-declared under the
  count kind without a stored name changing. UNITS.md §11 is the design
  record; the multiplicity use case (bouquets: 2 red roses as
  `part`-style lines) is BINDING.md §5.

- **Ranges as honest uncertainty — documented.** A stored range is a claim
  about bounds, and the machinery composes correctly around that reading:
  `is_below` answers certain matches fail-closed, `get_overlapping` answers
  possible ones, narrowing to the exact value later prunes the range edge
  automatically while the old claim stays entailed, and a "correction"
  outside the stated bounds refuses (vagueness is repairable by precision;
  wrongness only by deliberate removal). New guide section with executed
  snippets, including the two limits: ranges are bounds, never probability,
  and overlapping same-head claims are not auto-combined (assert the meet
  yourself).

- **Help getting a node.** A "Getting a node" table in the User Guide §5.1 —
  Swarm Desktop, Bee on its own, or Freedom Browser's bundled node — and `odag
  swarm` now points at the same three. Freedom runs **Ant** (`antd`,
  Bee-compatible) on port **11633**, so both places name
  `odag set bee_api http://127.0.0.1:11633`: a node that is running while
  `odag` reports nothing at Bee's default 1633 is the one failure that costs
  real time. OntoDAG against Ant is untested and the guide says so.

### Changed

- **`ontodag[all]` now means all** — it installs `swarm` and `web` alongside
  `viz`, `owl` and `store`. It previously covered three of the five, which left
  the one extra this project is most about as the one `[all]` did not deliver.
  The narrow extras are unchanged, the base install stays lean, and `[test]`
  still deliberately excludes `swarm` so CI keeps proving the suite passes when
  Swarm is absent.

## [0.12.0] — 2026-08-03

Signing keys you do not have to handle. `odag set bee_signer generate` makes one
and stores it without ever showing it to you, and the two ways the old path
leaked a key — a world-readable config file, and `odag set` echoing it in full —
are closed.

### Added

- **`odag set bee_signer generate`** — makes a signing key, stores it, and never
  shows it to you. The alternative was telling people to type
  `odag set bee_signer "$(python3 -c 'import secrets; …')"`, which is hostile,
  platform-dependent (a stock Windows has no `openssl`, the usual suggestion),
  and easy to get subtly wrong: a stray character on a paste gives a
  65-character string. `generate` cannot collide with a real value, since a
  signer is always 64 hex characters. It reports the key's last four characters
  and where it went **on stderr** — `set` is silent on success by convention,
  but a secret you will never be shown again is the one case where silence
  stops you doing the necessary thing, which is backing it up.

  Generating over an existing key is **refused** unless `--force`: the feed's
  address derives from the key, so replacing it strands everyone following the
  old feed at the last root published there, irreversibly if the old key was not
  backed up. That is not something to do as a side effect of a command that
  looks like it sets a preference. It also warns when `BEE_SIGNER` is set in the
  environment, since that outranks the config file and the new key would
  otherwise silently not take effect.

  User Guide §8 now documents key creation, with `generate` as the whole
  procedure and the same three lines on every platform.

### Changed

- **A `bee_signer` you supply by hand is checked when you set it**, not at the
  next command that opens the store — the principle `set` already applied to
  `limit`, extended to the setting where a mistake is least visible. 64 hex
  characters, `0x` prefix optional; anything else is refused with a message
  pointing at `generate`. **Mildly breaking**: a value that is not a well-formed
  key used to be stored happily and fail later, so a script storing junk now
  fails at the point it stores it.

### Fixed

- **The config file is written owner-only, and an existing one is repaired.**
  `~/.ontodag/config` can hold `bee_signer` — a secp256k1 private key that can
  publish a new root to your feed, i.e. change what everyone following your
  ontology sees — and it was written with default permissions, which under a
  typical umask left that key group- and world-readable. It is now created
  `0600` (via `O_CREAT`'s mode, so there is no window where it exists looser),
  and `chmod`ed on every write, which is what repairs a config written by an
  earlier version — the case that matters, since by then the key is already on
  disk. New home directories are created `0700`.
- **`odag set` no longer prints the signer key.** It is the routine "what is
  configured?" command, so what it echoes ends up in scrollback, screen shares
  and captured output — and it printed the full 64-character key, both in the
  all-settings listing and when asked for `bee_signer` alone. Secrets now
  display as `<hidden, ends 1234>`: enough to confirm one is set and to tell two
  apart, without the value. Marked per-setting (`secret=True`) rather than by
  name-matching, so a future credential inherits the behaviour. Display-only —
  the config file remains the place to read the real value from, deliberately
  not a display command.
- **The test suite no longer fails when `BEE_API` is exported.**
  `TestSetCommand` wrote `bee_api` to the config and asserted on reading it
  back, but settings resolve flag > environment > config > default, so an
  exported `BEE_API` correctly won and the assertion was reading the wrong
  layer. Since the User Guide's setup step tells you to export exactly that
  variable, the suite went red for anyone who had followed the instructions —
  and CI never saw it, having no such variable. The class now owns its
  environment in `setUp`/`tearDown`, as the neighbouring swarm classes already
  did.

## [0.11.0] — 2026-08-03

The install-and-try-it release. `pip install ontodag` no longer pulls 31 MB of
compiled extensions and Java reasoners it never invokes, `rs:PATH` gives the
canonical roots and snapshots on an ordinary directory with no node at all, and
`odag swarm` walks the Swarm setup in dependency order when you do want one.
Plus the native `.od` format learning to carry node metadata, which it should
always have done — without it the text format could not represent a DAG that
the recordstore backend can.

### Added

- **`rs:PATH` — a content-addressed store on ordinary disk.** The rung that
  was missing between a text file and Swarm. Canonical roots, immutable
  snapshots, `is_below` certificates and multi-writer `sync` were all
  reachable only through a Bee node, so seeing what OntoDAG is *for* meant
  first funding a wallet and buying postage. The same semantics now run on
  a directory, which makes `swarm:NAME` a change of backend rather than a
  new concept. `odag index` accepts it too.
- **`odag swarm`** — walks the Swarm setup in dependency order (extra
  installed → node reachable → healthy → chain synced → wallet funded →
  usable postage batch) and stops at the first failure with the command
  that fixes it, including the two waits nobody expects: a fresh node needs
  ~8 minutes before its chainstate answers, and a bought batch needs ~70
  seconds before it is usable. Uses only the standard library, so it still
  runs when the swarm extra is the missing piece. When the answer is "not
  today", it points at `rs:PATH` instead.
- **`ontodag.browser`** — `JsBytesStore`, `JsFeedPointer` and
  `LocalStorageBytesStore`: the four methods recordstore needs, implemented
  over a JavaScript bridge, so OntoDAG can run in Pyodide against Swarm
  through bee-js without a fork. **Written, not yet run in a browser** —
  the logic is tested against a fake bridge (including that a
  JS-backed store computes the same canonical root as an on-disk one),
  but no Pyodide or bee-js has touched it. The module docstring records
  the one real obstacle: `BytesStore` is synchronous and every browser
  network API is not, so the caller supplies a bridge — a web worker with
  `Atomics.wait`, or JSPI's `run_sync`. Implementation record and
  sequencing: `docs/plans/BROWSER.md`.
- **`ontodag[viz]`, `[owl]`, `[all]` extras** — see Changed.
- **A name-consumer corpus** (`tests/test_name_consumers.py`). One list of
  hazardous names — spaces, `+ & # | , : " \`, unicode, a leading dash —
  plus the canonical names the system generates itself, pushed through
  every surface a name flows out through: DOT (source *and* a real
  `dot` render), the native store, OWL, Manchester, the surface renderer,
  and REST/URL. The 0.10.1 post-mortem's conclusion in executable form: a
  change to the canonical-name grammar is a cross-cutting change, and the
  fan-out needs to be written down somewhere that fails.
- **The publish workflow works again.** `.github/workflows/publish.yml`
  fires on `v*` tags but had not run since v0.7.0, and would have
  red-failed on any version already uploaded by hand. It now has
  `skip-existing`, plus three things it never had: a check that the tag
  matches `pyproject`'s version (otherwise a `v0.10.2` tag quietly
  publishes 0.10.1, and PyPI never gives a version back), a smoke test of
  the built wheel before upload, and a job that re-runs the smoke test
  against what PyPI actually serves afterwards. Tagging is the preferred
  release path again.
- **A release smoke script** (`scripts/release_smoke.py`). Installs the
  built wheel — or a published version, with `--pypi VERSION` — into a
  throwaway virtualenv and drives `odag` as a new user would: prelude,
  typed values, query, computed containment, the empty query, the cap,
  `canon`, **visualize**, export and re-import. Run it before publishing;
  run it again after, against PyPI. It fails on the published 0.10.0,
  which is the point.

### Changed

- **The base install has no third-party dependencies.** `pip install
  ontodag` previously pulled 31 MB — `owlready2` alone is 28 MB plus a
  compiled extension and two bundled Java OWL reasoners that OntoDAG never
  invokes — to deliver a 648 KB package that used none of it. Worse,
  owlready2 ships sdist-only, so installing OntoDAG required a C toolchain
  and could not work under Pyodide at all, where micropip cannot build
  sdists. That single line blocked the in-browser story the roadmap
  describes.

  `graphviz`/`Pillow` are now the **`viz`** extra and `owlready2` the
  **`owl`** extra, with **`all`** for both; `web` and `swarm` are unchanged
  in spirit and pull what they need.

  `recordstore` stays a base dependency, and the criterion it passes is
  worth stating: 184 KB, pure Python, no compiled extension, no
  dependencies of its own. It costs nothing an embedded or browser target
  cares about, and it is what makes canonical roots, snapshots,
  certificates and `odag-mcp` work on a plain install instead of hiding
  behind a flag. A dependency that changes what the package *is* by
  default earns its place; one that adds 28 MB of Java reasoners for a
  file format does not.

  **This is mildly breaking**: code doing `pip install ontodag` and then
  using OWL, rendering or a concrete record store now needs the matching
  extra. Each of those paths raises an error naming the extra to install
  rather than a `ModuleNotFoundError` naming a package — including
  `odag-mcp`, which needs `[store]` even against a *file* store, because
  every answer it gives cites a root and a text file has none.

  What still works with nothing installed is more than it sounds: the DAG,
  the CLI, typed values and their arithmetic, and a **persistent** store —
  the native `.od` file is canonical line-oriented text, so a bare install
  is not an in-memory toy.
- **`OntoDAGVisualizer` moved from `ontodag.dag` to `ontodag.viz`.**
  Rendering is an optional consumer of a DAG, not part of one, and keeping
  it in the core module is what made the core look like it needed a
  renderer. `from ontodag.dag import OntoDAGVisualizer` still works — the
  old module forwards it — and `ontodag.OntoDAGVisualizer` is unchanged.

### Fixed

- **The native `.od` store persists node metadata.** It did not, and dropped
  it on save with no warning and no error, so the text format could not
  represent a DAG that the recordstore backend can: `_record_for` puts `meta`
  into the record and therefore into the canonical root, while `_save_native`
  wrote names and edges only. The measurable consequence was that **a
  save-and-load changed the root** — the same knowledge hashing to two
  different values depending on which backend it travelled through — and any
  consumer keeping data in metadata lost it silently. ontodag-fs is one: it
  marks objects with `metadata["object"]` and carries display filenames in
  `metadata["label"]`, so browsing a file store showed no files at all, and
  because empty extents also suppress the concept directories, a store with a
  hundred objects in it presented as an empty one.

  Metadata now rides on a `#:meta <name> <json>` line per annotated node.
  Riding on a *comment* is what makes the extension safe in both directions:
  every already-released reader skips `#` lines, so it reads a
  metadata-bearing file exactly as before — edges only, nothing corrupted —
  whereas putting the annotation on the node's own line would have older
  readers take the JSON for a list of parent names and invent nodes from it.
  The edge grammar is unchanged, so the header stays `v1` and metadata is
  optional enrichment rather than a new version. Values are JSON with sorted
  keys, so the file stays byte-stable for diffing, and JSON escaping is what
  lets a display label contain a newline without splitting the record — the
  one hazard a metadata value has that a node name does not. A malformed
  annotation now raises with the file and line rather than being skipped;
  silently ignoring it would be the same data loss in a new place.
  `tests/test_cli.py::TestNativeStoreMetadata` covers the round trip,
  canonicality, both compatibility directions, and the root-preservation
  property; the name-consumer corpus now runs its whole hazard list through
  metadata values as well as node names.

  Not fixed here: `payload` is persisted in records too and the text format
  still drops it. It lives on `EagerOntoDAG`, not on the node, so a plain
  `OntoDAG` has none to write — worth a separate pass rather than a partial
  one alongside this.
- **`odag swarm` no longer reports a healthy node as unreachable.** The
  reachability probe asked for `/` and parsed the reply as JSON, but Bee serves
  its root as `text/plain` ("Ethereum Swarm Bee"), so a working node raised
  `JSONDecodeError` and was reported as "nothing answering at …". Since the
  walk stops at the first failure, that ended the diagnosis and advised
  starting a node that was already running — the one thing a diagnostic must
  never do. Reachability is now asked of `/health`, which answers JSON and
  whose 200 proves reachability anyway, so two checks collapse into one honest
  one. Caught only because the fix landed in the same session as a live node:
  the regression test drives a real socket serving `text/plain` at `/`, since
  anything that stubs the fetch helper shares the assumption that was wrong.
- **The native store reads and writes UTF-8 explicitly** rather than relying
  on the platform's default encoding, which made a store containing a
  non-ASCII name unloadable on any system whose default is not UTF-8 — the
  Windows tier the platform matrix claims core support for.
- **OWL export refuses names it cannot carry instead of writing a corrupt
  file.** A node name becomes the class IRI, written straight into an XML
  attribute, so a `"` in a name closed the attribute early and produced a
  file that was not well-formed XML — the export reported success and the
  damage surfaced only when something read it back. `"` is illegal in an
  IRI, so there is nothing to escape; the export now names the offending
  entries and points at Manchester or the native format, which carry any
  name. Found by the corpus above on its first run.

### Notes

- Registry unchanged at **4.0**; no migration.
- The base-install change is **mildly breaking**: code that did
  `pip install ontodag` and then used OWL, rendering, or a concrete record
  store now needs `[owl]`, `[viz]` or `[store]`. Each of those paths raises an
  error naming the extra rather than a bare `ModuleNotFoundError`.
- `.od` stores written by this version carry `#:meta` lines. Older readers skip
  them as comments and see the same edges they always did, so the files stay
  readable by 0.10.x — without the metadata, exactly as before.

## [0.10.1] — 2026-08-02

A bug-fix release. **0.10.0 could not draw any DAG containing a typed
date** — the one published release with the fault, though it had been in
the code since calendar dimensions landed in 0.8.0 (never published).

### Fixed

- **Visualization of parametric time values.** Canonical names like
  `time(2026-08-15T00:00:00Z..2026-08-15T23:59:59Z)` were used as DOT node
  *identifiers*, where `:` is the port separator; the graphviz package's
  quoting split them and the render died with a syntax error. So
  `odag visualize`, `OntoDAGVisualizer.generate_image`, and the DOT and
  LaTeX exports all failed on any store holding a date. Names now live in
  labels and identifiers are synthetic (`n0`, `n1`, …), which makes every
  name renderable whatever a future canonical form contains rather than
  fixing this one character. Ids follow the DAG's deterministic iteration
  order, so DOT output stays diffable. Linear dimensions (`weight(3kg)`)
  were never affected — timestamps are the only canonical names with a
  colon in them.
- **The web app** (not shipped in the wheel; affects checkouts): session
  state is created on demand, so the REST API works without a browser
  having loaded the page first; `/market` no longer 500s in a session that
  used the main page; the query picture is built from `get()` instead of a
  name-intersection, so virtual parametric terms are no longer silently
  dropped from it (`Japan,weight(..5kg)` used to draw a picture that
  contradicted its own result list) and `|` union is drawn as two
  branches; the UI URL-encodes query terms, so a name containing `+`, `&`
  or `#` queries what you typed.

### Added

- **The empty query is the universe.** `get([])` returns everything rather
  than raising: an intersection of no cones is unconstrained. `odag get`,
  `odag list` and `odag get '*'` are now one code path, and the REST and
  MCP query surfaces agree. A dangling `or` remains an error.
- **`odag count [CAT...]`** — the same queries as one number, never
  capped.
- **A terminal display cap.** Results stop at 50 lines when stdout is a
  terminal, with the withheld count on stderr; pipes are never capped, so
  `odag get | wc -l` still counts everything. `-n N` / `-n 0` override.
  MCP deliberately differs: no default cap, an explicit `limit`, and a
  `truncated` flag beside a `count` that always reports the complete size.
- **One settings table.** All six settings (`store`, `limit`, `render`,
  `bee_api`, `bee_batch`, `bee_signer`) resolve by one rule — flag >
  environment > config file > default — where three regimes existed
  before. `auto` is a real value meaning "decide from the tty", and bad
  values are refused at `set` time.

### Notes

- Registry unchanged at **4.0**; no migration.
- First test coverage of any rendering endpoint (`TestPicturesAndExports`,
  `TestVisualizerRendersEveryName`, `TestQueryPictureAgreesWithTheAnswer`)
  — the absence of it is why the DOT bug survived a release.

## [0.10.0] — 2026-08-01

The agents-first release, part 2 (writes + vocabulary), plus the full unit
system. **Registry 4.0** (see migration notes below).

### Added

- **Provenance store** (`ontodag.provenance`): signed, content-addressed
  assertion/retraction/endorsement/binding records at claim grain
  (subjects are claims like `sub ⊑ sup`, not edges), in a sibling store
  beside the knowledge — attribution never contaminates the canonical
  root. Per-writer stores fold with a conflict-free `union`.
- **MCP write surface** (`odag-mcp --write`): `propose_put`/`put`,
  `propose_remove`/`remove` with compare-and-confirm proposal tokens
  (canonical echo of what will be stored, refused if the store moved),
  every accepted write emitting signed provenance records; `endorse`/
  `retract` speech acts; `review` — a claim's full audit view with
  signature verification and reader-side trust policy ("claims merge,
  acceptance is policy").
- **The standard prelude** (`odag prelude`, `ontodag.prelude`): the
  everyday dimension declarations (weight, length, duration, time, geo,
  size, area, volume, speed, pressure, temperature, energy) adopted by
  explicit idempotent merge; golden-root pinned.
- **The full unit system** (registry 3.0→3.1, docs/UNITS.md): canonical
  values are reduced rationals of the SI coherent anchor — `weight(3kg)`,
  `weight(1/2kg)`, the shaku's `length(10/33m)` — nothing rounds, nothing
  is refused for precision; ~35 measurement families, 247 built-in
  suffixes (SI, customary incl. psi/oz/gal, digital incl. TiB/Gbps/FLOPS);
  psi↔bar in one lattice. `ontodag.migrate` replays older stores onto the
  new canonical names.
- **Graph-declared units** (registry 3.2): `unit(firkin=9igal)` /
  `unit-family(NAME)` declaration nodes under `unit-declaration` —
  vocabulary is data that merges and travels with the store; conflicts
  and unresolvable definitions refuse loudly.
- **Unit packs** (`odag pack`, `ontodag.packs`): shipped vocabularies
  adopted by merge, golden-root pinned — `crypto-core` (BTC/ETH/BZZ/xBZZ/
  DAI/xDAI + sat/Gwei/wei/PLUR), `crypto-majors` (top-20 coins with
  chain-canonical denominations), `stablecoins` (incl. LUSD),
  `fiat-iso4217` (~150 national currencies). Each currency is its own
  family: exchange rates, pegs and bridges are never arithmetic
  (BZZ vs xBZZ refuses). The built-in table holds only what physics
  fixes; everything market-shaped is a pack.
- **Affine temperatures** (registry 4.0): `24C`, `-40F`, `0C..100C` parse
  exactly onto the still-canonical kelvin scale; `-40C` and `-40F` are
  one stored name; below absolute zero refuses. Bare `C`/`F` mean
  Celsius/Fahrenheit context-free; `degC`/`degF` are input aliases;
  rendering emits `C`/`F`.
- **Pack-aware teaching errors**: `price(5USD)` before adoption refuses
  with the exact remedy (`odag pack fiat-iso4217`), for value parsing and
  declaration bases alike.
- `docs/UNIT_TABLE.md`: the generated full listing of built-in suffixes
  and pack contents. `docs/PROVENANCE.md`, `docs/plans/PACKS.md`,
  `docs/UNITS.md` design records; User Guide Quick Start.

### Changed

- **Registry major: 3.x → 4.0.** Two canonical anchors changed — the bare
  coulomb and farad are now spelled `coulomb`/`farad` (all prefixed forms
  `mC`/`uF`/`mAh`… unchanged) — and bare `C`/`F` changed meaning to the
  temperatures. Registry-3 stores carrying bare-`C`/`F` values must
  rewrite them to `coulomb`/`farad` spellings before an `ontodag.migrate`
  replay. Registry 3.0 itself renamed the canonical spellings of
  weight/length-class values (`weight(3000000mg)` → `weight(3kg)`);
  `ontodag.migrate` handles that replay.

## [0.9.0] — 2026-08-01 (never published to PyPI; first shipped in 0.10.0)

The agents-first release, part 1 (the trustless read stack).

### Added

- **The contract** (`docs/CONTRACT.md`, v0.1): the written guarantees
  G1–G6 any program may rely on (canonical roots, merge monotonicity,
  determinism, fail-closed `is_below`, convergence, `get_overlapping`
  recall-completeness) with the as-of/root-pinning clause; enforced by
  `tests/test_contract.py`; `ontodag.CONTRACT_VERSION`.
- **Readable output** (`ontodag.surface`): rendering as a pure function
  of the canonical name (`weight(3kg)`, `time(2026)`), the round-trip law
  `elaborate(render(t)) == t`, `odag canon TERM`; CLI pipe rule — output
  is canonical whenever stdout is not a terminal, so `odag get | odag`
  round-trips (`--raw`/`--render` to override).
- **MCP agent surface** (`odag-mcp`, `ontodag.mcp`): stdlib-only MCP
  stdio server — `about`, `query`, `is_below`, `overlapping`, `describe`,
  `canon`; every answer cites its root + contract version; canonical echo
  throughout; `as_of` time travel via snapshot roots.
- **Verifiable `is_below` certificates** (`ontodag.certificates`):
  `prove_below`/`verify_below` — re-execution over authenticated
  fragments; verification needs only the certificate and the 64-hex root,
  no store access, both polarities provable; live on the MCP surface as
  `certify: true`.

### Changed

- recordstore floor raised to **>=0.16.0** (`prove`/`verify_proof`).

## [0.8.0] — 2026-08-01 (never published to PyPI; first shipped in 0.10.0)

### Added

- **`calendar-dimension`**: `time(2026)` means the year, `time(2026-08)`
  the month — reduced precision denotes the whole period, subsumption by
  arithmetic with no stored edges.
- `odag index`: publish cone summaries from the CLI; web stats endpoint.
- `is_below` streams the virtual-bound climb (early exit both ways).

### Changed

- CLI store-open failures obey the error contract (a stopped Bee node
  names the API URL and both escapes, never a traceback; no silent
  fallback between stores).
- Deterministic `topological_sort` (sorted iteration): `odag show` and
  OWL/Manchester exports are byte-stable across runs.
- recordstore floor raised to >=0.14.0; the `swarm` extra declares
  `recordstore[bee,feeds,stamps]` so `batch=auto` works on clean installs.

## [0.7.0] — 2026-07-31

### Added

- **`is_below sub sup`** (CLI `below`/`?`, REST `/dag/below`): Boolean
  fits-within — answered by an upward walk, reflexive, fail-closed on
  unknown terms, decidable from names alone for parametric terms.

## [0.6.0] — 2026-07-31

### Added

- **`SparseOntoDAG`**: the partially-resident writer — full mutation
  semantics over a store fragment, commits staged from a resident-set
  diff (a `put` against a 447-record store costs ~7 fetches).
- **Union queries**: `get_any` (CLI `get A or B`, REST `|`).

## [0.5.0] — 2026-07-31

### Added

- **Multi-writer sync**: `EagerOntoDAG.sync(other_root)` — graph-level
  renormalization implementing the CRDT merge rule; replicas converge to
  byte-identical roots under any gossip order.
- **Published cone summaries** (`ontodag.cones`): a separate index store
  a thin `LazyOntoDAG` reader uses to answer broad queries in a handful
  of fetches (375 → 6 on the benchmark fixture).
- **Signed-feed roots**: `set store swarm:NAME` + a configured signer
  puts the latest ontology root in a signed Swarm feed — a followable,
  publishable address.

## [0.4.0] — 2026-07-30

### Added

- **Parametric dimensions (dimension lattices)**: values like
  `weight(3kg)` and ranges like `weight(..5kg)` are ordinary categories
  whose order is *computed* from the canonical name (containment of
  denotations, exact arithmetic) — never materialized as edges. Kinds:
  `linear-dimension`, `prefix-dimension` (geohash-style codes),
  `dominance-dimension` (does-it-fit tuples). `get_overlapping` for
  possibly-satisfies queries. Design record: `docs/DIMENSIONS.md`.

## [0.3.1] — 2026-07-28

Metadata-only release.

## [0.3.0] — 2026-07-28

### Added

- `merge_published()`: settle "do I already have this?" by root
  comparison before fetching.
- CI: test workflow, publish-on-tag workflow gated on the suite,
  LICENSE, README badges.

### Changed

- recordstore floor raised to >=0.12 (the CLI signer path calls
  `swarm_store()`); the `[swarm]` extra correctly pulls `swarm-bee`.

## [0.2.0] — 2026-07-25

### Added

- **`LazyOntoDAG`**: read-only on-demand reader — querying a published
  store costs the query, not the store (bounded fetches, memoized cones).
- Batched hydration through `RecordStore.items()`.

## [0.1.0] — 2026-07-25

First PyPI release.

### Added

- The `ontodag` package: `OntoDAG` (multi-parent category lattice in
  transitively reduced canonical form; `put`/`get`/`remove`/`merge`;
  invariants I1–I7 under test), the `odag` CLI (Unix-style; native text
  store, OWL/Manchester import/export, `swarm:NAME` backends),
  `EagerOntoDAG` persistence over recordstore (canonical roots:
  same knowledge, one root, any history), Graphviz/DOT/LaTeX export,
  and the Flask web app.
