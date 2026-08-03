# SWARM_DESIGN.md — Update: Combined POT / beeson / recordstore Architecture

> **Note for Claude Code / whoever integrates this:** This is a drop-in addition to the
> existing `SWARM_DESIGN.md`, written from a chat that reviewed the Proximity Order Trie
> (POT) paper (Trón & Verbin, draft July 2026) and the b33son paper (Trón & Tóth, draft
> July 2026) against OntoDAG's own `recordstore` work. Merge instructions:
> - If `SWARM_DESIGN.md` already has a persistence/storage section, merge §1–§5 below into
>   it and keep the existing section's terminology where it conflicts with this doc's.
> - If it doesn't, add §1–§5 as a new top-level section (e.g. "Storage Architecture").
> - §6–§9 (repo boundaries, integration steps, open questions, milestones) are meta/process
>   content — keep these as their own section regardless, since they're project-management
>   rather than design content and shouldn't get absorbed into design prose.
> - Flag anything here that contradicts a decision already recorded elsewhere in
>   `SWARM_DESIGN.md` rather than silently overwriting it — some of this is a proposal,
>   not yet a decision (see §8).

**Context:** dated 2026-07-19. Sources: `proximity-order-trie.md` (distilled POT notes),
the POT draft PDF, the b33son draft PDF, and OntoDAG's existing `recordstore` design
(canonical radix trie, `MemoryChunkStore`/`BeeChunkStore` backends).

**Status note:** `recordstore` currently lives inside this repo, under active development
here. `github.com/petfold/recordstore` has been created (empty) as its destination repo.
This document describes the target architecture post-extraction; §6–§7 include the actual
extraction steps, which have not yet been run.

---

## 1. Layered architecture

```
 ┌─────────────┐  ┌──────────────┐  ┌─────────────┐
 │   OntoDAG   │  │ Marketplace  │  │ Worldwatch  │   domain consumers
 └──────┬──────┘  └──────┬───────┘  └──────┬──────┘   (each its own repo)
        └────────────────┼─────────────────┘
                          ▼
                 ┌──────────────────┐
                 │      beeson      │   record encoding + schema registry
                 └────────┬─────────┘   (spec / own repo)
              ┌───────────┴────────────┐
              ▼                        ▼
   ┌────────────────────┐   ┌───────────────────────┐
   │     recordstore     │   │    POT (whirl), opt.  │   indexing — two poles
   │ canonical radix trie│   │  write-ahead log       │   (recordstore repo,
   └──────────┬───────────┘   └───────────┬───────────┘   POT optional/later)
              └────────────┬───────────────┘
                            ▼
                 ┌──────────────────────┐
                 │ Chunk store abstraction│   MemoryChunkStore / BeeChunkStore
                 └───────────┬───────────┘   (lives in recordstore repo)
                             ▼
                    ┌──────────────────┐
                    │  Swarm / Bee node │
                    └──────────────────┘
```

Each layer answers one question:

- **Swarm/Bee** — where bytes physically live, postage economics.
- **Chunk store abstraction** — a pluggable interface over that (`/bytes`, `/chunks`),
  already built as `MemoryChunkStore` / `BeeChunkStore` — currently living inside this
  repo, moving to the standalone `recordstore` repo (§6). This is the shared foundation;
  nothing above should talk to Bee directly.
- **Indexing (two poles of one trade-off)**:
  - `recordstore`'s **canonical radix trie** is the ground truth: deterministic references,
    cross-writer dedup, mergeable, provable roots — at the cost of O(path) rewritten
    chunks per update.
  - **POT** (whirl variant) is the opposite pole: O(1) new chunks per update, ideal for
    append-heavy logs, at the cost of non-canonical, history-dependent roots. Treat it as
    an **optional companion**, not a replacement — a write-ahead log that periodically
    compacts into a `recordstore` checkpoint (LSM-style), used only where a consumer is
    genuinely write-dominated (see §8).
- **beeson** — canonical, schema-conformant, field-addressable binary encoding for
  whatever sits at the leaves of either index. Gives every value a stable canonical
  reference and lets a BMT proof reveal one field without the whole record.
- **Domain layer** — OntoDAG, Marketplace, Worldwatch. Each defines its own beeson
  realm(s) and persists instances through `recordstore` (and, later, POT where relevant).

---

## 2. Where OntoDAG fits

OntoDAG is a **consumer** of `recordstore` and beeson, and a plausible **co-developer**
of one specific, underdeveloped part of beeson.

**As consumer:**
- Define a `concept` beeson realm: attributes for extension, intension, MDL score,
  parent/child concept-refs. `dag.py`'s existing invariants suite is effectively the
  test suite for this realm's ideal — the schema discipline already exists in code and
  now gets a name, a canonical wire format, and a hash-addressable reference.
- Persist concept nodes through `recordstore`, keyed by concept ID (or by content hash,
  if concept identity should be structural — see open question in §8).
- The `sys:` projection namespace in `datacat.py` (regenerable mapping from placement
  facts to human categories) keeps its existing role as a local, disposable *view*. The
  only change is that the authoritative store it's regenerated from becomes
  Swarm-persisted via `recordstore` rather than local SQLite.

**As co-developer:** beeson §3.3 (facets, "concepts," conceptual closure — generalization
by attribute-subset removal) is, structurally, a Formal Concept Analysis concept lattice,
underformalized. This is squarely OntoDAG's home turf. Worth proposing to Trón directly
that OntoDAG's FCA work extend/finish that section, rather than beeson reinventing FCA
independently — the same way the three POT implementations are what made that paper
concrete rather than just asserted.

---

## 3. recordstore's role: the canonical pole

No change to `recordstore`'s existing design here — this section just states explicitly
*why* the canonical radix trie is the right default, now that it has multiple consumers:

- Deterministic references → equal content produces equal roots → automatic dedup across
  OntoDAG, Marketplace, and Worldwatch if they ever share sub-objects.
- Mergeable: subtree-hash comparison short-circuits diff/merge, which matters once more
  than one writer touches overlapping structure (e.g. collaborative concept curation).
- Verifiable from content alone — a fresh reader can check a root without replaying
  history, unlike a whirl-based POT.

The cost — O(path) rewritten chunks per update — is the correct trade for OntoDAG's
access pattern (read-dominated, structure-dominated, not append-log-dominated).

---

## 4. POT's role: optional write-ahead log

Not needed on day one. Build only when a consumer is genuinely write-heavy — Worldwatch's
per-stream surprise events are the likeliest first candidate, not OntoDAG. If/when built:

- Whirl-to-top inserts, O(1) new chunks, timestamp-keyed (the paper's "event log"
  variant).
- Periodically compacted into a `recordstore` checkpoint; short-TTL postage stamps on
  WAL/L0 chunks since they're superseded at compaction (free garbage collection).
- Node format detail worth carrying over from the POT implementation chat: sparse
  bitmap-indexed fork tables, per-node adaptive inline-vs-reference value placement
  (small/deep nodes inline a beeson record; large/shallow nodes spill to a reference) —
  this composes cleanly with beeson's segment-aligned field proofs either way.

---

## 5. beeson's role: record encoding and schema registry

Adopt now, informally, regardless of whether the full beeson library exists yet:

- Deterministic field ordering (fixed-length first, descending size, then lexicographic
  attribute name), 32-byte segment alignment, large/shared substructures hoisted to
  references. Doesn't require waiting on the paper's §3 (Datasets), which is empty —
  OntoDAG's own indexing needs (via `recordstore`) fill that gap in practice.
- Realms/ideals are themselves beeson objects with canonical serializations → the schema
  registry is just another versioned map inside `recordstore`. This gives schema
  evolution the reified history the beeson paper wants, using machinery `recordstore`
  already has.
- Note the one real constraint this imposes: beeson payloads carry **no embedded type
  info** by design. Index entries need `(schema-ref, record-ref)` pairs, or the schema
  must be recoverable from the key's namespace.

---

## 6. Repo boundaries and dependency graph

**Current state:** `recordstore` still lives inside this repo. `github.com/petfold/
recordstore` exists (empty, cloned locally) but nothing has been pushed to it yet.
Target state:

```
recordstore  ◄──────────── OntoDAG
     ▲       ◄──────────── Marketplace   (prospective)
     │       ◄──────────── Worldwatch    (prospective)
     │
  beeson (spec) ── informs value encoding in all of the above
```

Decision rule used throughout: **two or more real (not hypothetical) consumers →
standalone repo with versioned releases.** `recordstore` now clears this bar — OntoDAG
plus the prospective Marketplace/Worldwatch consumers — which is why it's being pulled
out now, not why it should stay put.

**Extraction (history-preserving, run from the OntoDAG working directory):**

```bash
# 1. Confirm the path — adjust if recordstore isn't a top-level directory
#    (e.g. src/recordstore instead of recordstore)
git log --oneline -- recordstore | head

# 2. Split that directory's history onto its own branch
git subtree split --prefix=recordstore -b recordstore-split

# 3. Push that branch as main in the new (empty) repo
git push https://github.com/petfold/recordstore.git recordstore-split:main

# 4. In a fresh clone of recordstore, sanity-check the history came across
git clone https://github.com/petfold/recordstore.git /tmp/recordstore-check
cd /tmp/recordstore-check && git log --oneline

# 5. Back in OntoDAG: remove the now-extracted directory and the split branch
cd -   # back to OntoDAG
git rm -r recordstore
git commit -m "Extract recordstore into github.com/petfold/recordstore"
git branch -D recordstore-split
```

If `git subtree` isn't available or the history is tangled with unrelated commits,
`git filter-repo --path recordstore --to-subdirectory-filter recordstore` against a
throwaway clone is the more robust alternative — worth trying `subtree` first since it's
simpler and doesn't require installing anything.

After the push, tag a first release in `recordstore` (e.g. `v0.1.0`) so OntoDAG can pin
a version rather than reading off `main`.

**Ongoing boundaries, once split:**

- **recordstore**: standalone, tagged releases, README describing the public API
  (`put`/`get`/`update`/`delete`/`iterate`/`save`-equivalent, the two chunk store
  backends, the canonicity guarantee). Every consumer pins a version.
- **OntoDAG**: keeps `dag.py`, the invariants suite, `CLAUDE.md`. Adds a thin
  `docs/recordstore-interface.md` — a manually synced summary of `recordstore`'s public
  surface, *not* a git submodule. A submodule solves a version-pinning problem that
  doesn't exist yet and introduces a sync-drift problem that does.
- **beeson**: stays a spec/paper repo for now; implementations (Go/TS/Python) arrive as
  separate packages later, mirroring POT's one-reference-plus-two-ports pattern. Don't
  let an implementation attempt get entangled with the still-moving spec.
- **Only reconsider merging repos** if version-pinning friction (bump recordstore → bump
  N consumers' pins, repeatedly) becomes the dominant cost — at which point a
  single-repo, multi-package workspace layout is the right fix, not a true merge of
  `dag.py` and `recordstore`'s internals into one undifferentiated codebase.

---

## 7. Practical integration steps for OntoDAG

1. **Run the extraction in §6** — split `recordstore` out, push to
   `github.com/petfold/recordstore`, remove it from this repo, tag `v0.1.0`.
2. Add `recordstore` as a pinned dependency in this repo (path/git dependency against the
   tag until it's published to PyPI, if it's Python; adjust for whatever the actual
   toolchain is).
3. Add `docs/recordstore-interface.md` summarizing the public API OntoDAG actually uses.
4. Define the `concept` beeson realm (§2) informally — a plain serializer function is
   enough to start; doesn't need to wait on a full beeson library.
5. Decide concept-node keying: semantic ID vs. content-hash (see §8 — unresolved).
6. Defer POT/WAL entirely until a concrete write-heavy need appears.

---

## 8. Open questions / decisions log

- **Concept-node keying.** Semantic key (mutable, evolves across versions) vs.
  content-hash key (immutable, set-like, automatic dedup) — likely need both: a
  content-keyed canonical store plus semantic secondary indexes into it. Not yet decided
  for OntoDAG specifically.
- **Schema registry location.** Proposed: inside `recordstore`, as just another versioned
  map. Needs confirming this doesn't create a circular dependency (schema definitions
  needed to interpret values, stored using the same value-encoding they define — should
  be fine if schema objects use a fixed, un-schema'd bootstrap encoding, but worth being
  explicit about).
- **When does POT/WAL become necessary?** Deferred until a consumer shows a genuinely
  write-dominated pattern. Candidate: Worldwatch's per-stream event log.
- **beeson §3.3 (facets/concepts) as OntoDAG contribution** — proposal, not yet raised
  with Trón.

---

## 9. Near-term milestones

- **M1** — Extract `recordstore` out of this repo into `github.com/petfold/recordstore`
  (history-preserving, §6), tag `v0.1.0`, pin it back in as a dependency here.
- **M2** — `concept` realm defined informally; concept nodes round-trip through
  `recordstore`.
- **M3** — `docs/recordstore-interface.md` added to OntoDAG.
- **M4** (stretch) — proposal to Trón re: OntoDAG/FCA finishing beeson §3.3.
- **Deferred** — POT/WAL integration, pending a real write-heavy consumer.
