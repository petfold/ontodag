# How OntoDAG Works Inside

This is the companion to the [User Guide](USER_GUIDE.md): what actually happens
when you `put`, `get`, `remove` and `merge`, why the design insists on the rules it
enforces, how your data can outlive your laptop, and where the project is headed.
It's written for a broad audience — no graph theory required, though we'll earn a
couple of technical terms along the way. Readers who want the full engineering
rationale can continue to `SWARM_DESIGN.md` and `SEMANTIC_CODES.md`; this document
is the readable map of that territory.

---

## 1. The shape of the thing

OntoDAG stores one graph: named items connected by "is-under" arrows, general
above, specific below, with a single root `*` above everything. Arrows may
converge — `Dog` sits under both `Animal` and `Pet` — which is what makes it a
**DAG** (directed acyclic graph) rather than a tree. Trees are what folders are;
the whole point here is to not be one.

Every item casts a shadow downward: itself and everything reachable below it. We
call that its **cone**. `Animal`'s cone contains `Dog`, `Cat`, `Spaniel`, and every
photo you ever file under any of those. The *entire query language* is one
operation on cones:

> **get(A, B, …) = the intersection of the cones of A, B, …**

"Everything that is under all of these." That single primitive is deliberate: it
keeps the system small enough to be exact — and exactness, it turns out, is where
all the magic comes from.

## 2. The golden rule: keep no link you can infer

Here is the one design decision from which everything else follows.

At all times, OntoDAG stores the **minimal** set of arrows whose implications give
your full category structure — never a link that's already implied by a chain of
others. If `Spaniel → Dog → Animal` exists, the direct link `Spaniel → Animal`
must *not* be stored; adding it is silently skipped, and if adding some new link
makes an old one redundant, the old one is dropped on the spot. Mathematicians
call this the **transitive reduction** of the graph.

Why be so strict? Because of a lovely mathematical fact: **for a DAG, the
transitive reduction is unique.** There is exactly one minimal graph for any given
category structure. Which means:

- **Your graph has a canonical form.** However you built it — whatever order you
  added things, whatever redundant links you tried to add along the way — the
  stored graph is byte-for-byte the same. Two people who describe the same
  knowledge get the *identical* object.
- **Identical objects can be fingerprinted.** Serialize the canonical form
  deterministically and hash it, and "the same ontology" becomes "the same
  fingerprint" — which is what makes saving to content-addressed storage (§6),
  cheap change-detection, and multi-writer merging (§7) possible at all.

So when the User Guide says "OntoDAG tidies your graph automatically," this is
what's really going on: the tidiness is a *canonical form*, and the canonical form
is a load-bearing wall, not a cosmetic preference.

## 3. What happens when you `put`

`put(Spaniel, [Animal, Dog])` runs, for each requested parent link:

1. **Already implied?** If `Spaniel` is already reachable from `Animal` through
   other links, skip this link entirely (that's the redundant-`Animal` case).
2. **Would it loop?** If the *reverse* is reachable — `Animal` is somewhere below
   `Spaniel` — the link would create a cycle, and the operation is rejected with
   an error *before anything is modified*. "Is X reachable from Y" is answered by
   a simple walk that stops as soon as it finds the target.
3. **Does it obsolete an old link?** If some ancestor of `Dog` (say `Animal`) has
   a direct link to `Spaniel`, that link is now redundant and gets removed.
4. Only then is the arrow added.

Alongside the arrows, every item keeps a running `descendant_count` — the size of
its cone. Rather than recount after every arrow, a whole `put` batches its changes
and refreshes the counts once at the end. These counts are more than statistics;
they're the query planner's fuel (§4).

Internally each item knows both its children *and* its parents (two mirrored sets,
kept in sync automatically), so the graph can be walked cheaply in either
direction — downward for cones, upward for ancestry checks.

## 4. What happens when you `get`

A query like `get(Animal, Pet, Vaccinated)` could be executed naively: compute
each cone by walking the graph, then intersect the three sets. Correct, but
wasteful — and OntoDAG's planner improves on it in ways borrowed from database
query optimizers, all *provably result-preserving* (an optimizer that changes
answers is a bug generator):

**Planned before touching the graph** — using knowledge that's exact in advance:

- *Drop redundant terms.* If `Dog` is among your query terms along with `Animal`,
  the `Animal` term adds nothing (everything under Dog is already under Animal),
  so it's discarded. The check walks *upward* from the more specific term, which
  is cheap — ancestor chains are short even in huge graphs.
- *Order by size.* `descendant_count` says exactly how big each cone is, so the
  planner starts with the smallest — the strongest filter first.

**Decided during the query** — using knowledge that *only exists* at runtime:

- After each intersection step, the planner looks at how many candidates survive.
  No statistic could have predicted this (it depends on how much the cones
  overlap), but now it's a known number, and it drives a choice between two
  strategies for each remaining term:
  - **walk** the term's whole cone and intersect — right when many candidates
    remain;
  - **probe** upward from each surviving candidate and check the remaining terms
    are among its ancestors — right when few candidates remain, because its cost
    doesn't depend on how huge the remaining cones are, and a single upward walk
    per candidate settles *all* remaining terms at once.
- And if the running result ever becomes empty, the query stops immediately —
  the biggest cones are often never visited at all.

The flavor to take away: *plan with what's known in advance, adapt on what can
only be learned by doing* — and never let either change the answer.

## 5. Removing, merging, and why order never matters

**Remove** deletes an item and reconnects its children to its parents — the graph
"contracts" over the hole, so no knowledge below the removed item is lost, and the
result is again the unique minimal form.

**Merge** takes another OntoDAG and folds it in: add every missing item, then
replay every arrow through the same careful `put` machinery (so redundancies
introduced by the union are pruned). Because both inputs were canonical and the
union is re-canonicalized, merge has two properties that were engineered
deliberately and are checked by tests:

- **Commutative:** merging A into B gives the same graph as merging B into A.
- **Idempotent:** merging the same thing twice changes nothing.

Together with the canonical form, this means *any group of people can share
changes in any order, repeatedly, and converge on the identical graph* — the
property distributed-systems folks call a CRDT. That's the seed of the
multi-writer future in §8.

**Names are the identity.** Inside a running DAG, links are direct object
references (fast pointer hops). But at every boundary — files, queries, merging,
network — an item *is* its name string, nothing more (which is why the public API
simply accepts plain strings). Two `"Dog"`s are the
same dog. This is why merges knit shared categories together, and why the same
name in two DAGs means the same thing. (The corollary — agree on names before
merging — is the price of that simplicity.)

## 6. Saving forever: fingerprints all the way down

Persistence goes through a small library called **recordstore**, developed
alongside OntoDAG (and usable without it). It provides a versioned key→record
store on top of **content-addressed storage** — storage where each blob of bytes
is retrieved by its own cryptographic fingerprint (hash), and nothing is ever
overwritten: new content simply gets a new fingerprint.

The trick recordstore adds is an index (a compacted radix trie, if you're
collecting terms) that is itself stored the same way and built so that **equal
contents always produce an equal index** — history doesn't matter, only the
current data. So each `commit()` returns one fingerprint, the **root**, with
strong properties:

- The root names your *entire dataset at this moment*. Share the root, share the
  dataset. Keep an old root, keep a snapshot forever — old roots remain valid,
  because nothing is overwritten.
- Same content ⇒ same root, always. Comparing two versions starts with comparing
  two strings.
- Consecutive versions **share structure**: committing a small change writes only
  the records that changed plus a thin path of index nodes — like git, a thousand
  snapshots of a slowly-changing dataset costs little more than one.

`EagerOntoDAG` is OntoDAG plugged into this: **one record per item**, keyed by
name, holding its parent names, child names, count, and optionally a payload
reference and metadata. On startup it loads all records into an ordinary
in-memory OntoDAG (queries stay RAM-fast); `commit()` diffs the graph against
what was last saved and stages only the changed records. And because the graph
has a canonical form (§2) *and* the store gives canonical roots, the fingerprint
chain goes all the way up: **same ontology ⇒ same records ⇒ same root**, no
matter who built it or in what order. The test suite literally builds the same
ontology by different histories and asserts the roots come out identical.

**Where Swarm fits.** Ethereum Swarm is a peer-to-peer network that acts as a
giant content-addressed store: data is split into chunks, spread across nodes
worldwide, retrieved by fingerprint, paid for with "postage stamps" (storage rent,
so the network knows what to keep). Point recordstore's `BeeBytesStore` at a Swarm
node instead of memory or disk, and the same `commit()` publishes your ontology
into that network — durable, verifiable by fingerprint, hosted by no one in
particular. This works today against a real node; making it *convenient* (a
published mutable "latest version" pointer, multi-writer collaboration) is the
active edge of the project — see below.

## 7. How we know it's correct

A design whose value is exactness needs its guarantees tested as such. The test
suite is organized around named **invariants** — I1 acyclicity, I2 transitive
reduction, I3 order-independence, I4 no aliasing between derived graphs, I5 exact
counts, I6 no recursion (deep graphs must not crash), I7 merge
commutativity/idempotence — plus the dependency boundaries (the core must work
with no optional library and no network). Wherever an optimization could silently
change behavior, tests compare against a brute-force *oracle*: the query planner,
for instance, is checked against naive intersection over every 1-, 2- and 3-term
query on fixtures and on randomized DAGs, in every planner mode. The persistence
layer gets the same treatment (fuzzed against a plain dictionary; canonical roots
asserted under arbitrary edit histories).

## 8. Where this is going

The project's roadmap — what is delivered, what is queued next, what is parked
behind explicit triggers, and what is research horizon — lives in its own file:
**[ROADMAP.md](ROADMAP.md)**. Longer-term goals for OntoDAG as a database, and the
conventional database features deliberately *not* being built yet, are in
`DATABASE_DIRECTION.md`; the day-to-day task list is in `CLAUDE.md`.

The common thread through all of it: keep the core exact and small — one graph,
one invariant set, one query — and let everything else (storage, speed, sharing,
learning) be a layer that *earns* its place around that core.
