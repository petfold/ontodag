# Merkle structures in OntoDAG: what they can and cannot do for us

Status: analysis, 2026-07-28. Not a task list — a decision record so the
question isn't re-litigated from scratch.
Origin: asked after the delta-count work landed — *"I was thinking how to
determine which parts of the DAG were affected by changes. An idea is BMT.
But you managed to fix it without BMT. Would it be a good idea to use BMT in
OntoDAG?"*

## First, two different things are called "BMT"

1. **Swarm's chunk addressing.** `keccak(span ‖ bmt_root(payload))` — how a
   Swarm reference is derived from content. `swarmfs.splitter` (added
   2026-07-28) computes it offline. Its relevance to OntoDAG is *identity*:
   whether a local store shares Swarm's address space
   (`recordstore.DirBytesStore(addressing="swarm")`). Nothing to do with
   change detection.
2. **A Merkle tree used to detect what changed** — the sense in the question.
   Hash the structure, compare hashes, skip anything equal.

The rest of this note is about (2). They are orthogonal: (1) is a choice of
hash function for naming blobs, (2) is a technique for diffing versions.

## Why it did not solve the count problem

A Merkle hash answers exactly one question: **are these two things equal?**
It cannot answer either question the count work actually needed:

- *"How much did this count change?"* — that is arithmetic. A hash tells you
  a subtree differs, not that an ancestor's `descendant_count` should go
  `+1`.
- *"Can X already reach n?"* — that is **membership**, and hashes do not
  answer membership.

There is a second, more basic reason. **When you are the one making the
change, you already know where it is.** `put(Spaniel, [Dog])` hands you the
affected region directly: the ancestor closure of `Dog`. There is nothing to
discover, so a detection mechanism has no work to do. Merkle diffing earns
its keep precisely when you did *not* make the change and must find it.

## Where it is already working, for free

recordstore's trie is a Merkle structure — every node is a content-addressed
blob — and `_diff` "prunes shared subtrees, so the cost is proportional to
the difference, not the dataset". Equal references ⇒ identical subtrees ⇒
skip. OntoDAG already benefits from this whenever versions are merged at the
storage layer. No new mechanism required; it is a property of the substrate.

## The genuinely promising use: unblocking lazy writes

`LazyOntoDAG` is read-only for what were three reasons. One is gone:

1. ~~exact counts are whole-graph properties~~ — **disproved** 2026-07-25;
   counts are maintained by local delta (see `HOW_IT_WORKS`, "counts"), which
   is both exact and cheaper than the recompute it replaced.
2. **change detection** — `EagerOntoDAG.commit()` builds a record for *every*
   node and diffs it against a complete `_synced` dict held in memory. This
   is exactly what a partially-resident writer cannot do, and it is now the
   principal structural blocker.
3. **minimal links** — transitive reduction is bounded by the ancestors and
   cones it touches, so it looks local, but that has not been tested under
   partial residency.

**Blocker 2 is a Merkle-diff problem, and the machinery already exists.**
Instead of holding `_synced`, walk the current trie against the previously
committed root, pruning every subtree whose reference matches; what survives
is precisely the set of changed records. That needs no in-memory copy of the
graph, which is the whole point.

Concrete step: `recordstore._diff` is **private**, used only by `merge`.
Exposing it (`RecordStore.diff(other_root)` or similar, yielding
`(key, before, after)`) is small, has an obvious contract, and is the
prerequisite for a lazy writer. It would also give OntoDAG a cheap
"what changed between these two published versions?" for free — useful well
beyond writing.

## What Merkle will *not* fix, with the right tool named

- **Cross-links** (adding an edge between two items that both already exist —
  the multiple-inheritance case, `put(Dog, [Pet])` when `Dog` exists). Cost
  here is per-ancestor *membership*: "how much of the newly reachable subtree
  could I not already reach?" The answer is a membership summary — the
  succinct cone bitmaps in `CONE_SUMMARIES_PLAN.md`, roadmap item 1, where
  the test becomes `popcount(cone_c & ~reach(X))` — **not** a hash tree.
  Measured gap: appends 8.9× cheaper under delta counts, removals 642×,
  cross-links only ~1.9×.
- **Multi-writer count reconciliation.** Every insert changes the root's
  count (the root is an ancestor of everything), so two concurrent writers
  always both touch it. Hashes will confirm the conflict, not resolve it.
  Counts are *derived*: re-compute them from the merged structure rather than
  reconciling them as competing values (see `SWARM_DESIGN.md` §5).

## Summary

| question | right tool | status |
|---|---|---|
| how much did a count change? | delta rules | done (2026-07-25) |
| can X reach n? | cone summaries / bitmaps | roadmap item 1 |
| what changed between two versions? | **Merkle diff** | exists in recordstore, private |
| detect my own changes without full residency | **Merkle diff** | the next step for lazy writes |
| what is this blob called? | Swarm BMT vs sha256 | choosable per store, orthogonal |
