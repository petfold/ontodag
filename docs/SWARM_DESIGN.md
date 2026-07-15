# Swarm Persistence Design for OntoDAG

Status: `recordstore` implemented and tested (in-memory + fuzz; Bee integration
tests passed once against a `bee dev` 2.7.1 node — HTTP contract only, see the
label in §7). The `dag.py` invariant fixes (I1–I6) and the `SwarmOntoDAG`
adapter (§3/§6 design, `src/ontodag/swarm_adapter.py`, tested against
`MemoryChunkStore` and smoke-tested over the same dev node) are done as of
July 2026. This document is the design rationale; `CLAUDE.md` has operational
instructions and the current task list.

Read this before making architectural changes to `recordstore` or starting the
`SwarmOntoDAG` adapter — it explains *why*, which the code comments don't fully
capture.

## 1. Why persist OntoDAG at all, and why on Swarm

Persisting a data structure durably is completely normal — every database is a
data structure on slow storage (B-trees in Postgres/SQLite, LSM-trees in
RocksDB). What's specific to Swarm is that its storage is *content-addressed
and immutable*: two senses of "persistent" (durable, and
immutable-with-structural-sharing, as in Git or a Merkle Patricia trie)
coincide by construction. That's unusually good for a category graph, because
OntoDAG has a property most graphs lack: **the transitive reduction of a DAG
is unique**, so a correctly-maintained OntoDAG has one canonical form. Content
addressing turns that canonical form into a hash — which is the precondition
for cheap structural diffs, free version history, and a convergent multi-writer
merge (see §5). None of that works if the Python invariants (acyclicity, exact
transitive reduction, deterministic serialization) aren't held exactly —
that's why those bugs had to be fixed before this layer was designed.

## 2. Why a generic `recordstore` layer instead of Swarm calls directly in OntoDAG

Swarm/Bee gives you: a chunk store (immutable, content-addressed,
get/put by hash), a mantaray *library* for building `name -> reference` tries,
feeds (a mutable pointer to a "latest" reference), and postage stamps for
write authorization. It does **not** give you: typed records, a notion of a
consistent multi-key transaction, snapshot isolation, canonical encoding, or
an interface that hides storage layout from the application. `recordstore`
fills exactly that gap and nothing more:

- **Records instead of raw references** — a canonical codec (sorted keys,
  fixed separators) so identical content always serializes to identical
  bytes, which is a correctness requirement here, not a style preference:
  content addressing means non-determinism in encoding breaks the
  "same content -> same root" property everything else depends on.
- **A transactional commit unit** — an OntoDAG `put` touches several
  records (the new node, its supercategories' edge lists, ancestor
  counts); `commit()` lands all of them as one new root, so a reader never
  sees a torn write.
- **Snapshot isolation** — a reader pins one root and sees a frozen,
  self-consistent dataset for an arbitrarily long traversal, with no
  locking, because the whole dataset-at-a-version is just one reference.
- **A layout-hiding interface** — OntoDAG will only ever call
  `get(key)`, `put(key, value)`, `commit()`, `RecordStore.at(root)`.
  Everything about trie fanout, one-chunk-per-record vs. leaf-packing (see
  §4), or swapping the trie for mantaray-compatible encoding happens behind
  this interface with zero changes above it.
- **The substrate the CRDT merge runs in** (§5): folding a set of
  operations into a new canonical root is a `recordstore`-level
  read-modify-commit cycle; OntoDAG only supplies the merge *rule*.

Explicitly out of scope for `recordstore`, on purpose: no query planner, no
secondary indexes, no schema DSL, no knowledge of what an edge or a
descendant is. The moment this module starts knowing about graph semantics,
the boundary has leaked and part of OntoDAG has been rebuilt one layer down.

**Decision:** build `OntoDAG`-on-`recordstore` directly; do not build a
general graph/DAG database first. A generic graph layer designed with no
real client tends to get the abstraction wrong, and it wouldn't capture
OntoDAG's actual value (the invariants) anyway, since those are semantic and
belong in the OntoDAG layer regardless. If a second client for
`recordstore` ever appears, a more general structure can be extracted then,
which is cheaper than speculating about it now.

### Packaging status (decision, July 2026)

`recordstore` is conceptually independent of OntoDAG — it imports only the
Python standard library, contains no graph semantics, and the dependency is
strictly one-directional (ontodag → recordstore). The question of whether it
should live in its own repository was considered and **deliberately
deferred**, not rejected:

- **Stay in this repo for now.** The `SwarmOntoDAG` adapter (§3, §9) is the
  first real consumer and will exert pressure on the interface — batching,
  leaf-packing (§4), the GSOC merge (§5), the real feed pointer. Splitting
  repos before the first consumer stabilizes the API turns every interface
  adjustment into a change/release/pin/bump cycle across two repos.
- **Keep the boundary mechanically clean** so cohabiting costs nothing:
  `src/recordstore/` must never import from OntoDAG code and stays
  stdlib-only; it keeps its own self-contained tests. Because the directory
  is self-contained, `git filter-repo` / `git subtree split` can extract it
  later with full history — nothing done now forecloses the split.
- **Split when any of these become true:** the adapter is done and the API
  has stopped moving; there's a decision to publish it (PyPI / Swarm
  community — more attractive if the mantaray-compatibility question above
  is ever resolved in favor of compatibility); or a second consumer appears.
- **Cheap middle step** available before a full repo split: give
  `src/recordstore/` its own `pyproject.toml` so it is installable as its
  own distribution while still living in this repo.

## 3. Node record schema (for the `SwarmOntoDAG` adapter — not yet built)

One OntoDAG node is one `recordstore` record, keyed by name:

```
key:   "<name>"                       # the qualified/plain category name
value: {
  "up":    ["<name>", ...],           # supercategories (sorted)
  "down":  ["<name>", ...],           # subcategories (sorted)
  "count": <int>,                     # descendant_count
  "payload": "<swarm ref>" | null,    # optional: content this category tags
  "meta":  {...}                      # optional, e.g. Content-Type
}
```

Nodes are deliberately undifferentiated — there is no class/instance
`kind` field. Everything is one `Item`; a node that tags stored content is
simply one with a `payload`.

Both edge directions are stored (unlike current `dag.py`, which only stores
`down`/`neighbors` — adding `parents` in Python, already on the fix list in
`CLAUDE.md`, is what makes the in-memory and persisted shapes match).

**Hub nodes:** a typical record (~5-10 edges, short names) is 300-500 bytes,
comfortably inside one 4 KB chunk. A hub node (the root `*`, or a popular
category) can exceed that. `recordstore`'s `BeeChunkStore` already handles
this transparently — Bee's `/bytes` splitter turns any payload, however
large, into a chunk tree behind one reference — so oversized records work
from day one with **no special-casing needed in the record codec**. (An
earlier version of this plan proposed an inline-list-or-spill-reference
union in the record format for this; that's now unnecessary because the
chunk store already solves it one layer down. Leave the schema flat unless
a future profiling pass shows a reason not to.)

## 4. Storage layout: one record per chunk (current), and when to revisit it

Current `recordstore` layout is one record = one chunk, deliberately, even
though a typical 300-500 byte record fills only 10-15% of a chunk. Rationale:

- The novel, hard work in this project is the invariants and merge
  semantics, not chunk packing — keep the first implementation simple and
  debuggable.
- The three costs of underfilled chunks are not equally important:
  **storage rent** (per chunk regardless of fill — real money at large
  scale, noise below ~100k nodes), **write cost** (roughly a wash either
  way), and **read latency** (packing wins because Swarm's "page" is the
  4 KB chunk and its "seek" is a network round trip — traversing 8 packed
  records costs 1 round trip instead of 8; this is the disk-page argument
  in its purest form).
- Naive packing (arbitrary co-location) is a trap: rewriting one record in
  a shared chunk changes the chunk's address, so every trie entry pointing
  into it must update — write amplification, scattered through the trie.
  The only packing that works is **packing by key adjacency** — i.e.
  turning the trie's leaves into B-tree-style pages, a real feature with
  real machinery (page splits, a record-to-page indirection), not a tweak.
  A cheaper intermediate step: mantaray-style fork nodes can carry small
  inline values, so tiny records could ride inside trie chunks that are
  already packed many-per-chunk.

**When to revisit:** once there's usage data — record-size distribution,
which keys get traversed together — because that data is exactly what a
leaf-packing policy needs to be designed well, and guessing now would be
premature. The `RecordStore.get`/`put`/`commit` interface must not change
when this happens; only what's behind it does.

## 5. Multi-writer / CRDT plan (not yet implemented)

The uniqueness of transitive reduction (§1) gives OntoDAG an unusually clean
convergence property: define the canonical state as **the transitive
reduction of the union of all asserted edges**. Under that definition,
concurrent `put`/`remove` operations from independent writers commute — apply
them in any order, or repeatedly, and the result converges. That's exactly
what `merge`'s commutativity and idempotence (invariant I7 in
`tests/test_invariants.py`) rehearses in-memory; getting I7 to hold in Python
is the dry run for this.

Planned mechanism: writers post signed operations (`put(name, supers)`,
`remove(name)`) to a shared Swarm GSOC address; any reader folds the pending
operation set into the current root deterministically and commits the result.
`remove` needs a tombstone or an observed-remove rule (standard CRDT
territory) since plain deletion doesn't commute with a concurrent re-add.
This is `recordstore`-level machinery (a read-modify-commit cycle with a
particular source of changes) — `SwarmOntoDAG` only supplies the fold rule.

Not started. `SwarmFeedPointer` in `recordstore.py` is a documented stub for
the same reason: a real feed update needs client-side SOC signing
(secp256k1), which pulls in an Ethereum crypto dependency deliberately kept
out of the stdlib-only first cut. `FilePointer`/`MemoryPointer` stand in
until then.

## 6. Performance model (read this before optimizing anything)

The dominant cost is always the network chunk fetch, not any code-level
choice. Rough figures: a Python dict lookup ~100ns; a chunk already on a
**local** Bee node ~1-5ms (HTTP + local lookup); a **cold** chunk fetched over
the network ~100-500ms (routing hops). That 4-6 orders of magnitude spread
means Python-vs-Go, JSON-vs-CBOR, and the recordstore abstraction itself are
all *noise* relative to the storage model. What actually matters:

- **Trie descent is serial** (can't fetch a child before decoding its
  parent), so latency scales with trie depth `D`. Compaction keeps `D`
  small (typically 3-5 for realistic key sets) — this is the point of a
  compacted rather than byte-at-a-time trie.
- **Immutable chunks cache perfectly**, so warm-path reads (repeat access
  to the same ref) collapse toward RAM speed. This is *the* lever: see
  caching layers below.
- **OntoDAG traversals are naturally concurrent** (BFS over `up`/`down`
  fans out to independent fetches) but the current `recordstore` is
  synchronous. A batched/async `get_many()` is the single biggest future
  speed lever for real queries and should be an early addition to the
  `SwarmOntoDAG` adapter or a `recordstore` extension, not an afterthought.
- **One-record-per-chunk (§4)** costs a real, measurable multiple on cold
  multi-record scans (~8x round trips vs. a packed layout) but this erodes
  fast once records are warm in cache.

**Caching happens at four independent layers**, in order from fastest/most
ephemeral to slowest/most durable:

1. **In-process (`_Trie._cache` in `recordstore.py`)** — decoded trie
   nodes, unconditionally correct (refs are immutable), no invalidation
   needed. Currently caches trie nodes but not decoded value records —
   adding a value-level cache is a small, worthwhile follow-up. Dies with
   the process; unbounded today (fine to ~10^5-10^6 nodes, would want an
   LRU beyond that).
2. **Bee's local chunk store** — every chunk the node has uploaded,
   fetched, or served to peers, retrieval-order-first. Chunks you write
   are served locally forever *if not garbage-collected* — Bee's GC evicts
   least-useful chunks under disk pressure unless chunks are pinned.
   **Action item: pin the current root's chunks, or run a stewarding
   process, or an ontology will quietly start feeling slower as its own
   chunks get evicted** and eventually fail once the postage stamp expires
   too.
3. **Swarm-wide neighborhood forwarding cache** — emergent, not a tunable
   lever, safe to ignore for design purposes.
4. **HTTP caching downstream of Bee** — `/bytes/{ref}` responses are
   immutable by definition, so `Cache-Control: public, max-age=31536000,
   immutable` is correct if ever fronted by nginx/a browser/another
   process. Not wired in `BeeChunkStore` yet; low priority.

**Practical consequence:** for anything that fits in memory (a 100k-node
ontology is a few tens of MB), the fast pattern is *hydrate into the
existing in-memory `OntoDAG` once at startup, query entirely in RAM, and
push mutations through `recordstore.put`/`commit` for durability and sync*.
A cold hydration walk costs roughly `node_count x 5ms` the first time
(e.g. ~50s for 10k nodes) if the local Bee store doesn't have the chunks
yet; after that everything in-process is microseconds. Partial, on-demand
loading through the trie (rather than full hydration) is the regime for
graphs too large for RAM — not needed yet.

## 7. What's tested and what isn't (as of this document)

Tested (`tests/test_recordstore.py`, 11 tests): roundtrip + read-your-writes
staging, canonical roots under order/history independence (batched vs.
incremental, forward vs. reverse insertion, put-then-delete churn — this is
the load-bearing property for §5), snapshot isolation and all-or-nothing
commits, structural sharing (a 1-of-200 record update writes <12 chunks),
sorted prefix iteration with the staged overlay, and no-aliasing of returned
records (the same bug class as `intersection_dag` in `dag.py`, checked here
from day one).

Tested (`tests/test_recordstore_fuzz.py`): 12 seeded random histories of 400
ops each, against a plain-dict oracle, using an adversarial key set (mutual
prefixes, unicode, emoji). After every commit: contents match the oracle
exactly, and the root equals a from-scratch rebuild of the same content —
i.e., the canonical-root property survives arbitrary interleavings of
put/delete, not just the hand-picked orderings in the unit tests.

Run once, July 2026 (`tests/test_recordstore_bee.py`, skips cleanly without
`BEE_API` set) — all 4 passing against **`bee dev` v2.7.1**: roundtrip
through a real Bee node's `/bytes` API (header handling, real BMT refs
instead of the test double's sha256 refs), canonical roots under real Bee
refs, a 50KB oversized record round-tripping through Bee's splitter as one
reference (the hub-node case from §3), snapshot isolation over real storage.
**Label:** the dev-mode run validates the HTTP contract only. Bee v2.8.0
broke protocol compatibility with ≤2.7.x (handshake 15.0.0 / hive 2.0.0)
and removed dev mode, so a dev-mode 2.7.1 node is an isolated API fake.

**Real-node run (2026-07-11):** the same 4 tests also passed against a live
bee v2.8.1 light node on Gnosis mainnet with a real purchased postage batch
(depth 17, ~2-day TTL) — current version, real stamps, real BMT refs.
Caveat discovered: mainnet rejects batches under ~1 day of validity, so the
test's auto-buy default fails on a real node; set `BEE_BATCH` explicitly.
Still open: retrievability from other nodes (`/stewardship`), postage
expiry, GC/pinning — see `CLAUDE.md` "Bee integration status".

Tested (`tests/test_swarm_adapter.py`, 13 tests, added July 2026 with the
adapter): commit/rehydrate roundtrip with queries on the rehydrated graph,
history- and put-order-independent canonical roots at the *graph* level (not
just the record level), idempotent commit, incremental staging (a one-node
addition does not restage untouched subtrees), structural invariants after
rehydration, merge from either side converging to the identical root — the
persisted form of I7 and the direct precondition for §5 — and persisted
removal. All against `MemoryChunkStore`; a Bee-backed adapter test is still
missing (same `BEE_API` gate as the recordstore one).

Not tested, consciously deferred: concurrent writers to the same pointer
(single-writer assumed until §5's GSOC/CRDT layer exists), the feed pointer
itself (stub, see §5).

## 8. Provenance, and its role in a distributed/learned architecture (future work)

Not started; roadmap only. This section records a design direction we want
pinned down but are deliberately **not** building yet — no schema field, no
code. It is here because it constrains two mechanisms already described in
this doc (caching/eviction in §6, multi-writer sync in §5), and getting those
right later is cheaper if the provenance idea is on the record now.

### Related project: a structure learner producing the same-shaped DAG

There is a companion structure learner, **mdl-fca**
(https://github.com/petfold/mdl-fca), that learns "good" concept DAGs from
binary object×attribute data by minimum description length — a
probabilistic/MDL reworking of Formal Concept Analysis in which a concept
exists only if it compresses the data enough to pay for its own description.
Its DAG model is structurally aligned with OntoDAG's (downward-closure
semantics, multi-parent, acyclic, bidirectional edges), so a learned DAG can
become an OntoDAG snapshot through a mostly-identity conversion. That
alignment is what makes the rest of this section a real integration path
rather than an analogy: a learner can *emit* the same structure this doc
persists.

### Where the learner sits: separate package, in-memory access

The learner stays **outside the OntoDAG core**, as its own package/repo
depending on `ontodag` as a library — a strictly one-directional dependency
`learner → ontodag`, mirroring the existing `ontodag → recordstore` boundary.
The core must remain importable and fully functional with no learner present
(the B1-style discipline in `tests/test_boundaries.py`), so a boundary check
belongs here too. This keeps algorithms swappable — MDL-FCA today, something
else later — which is not merely convenient: the provenance schema pins
`learner_version` precisely because learners are expected to be replaceable.

The obvious objection — "a learner needs fast access to the detailed
structure, not a slow interface" — conflates two independent choices. The slow
interface in this project is `recordstore`/Swarm (the *persistence* boundary),
not the module boundary. A learner in a separate package but running
in-process gets the same object-reference-speed access to `neighbors`/`parents`
the core enjoys (the Identity decision preserves those pointer hops within a
DAG instance), following §6's hydrate-once/RAM-first pattern: all hot work
against the in-memory graph, the slow interface touched only at commit. Note
too that mdl-fca's hot-path input is the object×attribute matrix and its own
lattice-under-construction, with the concept DAG as *output* — so it is not
doing per-operation random reads against the OntoDAG structure anyway, and
learning is a periodic batch step, not something interleaved with every `put`.

The one thing to fix deliberately is the **in-memory contract** the learner
may touch: a clean read view plus a `put(..., origin=derived)` write path,
rather than reaching into private internals — otherwise keeping the seam would
quietly freeze OntoDAG's representation, defeating the point. Folding the
learner into the core would only be justified if a boundary crossing *per graph
operation* were unavoidable, which batch MDL/FCA learning is not.

### Design idea: tag provenance, don't add an instance/class distinction

The tempting move when mixing learned and asserted structure is an ontological
**instance vs. class** node distinction. Reject it: it is philosophically
unstable. Any "instance" can later be subdivided into a category — a book → an
edition → my copy → my copy when new — with no principled place to stop, so
the boundary can't be drawn once and trusted.

Instead, tag every node with **provenance**, orthogonal to what the node *is*:

- `origin: asserted | derived`
  - **asserted** — put there by an external act (user, import, observation).
    Ground truth; not regenerable; losing it is data loss. Must be retained
    durably.
  - **derived** — proposed by a learner (e.g. mdl-fca) because it compressed
    asserted data. A function of the asserted nodes plus the objective;
    regenerable by re-running the learner; losing it is only a cache miss.
- `derived_from: (corpus_root, learner_version) | null` — for derived nodes,
  the exact immutable snapshot + learner version that would regenerate it.
  Regenerability is only meaningful relative to a fixed corpus and learner, so
  it must be pinned, not assumed. (The content-addressed `corpus_root` is
  exactly the kind of immutable snapshot reference §1 makes cheap.)
- `endorsed: bool` — a user can promote a derived concept to something they
  rely on. Once endorsed, re-running the learner may propose a replacement but
  must not silently overwrite it.

### Why this matters for the architecture already in this doc

- **Postage / eviction policy (§6).** The provenance bit is exactly the flag
  that says which nodes are droppable. Derived nodes are regenerable → keep
  warm only when retrieval frequency justifies the storage cost, else let
  postage lapse and recompute on demand. Asserted nodes are not regenerable →
  retain durably regardless. This is the semantic input the "which chunks do
  we pin / keep stamped" question in §6's caching layers currently lacks.
- **Shared base / personal overlay (§5).** Provenance is orthogonal to
  shared-vs-personal, giving a 2×2. The commonsense base is largely *derived*
  (learned from a big corpus, so cheap to distribute — a user with the corpus
  recomputes it and syncs only the diff). Personal *assertions* are the
  irreplaceable inputs that need durable postage and backup. Personal
  *derived* concepts are recomputable per-device. So provenance is the routing
  information for what must sync durably vs. what can be lazily recomputed —
  directly feeding the multi-writer merge in §5.

### Adjacent research note: retrieval-aware MDL

Related, and equally deferred: mdl-fca's score already fully accounts for
**activation** frequency (how often a concept helps generate the data, via its
usage-coding term). It does not — and structurally cannot — account for
**retrieval** frequency (how often a concept is read by queries after the graph
is built), because that is a property of the query workload, not the training
data.

In the metered, separately-queried Swarm setting there is a genuinely
additional objective term:

```
L(data | G) + λ · Σ_c retrieval_freq(c) · storage_cost(c)
```

where `retrieval_freq` comes from the query log. This term is identically zero
in the in-memory setting (no retrieval cost) and collapses to nothing when the
query distribution mirrors the data distribution; it only earns its place when
the workload diverges from the corpus — likely common for a personal tool,
where users repeatedly query statistically-rare pet categories. This is a
research direction, not a committed feature; the real design decision to pin
down before acting on it is the free parameter **λ** (bits per byte-second of
storage, access-weighted).

## 9. Sequencing (what comes after `recordstore`)

1. **Done in dev-mode form (July 2026, see §7 for the label).** Run
   `test_recordstore_bee.py` against a live node. The remaining half is
   real-network validation against a funded Bee ≥2.8.1 node.
2. **Done (July 2026).** Fix the `dag.py` invariant bugs in
   `tests/test_invariants.py` (see `CLAUDE.md` for the exact list and
   order) — this was a precondition, not parallel work, because the
   `SwarmOntoDAG` adapter should inherit clean semantics rather than freeze
   bugs into a content-addressed encoding.
3. **Done (July 2026).** Build `SwarmOntoDAG`: a class implementing
   `put`/`get`/`remove`/`merge` against the `recordstore` interface, using
   the schema in §3 and the hydrate-once/RAM-first pattern in §6
   (`src/ontodag/swarm_adapter.py`).
4. Only then: consider leaf-packing (§4), async batched fetches (§6), the
   GSOC-based merge (§5), and the real feed pointer (§5) — each is an
   internal change behind an interface that shouldn't need to move again.
