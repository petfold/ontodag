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
  and pack contents. `docs/PROVENANCE.md`, `docs/PACKS.md`,
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
