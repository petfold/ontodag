# The Contract: What a Higher Layer May Assume

Status: drafted 2026-08-01 out of the strategy discussion (Peter + Claude),
the same discussion recorded in `SURFACE_LAYER.md` Part II — this document is
the one its §13 predicted. The **direction** it records is agreed (2026-08-01):
agents are the priority consumer, the core gains no further expressiveness,
and verification is a first-class offering. The second has one scoped
exception, agreed 2026-10-06: relations to entities as dimension terms,
ordered by a fixed set of kinds in code (§5.1), extended on 2026-10-07 to
narrower relations between their heads. The individual clauses are
marked **holds today** (a restatement of a tested guarantee) or **committed**
(agreed direction, not yet built).

**Contract version: 0.6 — amended 2026-10-10** (0.1 was reviewed and agreed
2026-08-01, 0.2 on 2026-10-06, 0.3 and 0.4 on 2026-10-07, 0.5 on
2026-10-09). 0.2 states what an arrow means (§2), admits
dimensions over nodes as the scoped exception (§5.1), and adds the writer's
obligation that goes with them (O6); 0.3 admits narrower relations between
their heads (§5.1); 0.4 promises that versions within a major only add
answers (G7); 0.5 promises that a spelling or a stored form changes only
with the registry minor (G8), and that a replay does not depend on the
order of what it replays (G9); 0.6 files what a merge brings as a single
write files it, so equal knowledge has one root however it arrived (G1),
with one stated exception for contradictions (G5). The record of every
version is §8. All open questions
from the 0.1 draft were resolved in the same-day review and folded into the
clauses. The version is exposed as
`ontodag.CONTRACT_VERSION`, will be carried by the discoverability record
once the agent surface lands, and is bumped on any clause change.

Companions: `SURFACE_LAYER.md` (where the questions arose, Part II §13–§14),
`DATABASE_DIRECTION.md` (the walls this contract leans on), `PROVENANCE.md`
(the design note gating agent writes), `HOW_IT_WORKS.md` (mechanisms).

## 1. Why this document exists, and for whom

Two consumers arrived at the same interface from different directions:

- an **inference layer** (`SURFACE_LAYER.md` §13) that wants to treat OntoDAG
  as its exact, shareable, extensional substrate and compile what it can down
  to cone intersections;
- an **AI agent** (§14) that reads and writes the store directly and needs
  answers it can *check* and cite rather than restate.

"What an inference engine may assume" and "what an agent may assume" turn out
to be one list, so there is one document. The strategic decision that
prioritizes it (agreed 2026-08-01): **agents first**, with a decent human
interface kept alongside (the surface layer's renderer serves both). The
reasoning in one paragraph: reasoning is now abundant and cheap — every agent
carries a flexible reasoner in its weights — while *agreement* is scarce and
expensive. A model's knowledge is not canonical, not addressable, not
verifiable, not attributable; OntoDAG's is all four. The substrate should
therefore sell guarantees, not expressiveness. (The forty-year KR record
agrees: the fragments that run the world — SNOMED CT, the Gene Ontology,
schema.org — are the *weak* ones; Cyc bet on expressiveness plus hand-built
coverage, LLMs commoditized the coverage, and the expressiveness made the KB
unmaintainable and unshareable.)

## 2. The interface

A higher layer may use exactly this, and nothing else:

- **Operations:** `put`, `get`, `get_any`, `is_below`, `get_overlapping`,
  `remove`, `merge`, `sync`.
- **Roots:** `commit() → root`; read-only snapshots at any root
  (`RecordStore.at(root)` under `LazyOntoDAG`); a followable signed pointer to
  the latest root (`SwarmFeedPointer`).
- **The interpretation context:** the merged declarations in the graph plus
  the pinned `REGISTRY_VERSION` (see G1).

Explicitly *not* part of the contract: the record schema, traversal orders,
planner behavior, residency (eager/lazy/sparse), and any module internals.
Those change; the list above does not, except by revising this document.

### What an arrow means (0.2)

Every name stands for a class of items, and `x ⊑ y` says that every item in
x is in y. The operations are defined against that reading: `get`
intersects classes, `is_below` decides inclusion, and a dimension term is a
class too — `mass(3kg)` is the things that weigh 3 kg, `in(japan)` the
things located in Japan. Typed values always worked this way; 0.2 makes it
the reading for every name. The core cannot check that writers keep to it
(it cannot tell a person from a place), so keeping to it is the writer's
obligation, O6.

### Capabilities, not tools

The contract promises *capabilities* — conjunctive and disjunctive query,
fits-within, overlap candidates, per-item description, canonical echo, and
discoverability ("learn what a store is about without downloading it") — and
stays silent on tool inventories. The concrete agent surface (the MCP tool
list, request/response shapes, the discoverability record's fields) is
specified in `docs/AGENT_SURFACE.md` (shipped 2026-08-01 — `ontodag.mcp`:
read-only by default, an opt-in provenance-coupled write surface, and the
review workflow). Two constraints on that surface *are* contract-level,
decided at the 2026-08-01 review:

- **The discoverability record never lives inside the knowledge store.** A
  summary stored in the trie would make the root depend on a description of
  itself (counts change the record, the record changes the root). It is
  derived — computed on demand by the surface, or published *beside* the
  store, manifest-style, the way cone indexes are.
- **Answers are extensible objects, never bare lists.** Every answer carries
  a namespaced `annotations` map (e.g.
  `annotations.factbond = {status, confidence, capital}`); unknown
  namespaces must be ignored; each namespace's semantics belong to its own
  contract, not this one. The slot exists before anything fills it, so
  answer shapes don't churn when guarantee machinery arrives.

## 3. The guarantees

- **G1 — Canonical root.** Equal knowledge yields an equal root: the stored
  form is a *semantic* canonical form (unique transitive reduction; dimension
  values canonicalized by denotation), not a syntactic one. Build history,
  insertion order, and spelling of equal denotations do not affect the root,
  nor does whether a fact arrived by `put` or by a merge: since 0.6 a merge,
  a sync and a load file an item left under two overlapping values of one
  head under their meet, as `put` does, and a value is kept only while
  something is filed under it or it is filed under an ordinary category,
  so the stored form is a function of what is filed: `x` under
  `mass(2kg..5kg)` and `x` under `mass(..5kg)` and `mass(2kg..)` are one
  root.
  Relativity clause: "knowledge" is read against the interpretation context —
  declarations that merge with the data, plus `REGISTRY_VERSION`. **Holds
  today** (eager/sparse root-equality oracles, every order of puts and every
  grouping of merges in `test_unused_values.py`; live canonical-root runs
  on real Swarm refs).
- **G2 — Monotonicity under merge.** Merge is union followed by
  re-reduction. `is_below` answers that are true stay true; `get`/`get_any`
  results only grow. Two documented exceptions: a `remove` loses to a
  concurrent re-add (the grow-only stance); and a value node nothing is
  filed under any more is not kept (0.6), so it can leave a `get` answer
  it was listed in. An item never leaves one, and no `is_below` answer
  changes, since a value is below its head whether or not its node exists.
  **Holds today** (I7, `test_multiwriter.py`).
  *Note (2026-08-01 review):* monotonicity is a property of **merge**, not
  of the timeline — a local `remove` may shrink answers between commits.
  Living-store answers are therefore advisory for anything that caches;
  only root-pinned answers are stable facts (a root is immutable, so an
  answer cited with its root is valid forever *as a statement about that
  root*).
- **G3 — Determinism.** Same root, same interpretation context ⇒ the same
  answer sets on any replica and any residency. **Holds today**
  (`test_lazy.py` eager-oracle equivalence; deterministic ordering pinned by
  `TestTopologicalSortIsDeterministic`).
- **G4 — `is_below` is fail-closed.** It answers true only when the graph
  plus dimension arithmetic *witness* it; false means "not derivable", never
  "unknown but plausible". This is what makes it verifier-shaped. **Holds
  today.**
- **G5 — Convergence.** Writers who fold in each other's published roots
  (`sync`) reach byte-identical roots regardless of gossip order. **Holds
  today** (two- and three-writer tests). *One exception (0.6):* for an item
  whose values of one head cannot all hold, a contradiction only a merge
  makes, which root the writers agree on can depend on the order of the
  merges, because folding values into their meet forgets which values made
  it. Writers that exchange roots still reach one root among them; `odag
  status` and `contradictions()` list such items, and fixing the facts
  ends the exception.
- **G6 — `get_overlapping` is complete for possibility, silent on
  satisfaction.** Defined only for parametric terms of a declared dimension
  (`ValueError` otherwise). Returns a recall-complete candidate set — every
  present value of the dimension whose denotation provably intersects the
  term's (exact arithmetic, computed from names), plus everything below
  those values — so anything that *could* satisfy the term is included, and
  membership asserts only possible coexistence: the caller's exact check
  (or `is_below`) decides actual satisfaction. Completeness follows from
  the filing discipline: an item's denotation is contained in its value's,
  so any possible satisfier sits under an intersecting value. Not a cone
  (overlap is not transitive), never stored, grows monotonically under
  merge like `get`, same `remove` caveat as G2. **Holds today**
  (`get_overlapping`, 2026-07-31; loopmarket's candidate generation already
  relies on exactly this property).

- **G7 — Monotone versions.** Within one major contract version and one
  major `REGISTRY_VERSION`, a newer ontodag never takes away an answer about
  a fixed store: every `is_below` that was true stays true, and every
  `get`/`get_any` answer stays inside the new one. A newer version may add
  answers (a registry minor that recognizes a new kind computes links the
  older one could not see), never remove them. The one exception is G2's:
  a value node nothing is filed under is not kept (0.6), so it can leave a
  `get` answer it was listed in; an item never does, and no `is_below`
  answer changes. A change that would remove any other answer is a major
  bump, and before 1.0 that means the contract goes
  to 1.0. This is what lets a consumer compare majors only: two offers
  pinned to the same root and to versions within one major mean the same
  thing, read by the newer interpreter (loopmarket's matcher and on-chain
  verifier both rely on it). **Committed** (2026-10-07), and held to by
  `TestG7MonotoneVersions`: a fixed store over every kind
  (`tests/fixtures/g7.od`) with the answers it gave when recorded, which
  must stay answers. The first run of that test found a released bug (a
  value index missing values after a load, 0.30.0) — exactly the kind of
  answer-taken-away it exists for. Loading reads a store and never
  migrates it, which is what keeps G7 true of stores an older release
  wrote: a native file the canonical marker does not vouch for is read as
  a merge of its lines would be (2026-10-09; replaying it through `put`
  instead would have filed the fixture's folded compound as its parts,
  and its name would have left the answers). `ontodag.migrate` is the
  explicit step into the current stored form.

- **G8 — Signalled spellings.** A valid name's canonical spelling, and the
  stored form a given set of filings produces (so its root), change only
  together with `REGISTRY_VERSION`'s minor. Within one registry version
  every release spells every name it accepts the same way, and the same
  filings give the same store and the same root — except where the store's
  own knowledge re-spells a term (a compound relation term whose
  constraints the graph comes to relate takes its current spelling,
  DIMENSIONS.md §16), which follows the store, not the release. A release
  that changes a spelling rule or a stored form bumps the registry minor,
  and its CHANGELOG entry names the `ontodag.migrate` step that brings an
  older store to the new form. So names and roots are comparable as
  identifiers when they were made under one registry version, while answers
  stay comparable across a whole major (G7). Releases before contract 0.5
  did not keep this: 0.30.6 changed how a graph-kind compound is stored,
  and 0.30.7 began re-spelling relation compounds, both within registry
  4.3. **Committed** (2026-10-09), and held to by
  `TestG8SignalledSpellings`: fixed filings over every kind, the spelling
  of inputs over every kind, and the stored form of the filings, recorded
  under registry 4.3 (`tests/fixtures/g8-spellings.json`). A failure means
  a release changes one of them: bump the registry minor, name the migrate
  step, then record the new forms (`tests/fixtures/make_g8.py`). The record
  replayed against 0.30.5 and 0.30.6 fails, against 0.30.7 and later it
  holds.

- **G9 — Replays are order-free; single writes are checked as they come.**
  A *replay* — merging a peer, syncing, loading a stored file, ingesting a
  projection stream — reaches the same store from the same filings in
  whatever order they arrive (and so, by G1, the same root). A *single
  write* (`put`, `move`, `remove`, the agent surface's write tools) is
  checked against the store as it is at that moment, so a sequence of
  single writes can be refused in one order and accepted in another. The
  cases, each a guard for the person writing:
  1. **What a write names must exist first**: a parent, a category a term
     names, a declared head or unit (a typo guard: `put dog animal` before
     `put animal` is refused, not silently given a new category).
  2. **A role term's place must already be in its dimension**, and a
     category a role term names must be placed inside it (DIMENSIONS.md §14).
     Since 0.6, in a role of `geo` a bare word must name a place already
     filed there, a cell being written by its own name (`from(geo(u2e4x))`):
     `put parcel from(home)` before `home` is placed is refused at once,
     where it used to read `home` as a cell and refuse the place later.
  3. **Of two writes that contradict, the later is refused**: two values of
     one head that cannot both hold, a cycle, something inside itself under
     a strict relation.

  A replay adds every name before any filing and reads a role parameter
  leniently until its place arrives, so cases 1 and 2 never refuse it
  mid-way. On case 3 the replays differ only in how they stay order-free:
  a merge, a sync and loading a stored file are total (they keep a
  contradiction an author would have been refused, DIMENSIONS.md §9, since
  a store a merge made must open again), while `ingest` refuses the whole
  stream, naming the line, and keeps none of it, on disk or in memory;
  once the stream is all in, it also refuses a role parameter still naming
  a category outside its dimension, case 2's end state. Removals and moves are a different matter: they
  do not commute with additions at all (G2's remove note). A script or an
  agent that cannot control the order of its writes uses a replay.
  **Committed** (2026-10-09; until then `ingest` applied its lines as single
  writes, so a role term and its place were refused in either order), held
  to by `TestG9WritesAndReplays` and `TestIngest` (`tests/test_cli.py`).

## 4. The as-of clause (root-pinning)

**Monotone questions may be asked of the living store. Non-monotone questions
must name a root.**

Negation ("under A but not under B"), aggregation beyond the built-in counts,
universal or closed-world readings, and absence claims ("the store does not
contain X") are ill-defined against a growing, merging store — their answers
can shrink, which is why the walls exclude them. But indexed by a root they
are pure, deterministic, eternally-recomputable facts: the root converts
open-world to closed-world *by scoping*, not by decree. "get(A ∧ ¬B) at root
`21728cd9…` = {…}" is an immutable claim anyone can verify by re-execution.

The mechanism **holds today** (`RecordStore.at(root)` + `LazyOntoDAG`); what
is **committed** is naming it at every tool surface (an `as_of` root
parameter on the MCP query tools) and in error text. Corollary for agents: an
agent that needs a closed world does not ask the store to close; it closes
the world itself by pinning.

## 5. Admissibility: the two-axis criterion

`SURFACE_LAYER.md` §13's criterion ("monotone and computable from names"),
sharpened into the two separately-necessary axes it conflated:

1. **Monotone** — merge-as-union survives. Negation, defaults, closed-world
   assumptions fail here. This axis is absolute: lose it and multi-writer
   convergence is gone.
2. **Cheaply, *semantically* canonicalizable** — "equal knowledge ⇒ equal
   root" stays decidable and cheap. OntoDAG's canonical form quotients away
   assertion order (transitive reduction) and value spelling (dimension
   arithmetic). Features can be monotone and still fail this axis: the
   EL-shaped relations extension is monotone (adding axioms only adds
   entailments) but makes subsumption a global inference, so canonicalizing
   up to logical equivalence means canonicalizing an entailment closure —
   research-grade. Until that research is done, "equal knowledge ⇒ equal
   root" silently degrades to "equal *syntax* ⇒ equal root", a far weaker
   guarantee and the one agents actually rely on.

The limit statement: **OntoDAG stays at the largest fragment where
canonicality is semantic and cheap.** Each step up the expressiveness ladder
first degrades the root from a fingerprint of knowledge to a fingerprint of
phrasing — that, not tractability, is the real wall. (There is a precise
precedent for drawing the line this way: EL++ retains polynomial subsumption
only under "p-admissible" concrete domains — the DL community's version of
"only exact-arithmetic kinds enter the canonical order".)

Both axes are **necessary, not sufficient**: computed values
(`transport_duration = arrival − departure`) pass both and should still wait
behind `DATABASE_DIRECTION.md`'s tripwire discipline until a real consumer
exists. The criterion tells you what is admissible; tripwires decide what is
warranted. The feature-by-feature sort lives in `DATABASE_DIRECTION.md`'s
walls (updated 2026-08-01 to name the axis each wall protects).

### 5.1 The scoped exception: dimensions over nodes (0.2)

Relations to entities are admitted as **dimension terms over nodes**: a
head applied to a node, `in(japan)`, `about(mars)`, `shared-with(alice)`, ordered
like any dimension by its head's kind. The consumer is the one meaning
itself (§2): without these terms, "located in Japan" or "about Mars" can
only be said by filing under the entity, which says something false. Three
conditions keep both axes:

1. **Users declare heads, never rules.** A head is a name filed under a
   kind node. How its terms are ordered is the kind's rule, fixed in code,
   each with its own correctness argument and an independent oracle
   (`tests/test_transitive.py`). The kinds over nodes are: *graph*
   (follows the order: `transport(bicycle) ⊑ transport(small-item)` from
   `bicycle ⊑ small-item`; registry 4.2); *transitive* (chains: once
   `tokyo ⊑ in(japan)`, `in(tokyo) ⊑ in(japan)`; strict, with a guard
   against anything being inside itself); *enclosing* (follows `in`
   without chaining: a photo about Tokyo is about Japan); and *reversed*
   (`shared-with(group) ⊑ shared-with(member)`: what is shared with a group is shared with each member).
   All four **hold today**. A new kind is a clause change: it bumps this
   contract and `REGISTRY_VERSION`. A new head never does. Filing a term
   of any of the four under anything but its head would state a rule
   (`in(japan) ⊑ japanese`: whatever is in Japan is Japanese), so `put`
   refuses it.
2. **The order stays a local computation.** Whether `R(x) ⊑ R(y)` holds is
   decided by walking the ancestors of x or y in the store: the kind of
   question `is_below` always answered, never inference over rules gathered
   from the whole store. That is what keeps axis 2: the rules are a fixed,
   finite set, terms are names, and their computed order takes part in the
   transitive reduction, so equal knowledge still reaches an equal root
   (G1). The oracle checks this on random worlds, for filing order and for
   merge; that is evidence, not a proof.
3. **Monotone.** Each kind's rule only adds pairs as edges are added
   (axis 1). The strictness guard refuses at `put`; merge never refuses,
   and a contradiction that arrives by merge is kept as data (O5).

**Narrower relations (0.3)** — **holds today.** A head of a transitive,
enclosing or reversed kind filed under another head of the same kind
names a narrower relation: with `departure` under `from`,
`departure(x) ⊑ from(y)` exactly when `from(x) ⊑ from(y)`, and a broader
term is never inside a narrower one. It is an inclusion between two
heads with no composition, admitted on the terms above:

- *Users still declare no rules.* The declaration is an ordinary edge
  between two heads, and what it means is fixed here, for these three
  kinds only. A head under a head of a value kind stays a role that
  takes its base's values (DIMENSIONS.md §14). The graph kind is left
  out: it was left out while its conjunctions folded (§15), when a
  narrower graph-kind head would have made stored form depend on filing
  order, and admitting it now that they are stored as parts would be a
  clause change of its own.
- *Local.* Deciding `R(x) ⊑ S(y)` walks the heads above R and the
  ancestors of x, as before.
- *Monotone.* A declaration only adds pairs. One made after terms were
  filed re-reduces them, so stored form does not depend on when it came
  (G1). One that would put something inside itself under a strict
  relation is refused at `put`; merges stay total (O5).

Design record: DIMENSIONS.md §20.

**Still outside**, behind the arbitrary-relations wall: rules a user writes
(relation chains such as "member of, then located in, gives located in",
which is false, and is the reason membership is not `in`; see O6); several
relations of one item that must stay paired (BINDING.md's two-leg
journey); relations among three or more things ("Alice gave Bob a book");
and defined concepts (O4).

## 6. Obligations of the higher layer

What the layer above must do *instead of* asking the core for more:

- **O1 — Derived closures stay local and regenerable** (the cone-index
  pattern: separate store, own root, never merged), or — if shared — enter
  the graph as ordinary claims marked with provenance (`PROVENANCE.md`).
- **O2 — Non-monotone answers cite their basis**: (query, root, and where
  parametric terms are involved, the registry version). An uncited
  non-monotone answer is not a fact, it is a snapshot of one.
- **O3 — Write-back is monotone attributed claims only.** No defaults, no
  probabilities, no weights in identity; confidence lives in provenance and
  endorsement metadata, or outside the store entirely. Defeasible reasoning
  happens freely *outside*; only its monotone residue ("K asserted X against
  root R") is stored.
- **O4 — Classification is the higher layer's job.** OntoDAG deliberately has
  no defined concepts (the meet-substitution guard, `SEMANTIC_CODES.md` §10:
  a node under A and B is a *sibling* of the meet, never the meet), so no
  symbolic classifier can place categories automatically. The resident
  reasoner — in 2026, usually an LLM — proposes placements; they land as
  asserted edges with provenance, under the same propose → validate → confirm
  contract the surface layer uses for elaboration. Same pattern, one level up.
- **O5 — Enforcement is local.** Constraint *claims* (a future
  disjointness vocabulary, say) merge like any claim; refusing or warning on
  a violation is per-reader policy, never a merge precondition. Merge stays
  total; an inconsistency arriving via merge is visible, queryable structure
  — `get(Flight, Hotel)` being non-empty *is* the consistency check.
- **O6 — File by the one meaning (0.2).** Kinds (`city`, `planet`) and
  qualities (`blue`, `mass(3kg)`) take items directly. An entity
  (`japan`, `mars`, `alice`) takes only its own instances and phases
  (`medieval-japan ⊑ japan`); whatever else is related to it goes under a
  dimension over it (`in(japan)`, `about(mars)`, `shared-with(alice)`). `in` is for
  places and parts; membership is said by kinds
  (`alice ⊑ sales-employee ⊑ employee`), because membership chained with
  location puts every member wherever the department is. Breaking O6
  breaks no guarantee, since G1–G6 hold for any graph; the answers just
  stop meaning what a reader assumes. After `mars ⊑ planet`, a photo filed
  under `mars` is a planet.

## 7. Verifiability

The crypto-facing half of the contract. Three tiers plus two limits.

### Tier 1 — holds today, by construction

- **Integrity.** A root is a 32-byte commitment to the entire knowledge
  state on content-addressed storage; tampering is detectable on retrieval.
- **Agreement.** Two parties prove they share an ontology by comparing one
  hash — and because canonicality is semantic (G1), this is
  same-*meaning*-same-hash, not same-bytes-same-hash. Independently built,
  differently ordered, differently spelled equal knowledge converges on one
  root. This is the commitment primitive nothing mainstream offers.
- **Localized disagreement.** Differing roots are narrowed to the exact
  differing records by structural trie diff (`RecordStore.diff`,
  recordstore ≥ 0.15.0).
- **Authenticity.** The signed feed gives "root R is the latest state
  published by key K" (live-validated 2026-08-01).
- **Verification by re-execution.** Any answer pinned to a root (§4) is
  deterministically recomputable by anyone (G3). Everything in Tier 2 is an
  optimization of this base case.

### Tier 2 — committed (the two proof items built 2026-08-01)

- **Inclusion and absence proofs from the trie — BUILT (recordstore
  v0.16.0).** recordstore's persistent trie is canonically encoded, so a
  key has exactly one possible location — which makes *non*-membership
  provable by exhibiting the path where the key would live, alongside
  ordinary O(depth) Merkle inclusion proofs. Shipped as
  `RecordStore.prove(key)` + pure `verify_proof(proof, root)` (no store
  access, hash-chain over the raw carried bytes, per the certificate
  policy below). Everything below stacks on it.
- **`is_below` certificates, both polarities — BUILT (2026-08-01,
  `ontodag.certificates`).** As shipped, the design is *re-execution over
  authenticated fragments* rather than bespoke closure rules: the prover
  bundles a recordstore proof (inclusion **or absence**) for every record
  the answer depends on — computed as the order-invariant dependency
  closure, so a verifier whose walk explores a different path is still
  covered — and the verifier re-runs the *real* `is_below` over a strict
  fragment store that serves only proof-verified records. Semantics stay
  single-sourced in the core; a coverage gap fails verification, never
  validates a wrong answer. Both polarities cost the (shallow) ancestor
  cone; the certificate pins `REGISTRY_VERSION` and a mismatched verifier
  refuses rather than misinterprets (L2). This upgrades the agent-facing
  verifier from "trust the store" to "trust nobody": `is_below(X,Y) at
  root R, certificate C` is checkable by a third party holding only the
  root — live on the MCP surface as `certify: true`.
- **`get` soundness certificates** (per-result upward paths to each query
  term). Full `get` *completeness* certificates are possible via the attested
  `down` lists but grow with the cone; re-execution stays the honest answer
  there.
- **Signed provenance and endorsement** — `PROVENANCE.md`; signatures over
  content-addressed data make the audit surface verifiable rather than merely
  recorded.
- **On-chain anchoring.** A root in a contract or event log is a 32-byte
  timestamped commitment. Practical tailwind: Swarm's BMT addressing is
  keccak-based — the EVM's native hash — and Swarm's storage-incentive
  machinery already verifies BMT inclusion proofs on-chain, so
  "contract holds an OntoDAG root, disputes settle by Merkle proof against
  it" is mostly existing pieces. Not a wall; waits only on a consumer.

**Certificate policy (decided at the 2026-08-01 review).** Certificates are
self-describing JSON envelopes — `{format, version, root, subject,
evidence}` — whose `evidence` carries the **raw trie/record blobs**
(hex-encoded). Verification is hash-chain recomputation over those exact
bytes, never re-serialization, which eliminates canonicalization drift by
construction: the bytes that hash to the root are in the envelope. Formats
are versioned by *name*, cone-summaries style — readers ignore formats they
don't know, so new proof formats land beside old verifiers. Transport is
inside tool results but **opt-in** (`certify: true` on the request):
proofs cost fetches, and most calls won't want them. Byte-level specs live
with their implementations — trie inclusion/absence proofs in the
recordstore repo (with `prove`/`verify`), `is_below` certificate envelopes
here.

### Tier 3 — walls (recorded in `DATABASE_DIRECTION.md`)

- **ZK proofs over private ontologies** ("my catalog contains something under
  `mass(..5kg) ∧ location(EU)` — proof, not disclosure"). Tripwire: a real
  privacy-demanding counterparty, loopmarket-shaped. Positioning note worth
  keeping: deterministic canonical encoding, one query primitive, and no
  floats anywhere (values are exact rationals — pairs of integers) make OntoDAG
  unusually circuit-friendly *when* the tripwire fires.
- **Query-completeness SNARKs** — probably never; re-execution is cheap.

### The two limits (state them first, always)

- **L1 — Proofs attest structure, never truth.** Every certificate above
  proves what was asserted and what follows from it — inclusion, subsumption,
  derivation — never that the assertion is true of the world. That is the
  oracle problem; the answer to it is attribution + endorsement
  (`PROVENANCE.md`): whose signature you trust is your trust decision, made
  explicit. Web-of-trust shaped, not oracle-shaped.
  **Extension (2026-08-01): the economic third leg.** The **factbond**
  sister project (github.com/petfold/factbond — bonded assertions +
  information insurance on factual claims, design stage) upgrades "someone
  said it" to "someone will pay if it's wrong": a stake slashed on
  successful dispute, a premium that prices reliability. Two structural
  gifts flow from this side of the fence: claims about an OntoDAG store are
  **canonical and root-pinned**, so a bondable claim identity is free — and
  a root is a *batched* claim (bond millions of facts in one assertion,
  dispute one record via an inclusion proof); and `matches-source` claims
  ("the store at root R entails X") **adjudicate mechanically by Tier-2
  certificate**, making a proof checker the cheapest rung of any dispute
  ladder — only matches-*world* claims need evidence and adjudicators. The
  fit is detailed in factbond's `docs/INTEGRATION.md`; nothing here depends
  on it.
- **L2 — Everything is relative to the pinned interpretation context.** A
  proof about a parametric term must pin the declarations and
  `REGISTRY_VERSION`, exactly as cone-index manifests already do.
  Certificates inherit the discipline; they do not escape it.

## 8. Review record (2026-08-01 — all draft open questions resolved)

Reviewed with Peter the same day the draft landed; all six resolutions
accepted and folded into the clauses above. Kept here so the decisions and
their homes stay findable:

1. **Certificate encodings** → the certificate policy in §7 Tier 2: JSON
   envelopes over raw bytes, hash-chain verification (never
   re-serialization), format-name versioning, opt-in transport
   (`certify: true`); byte-level specs live with their implementations.
2. **Contract versioning** → the version line in the header,
   `ontodag.CONTRACT_VERSION` in code, carried by the discoverability
   record once the agent surface lands. Conformance suite
   `tests/test_contract.py` — one named test class per guarantee (G1–G6),
   importing only the public `ontodag` API — **landed 2026-08-01** (15
   tests, including `TestAsOfClause` for §4; a contract clause now breaks a
   test before it breaks a consumer).
3. **`get_overlapping`'s statement** → G6 (complete for possibility, silent
   on satisfaction; recall-completeness provable from the filing
   discipline — and already what loopmarket's candidate generation relies
   on, so the promise ratifies an existing dependency).
4. **MCP tool list / discoverability record** → scoped out to
   `docs/AGENT_SURFACE.md` (written when that work starts); the contract
   keeps only the capability list and the two contract-level constraints in
   §2 ("Capabilities, not tools"): the discoverability record never lives
   inside the knowledge store (self-reference), and answers are extensible
   objects.
5. **`remove` caveat** → the note under G2: monotonicity is merge-wise, not
   timeline-wise; agents that cite roots have no cache-invalidation problem
   at all.
6. **Guarantee status slot** → the namespaced `annotations` map in §2;
   semantics belong to each namespace's own contract (factbond's, for
   guarantee status), only the slot's existence and ignorability are
   promised here.

### Amendment 0.2 (2026-10-06)

Discussed with Peter over `docs/plans/ROLES.md` (the review of the
swarm-sharing branch, which turned from keys to what a sharing edge
means), and accepted the same day:

1. **What an arrow means** → §2 and O6. "Below" had been used for several
   relations at once: Tokyo below Japan, a photo below Mars, a document
   below the person it is shared with. Each now goes through a dimension
   over the entity.
2. **Dimensions over nodes** → §5.1. The transitive and enclosing kinds
   were built in steps 3.2–3.3 of ROLES.md §9, and the reversed kind in
   step 3.4 (all registry 4.3). Step 3.4 also made the rule explicit that
   a term of a kind the graph orders goes only under its head, after
   random worlds showed that such edges make the order a computation over
   the whole store, exponential in the worst case; Peter: "We expect very
   large graphs, so exponential is out of the question." The conformance
   suite gained `TestDimensionsOverNodes`.
3. **Why the arbitrary-relations wall still stands** → the "Still outside"
   paragraph of §5.1, and `DATABASE_DIRECTION.md`. The exception admits
   fixed rules over declared names, not rules that users write.

### Amendment 0.6 (2026-10-10)

Prompted by the review of 2026-10-09 (`plans/REVIEW_2026-10.md` §8 item
18, decided by Peter as question 12): `put` files an item under two
overlapping values of one head under their meet, and a merge did not, so
Alice's `mass(..5kg)` merged with Bob's `mass(2kg..)` stored the crate
under both while one writer filing both stored it under `mass(2kg..5kg)`:
two roots for one piece of knowledge, a G1 break since 0.26.2. Options:
fold on every replay (chosen), fold and give a contradiction one fixed
"no value fits" form (exact, but that form would answer every query on its
head), stop folding in `put`, or document the exception.

1. **G1** now holds across merges for consistent knowledge: a merge, a
   sync and a load fold as `put` does.
2. **G5 gains a stated exception** for contradictions: a folding merge is
   commutative and idempotent but not associative once values contradict,
   because folding forgets which values made a meet; the root then
   depends on merge order as it already depended on the order of puts.
3. The stored form of merged stores changes, so `REGISTRY_VERSION` goes to
   4.4 (G8); `ontodag.migrate` (which replays through `put`) brings an
   older store along.
4. **G9's case 2 widens** (review question 14, decided by Peter the same
   day): in a role of `geo` a bare word names a place, a cell is written
   by its own name (`from(geo(u2e4x))`), and a write naming a word that is
   no filed place is refused with a teaching error; so is a `geo(...)`
   cell outside the geohash alphabet. Before, any such word was read as a
   cell, so `from(sydney)` filed a parcel in southern Turkey. G7 holds:
   a stored term reads as it was stored, and a query reads a bare word as
   before; `migrate` respells stored cells, in the same registry minor.

5. **A value is kept only while something is filed under it** (review
   question 24, decided by Peter the same day: A), or while it is filed
   under an ordinary category. Found while building item 1: each fold kept
   the meet it made ("a value once named stays"), so three or more
   overlapping values filed one at a time, or merged in different
   groupings, left an unused intermediate meet that depended on the order:
   equal knowledge, two roots. Now a fold, a move, a removal, a merge, a
   sync or a load that leaves a value empty forgets it, and a value `put`
   under its head alone is refused as a write with no effect. **G1** holds
   without a gap; **G2 and G7** gain the sentence that such a value node
   can leave a `get` answer it was listed in, an item never; and a value
   now reads as below its head whether or not its node exists, so no
   `is_below` answer is lost. Peter allowed this change, and only this
   one, to take answers from older stores without a contract major (no
   store is in real use yet); G7's test states the exception exactly. It
   rides registry 4.4, still unreleased; `ontodag.migrate` brings an older
   store along.

### Amendment 0.5 (2026-10-09)

Prompted by the review of 2026-10-09 (`plans/REVIEW_2026-10.md` §5):
loopmarket hashes ontodag's spellings into offer ids, provenance claims and
key-plan keys are names, and a published store is known by its root, yet
0.30.6 and 0.30.7 changed spellings and stored forms with every version
number unchanged. Three options were put to Peter: promise stability within
a major (every canonical-form fix a major bump, before 1.0 a jump to 1.0),
signal changes through the registry minor, or leave it unwritten. He chose
the second:

1. **G8, signalled spellings** → §3, with its conformance test and a record
   that changes only together with a registry bump.
2. **What does not change:** G7 still governs answers, and majors are still
   what consumers compare for them; `REGISTRY_VERSION`'s minor now also
   counts spelling and stored-form rules, not only vocabulary.
3. **G9, replays are order-free; single writes are checked as they come**
   → §3 (the same day, review question 3). The order-dependence of single
   writes is kept, as the guards it is, and stated; the replay that claimed
   order-freedom without having it (`ingest`) was made one. Peter chose
   this over making role terms lenient for authors too, and over replay
   semantics for every write (which would drop the typo and contradiction
   guards). Building review question 4 the same day showed the replays'
   shared leniency had also switched off `ingest`'s guards against
   self-containment and rules, so it is now two: order (every replay) and
   totality (merge, sync, load); `ingest` has only the first. G9's text
   was corrected to match, and to say loading is total.
4. **G7 is kept by loading, not by migrating** (review question 4: a
   native file the marker does not vouch for is read as a merge of its
   lines). Peter chose a fast load for files the marker vouches for and a
   canonicalizing replay through `put` for everything else; built that
   way, the replay failed `TestG7MonotoneVersions`, because it migrated on
   load (the fixture's folded compound was filed as its parts, and its
   name left the answers). So the replay canonicalizes spellings and keeps
   the stored form, and migration stays `ontodag.migrate`'s explicit step.
   This adaptation was made while building and reported to Peter with it.

### Amendment 0.4 (2026-10-07)

Prompted by loopmarket, whose off-chain matcher admitted offers pinned to
different minor versions while its on-chain verifier demanded the exact
versions, so offers written either side of an upgrade matched and then
reverted. Comparing majors is the right line only if ontodag promises that
a minor version never takes an answer away, and semver does not promise
that before 1.0. Peter agreed to write the promise down:

1. **G7, monotone versions** → §3, with its conformance test and a fixed
   fixture whose recorded answers may only grow.
2. **What does not change:** the version line still bumps on any clause
   change; a minor adds, a major may take away.

### Amendment 0.3 (2026-10-07)

Built overnight as ROLES.md §9 step 5 on a branch, in a form proposed
because the declaration was an open question (ROLES.md §8). Peter chose
it the next morning over a separate declaration node and over deferring:

1. **Narrower relations** → §5.1. The declaration is the edge between two
   heads of one relation kind (`departure ⊑ from`), the only reading that
   edge can have for kinds whose argument is any node. Value roles keep
   their meaning, and the graph kind waits for its folding question. The
   conformance suite gained `TestNarrowerRelations`; the oracle is
   `tests/test_narrower.py`.
2. **What stays:** a truck under `max-load(3000kg)` is still below the bare
   head `mass` ("has a mass"). Separating that needs a second
   declaration form for value roles, which nothing has asked for.
