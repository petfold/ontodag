# Sharing: What One Store Shows Another

Status: discussion draft (2026-09-24). **Built so far (unreleased, for
0.28.0):** `ontodag.sharing` — `reach`, `landing`, `losses` — and the CLI's
`shared-with` and `get`/`count --as` (§7, steps 1–2); principals are named
by the caller until Q1 is settled. Everything else here is proposed. categor.io, a website over OntoDAG, implements a version of the
rule server-side (its `docs/DESIGN.md` §4–§10); this record proposes which
part of that belongs in OntoDAG, and how it meets the three mechanisms
OntoDAG already has for more than one reader: overlays
([PROJECTIONS.md](PROJECTIONS.md) §5), category access control
([act-categories/DESIGN.md](act-categories/DESIGN.md)) and reader-side
trust lists ([../AGENT_SURFACE.md](../AGENT_SURFACE.md)).

## 1. The problem

OntoDAG answers questions about *a* store. Everything that combines stores
assumes they have one reader:

- **Overlays** compose a person's own layers — their store and the machine
  projections beside it — by merging them into one in-memory DAG and
  answering from that. For one reader this is exactly right.
- **For several readers it leaks.** Subsumption is transitive, so in a
  merged graph Bob's `rex ⊑ dog` puts `rex` below `dog` for everyone who can
  see `dog`. Classifying something under a shared category would publish it.
- **ACT** gates *content* with keys but leaves structure visible (its §6),
  and says so: "claims within one canonical store cannot have per-reader
  visibility".
- **Trust lists** (`review`) decide which *signed claims* a reader accepts,
  not what a reader may see.

What is missing is one rule that says **what store O shows reader R**, which
a server can evaluate (categor.io), which `ontodag-fs` could apply when it
mounts a colleague's Swarm store, which an agent surface serving a store to
many users needs, and which ACT would enforce with keys instead of a server.

## 2. The rule

Some nodes are **principals**: names that stand for a reader. categor.io
spells them as addresses, `ada@categor.io`; how OntoDAG should recognise
them is §6 Q1.

> **R sees node x of O's store iff x is below one of R's principals in O's
> store** — evaluated in O's store alone, never in a merge of stores.

Call that set **reach(O, R)**: the cone of R's principals in O. Sharing is
therefore filing: O files a category under `ada@…` to share it with her,
and everything below it goes along. A **group** is a category filed under
several principals; things filed under the group reach all of them.

Everything else follows from the one rule, and categor.io's tests pin each
point (its `tests/test_site.py`, `test_acme`):

- **Parents stay closed.** Acme files `employee-information` under its
  private `merger-plans`; Ada sees `employee-information`, not
  `merger-plans`. A parent is not below the principal.
- **Members don't see each other.** `employees ⊑ ada`, `employees ⊑ bob`:
  the principals sit *above* the group, and Ada sees only what is below her.
- **Groups nest by the order itself.** `employees ⊑ sales ⊑ harry` gives
  Harry everything employees have; no one outside sales sees sales
  material. More access means more below you.
- **Classifying is private.** Bob's `rex ⊑ dog` is an edge in Bob's store;
  `dog`'s cone in anyone else's evaluation does not contain it, because the
  rule never reads two stores at once.
- **Only O can share O's things.** Reach is computed from O's own edges, so
  nothing another store asserts can widen it.

A host adds its own policy on top (§5): categor.io also requires R to have
*accepted* O (O's principal filed in R's store) and refuses anything filed
under an address before that address existed. Neither is part of the rule.

### 2.1 Reach is a down-set, which makes the projection honest

PROJECTIONS and ACT both warn that "the public view of a reduced private
graph is not the reduction of the public view". That is true of an
arbitrary subset. It is **not** true of reach, because reach is closed
downwards: if y is in reach and x ⊑ y, then x is in reach.

For two members x ⊑ y of a down-set, every node on every path between them
is below y, hence in the set. So the subgraph induced by reach has exactly
the reachability of the store restricted to it, and its transitive
reduction is the store's reduction restricted to it. What R is shown is
therefore a faithful, canonical piece of O — not an approximation —
and only edges that leave the set (to parents above it) are cut, which is
the point. A host may show a cut parent when R can see it by another right
(categor.io shows public-vocabulary parents).

### 2.2 The combined order, not just asserted edges

categor.io walks asserted edges. OntoDAG's reach should be
`O.get([principal])` — the same combined order `is_below` uses, including
computed containment of typed values — so that "x is shared with R" is
`O.is_below(x, principal)` and inherits its guarantees (G4 fail-closed; §4
certificates). The difference only shows when a typed value is filed under
a principal (`time(2026) ⊑ ada@…` then reaches everything filed at
`time(2026-08)`), which is what the order says it should do.

## 3. It is ACT's rule, drawn in one direction

ACT draws two halves with opposite key directions — people keys flowing
upward (`alice → eng-dept → company`), document keys downward — joined by
bridge edges from a people node to a document category. Written as
OntoDAG edges, with each token `u → v` read as `v ⊑ u` ("v is held by u"),
both halves point the same way:

| ACT (act-categories/DESIGN.md §2.2) | This rule (in O's store) |
|---|---|
| token `alice → eng-dept` (Alice holds the department key) | `eng-dept ⊑ alice@…` |
| token `eng-dept → company` (the department derives the company key) | `company ⊑ eng-dept` |
| bridge `eng-dept → eng-documents` | `eng-documents ⊑ eng-dept` |
| document keys flow down, `eng-documents → doc-42` | `doc-42 ⊑ eng-documents` |
| a reader decrypts iff a token path runs from their leaf to the document | x ∈ reach iff `x ⊑* alice@…` |
| the design trap: never file a document category under another by audience | the same trap: filing under a shared category shares |

So there is one definition with two enforcements:

- **Server-enforced** (categor.io): reach is computed and only reach is
  served. The structure outside reach stays hidden, and revocation is an
  edge removal.
- **Key-enforced** (ACT): the token set is exactly the edges of the reach
  cones, so the same stores yield the same grants with no server. Structure
  is visible (ACT §6), and revocation is an epoch rotation (ACT §2.7).

**Proposal:** `ontodag.act` derives its token plan from reach instead of
from a separately declared people/document split. Then a store shared
through a server and the same store published to Swarm with ACT grant the
same things, by construction.

## 4. What OntoDAG would provide

A module, `ontodag.sharing`, standard library only (B1), over any DAG
(eager, sparse, or a read-only lazy view of a published root):

| call | returns |
|---|---|
| `reach(dag, principals, exclude=())` | the frozenset R may see in `dag`: the union of `dag.get([p])` over R's principals, walked so as never to enter a name in `exclude` |
| `landing(dag, principals, exclude=())` | for each principal, the names filed directly under it — where shares arrive |
| `losses(before, after, principals)` | `{principal: names}` that one state shows and the next does not, per principal — the check before an edit (categor.io's "This stops people seeing things"). The principals are named: nothing in a store says which names they are until Q1 is settled |
| `SharedView(own, sources)` | a read-only composed view: the reader's own store, plus `(store, reach)` pairs, answering `get`/`is_below`/`browse` per source and uniting the answers — the **filtered overlay** (§4.1) |

The CLI gains what a single user needs when publishing a store to others,
because the question "what does Bob see?" arises the moment a `swarm:`
store is shared, server or not:

- `odag shared-with PRINCIPAL` — reach, listed like `get`;
- `odag get --as PRINCIPAL CAT…` — any query, answered from reach only;
- `odag remove/move --dry-run` report `losses` beside the contested set
  (the "residual access report" ACT §2.7 already asks for). This one waits
  for Q1: a dry run has no principals to ask about until a store can say
  which of its names are principals.

### 4.1 Filtered overlays

Today's overlays merge whole stores, which is right for one principal's
layers. A **filtered overlay** contributes only a reach to the view, and is
never merged: each source answers from its own edges, and the view unites
the answers. PROJECTIONS §5 already notes that "the composed read view
needs no cross-layer re-reduction to answer queries: cones are
reduction-invariant"; per-source evaluation keeps that property and adds
the one categor.io depends on — a source's edges never meet another
source's edges. `Session.view()` would accept both kinds.

### 4.2 Contract

Nothing in G1–G6 changes: the rule reads stores and writes nothing. A new
clause is proposed once built:

> **G7 — Reach.** reach(O, R) is a down-set of O computed from O alone;
> `x ∈ reach` iff `O.is_below(x, p)` for one of R's principals p. It grows
> under merge into O (G2's argument) and may shrink under a local `remove`
> or `move`, with G2's note: living answers are advisory, root-pinned ones
> are facts.

Membership is then certifiable with what exists: a certificate for
`is_below(x, p)` against O's root is a proof that x was shared with R as of
that root, verifiable by anyone holding only the root (ACT §2.7 noticed the
same for grants).

## 5. What stays with the host

These are policy, and differ between a website, an agent surface and a
personal Swarm store:

- **Who a principal belongs to**, and logins.
- **Consent.** categor.io shows a share only after R has filed O's
  principal in R's own store, with requests (name and count only) until
  then, and blocking. This is a reader-side trust list over *stores*, the
  analogue of `review`'s trust list over *claim authors*; the two could
  share a shape later (§6 Q3).
- **Addresses that don't exist yet.** categor.io records, when an address
  is registered, what already sat below it in other stores, and passes that
  as `exclude` forever: a grant cannot wait for its holder to appear, or
  unregistered names become a hunting ground (categor.io DESIGN §10).
- **Never reusing a principal**, for the same reason.
- **What else a reader is shown** of a shared node's parents (§2.1).

## 6. Open questions

**Q1 — How does OntoDAG know a principal?** This is the real design
question, because principals collide with how OntoDAG already uses
addresses. PROJECTIONS §2 files an address in the human layer as an
ordinary category, `alice@acme.com ⊑ Alice ⊑ Acme ⊑ work`, and a mail
projection would file Alice's messages under her. Under the rule,
anything filed under `alice@acme.com` is shared with Alice. The same name
would mean "from Alice" in one store and "for Alice" in another. Options:

- **(a) The caller names the principals** (`reach(dag, ["ada@…"])`). The
  library stays neutral and the host decides. Nothing in a store says what
  is a grant, so a store's meaning depends on who reads it.
- **(b) Principals are declared**, like dimensions: a principal is a node
  filed under a registry node (`principal`, alongside `dimension`). A
  store then says which of its names are grants, and that travels with it.
  Hosts that also keep "from" facets keep those under `sys:` or under the
  person's category, never under the principal node.
- **(c) A role term**, `shared-with(alice@…)`, as a head of its own. This is
  rejected: role heads order covariantly (DIMENSIONS §14,
  `R(x) ⊑ R(y)` iff `x ⊑ y`), which is the wrong direction for groups —
  what sales may see must *contain* what employees may see.

*Leaning:* (b) for stores that travel, with (a) as the library's actual
parameter, so a host can still say "these, and only these".

**Q2 — Redundant grants vanish.** OntoDAG stores the reduction: after
`employees ⊑ sales ⊑ harry`, Acme's explicit `employees ⊑ harry` is gone,
and removing Harry from sales then removes both. categor.io mitigates this
with `losses` before every edit and "through a group" labels. OntoDAG
could do better: provenance subjects are **claims, not edges**
([../PROVENANCE.md](../PROVENANCE.md) — an asserted claim stays recorded
when a later edge makes it redundant). A grant recorded as a claim can
therefore be re-asserted when the path that implied it disappears. Is that
wanted, or is "grants are the order, nothing more" the cleaner stance?

**Q3 — Consent in OntoDAG, or only in hosts?** A reader-side list of
accepted stores has the same shape as `review`'s trust list. Unify them
(`trust` over authors *and* stores), or keep consent a host concern?

**Q4 — ACT alignment, in detail.** Deriving tokens from reach (§3) needs
epoch handling for the edits `losses` reports (ACT §2.7 already lists
them). Is the token plan a pure function of (store root, principals)? It
should be, for G1's sake.

**Q5 — Cross-store names.** Filing *your* thing under *O's* shared node,
so that one company vocabulary is used by many stores without copies.
categor.io needs this for company packs (it currently refuses per-user
pack copies for memory reasons). It needs names that survive between
stores, which OntoDAG has so far declined (PACKS.md principle 4: names are
identity). This is out of scope here, but the next question after this one.

**Q6 — Scale.** `reach` over a published store is `get([p])` on a
`LazyOntoDAG`: it fetches only the cone. With cone summaries
(`ontodag.cones`) a broad grant costs its summary, not its cone. Is that
enough for an agent surface answering many readers, or does reach want an
index of its own?

## 7. Build order (proposed)

1. **`ontodag.sharing`**: `reach`, `landing` and `losses`, with the tests
   ported from categor.io's scenarios (Acme's groups and departments, the
   private parent, members not seeing each other, the pre-registration
   exclusion as `exclude`). categor.io then drops its own copies.
   **[Built, unreleased: `tests/test_sharing.py`.]**
2. **CLI:** `shared-with`, `get --as`, and losses in `--dry-run`. This is
   single-user value, and it makes the rule inspectable by anyone.
   **[`shared-with` and `get`/`count --as` built; `--dry-run` losses wait
   for Q1.]**
3. **Filtered overlays** in `Session.view()`, and `SharedView` for hosts.
4. **Q1 settled** (principal declaration). Before this, principals stay a
   caller parameter.
5. **ACT derivation** from reach (Q4), when ACT Phase 1 resumes.
6. **G7** into CONTRACT.md after a review round, as G6 was.

Each step is additive; nothing existing changes meaning.
