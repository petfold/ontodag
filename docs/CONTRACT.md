# The Contract: What a Higher Layer May Assume

Status: drafted 2026-08-01 out of the strategy discussion (Peter + Claude),
the same discussion recorded in `SURFACE_LAYER.md` Part II — this document is
the one its §13 predicted. The **direction** it records is agreed (2026-08-01):
agents are the priority consumer, the core gains no further expressiveness,
and verification is a first-class offering. The second has one scoped
exception, agreed 2026-10-06: relations to entities as dimension terms,
ordered by a fixed set of kinds in code (§5.1). The individual clauses are
marked **holds today** (a restatement of a tested guarantee) or **committed**
(agreed direction, not yet built).

**Contract version: 0.2 — amended 2026-10-06** (0.1 was reviewed and agreed
2026-08-01). 0.2 states what an arrow means (§2), admits dimensions over
nodes as the scoped exception (§5.1), and adds the writer's obligation that
goes with them (O6); the record of both versions is §8. All open questions
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
class too — `weight(3kg)` is the things that weigh 3 kg, `in(japan)` the
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
  insertion order, and spelling of equal denotations do not affect the root.
  Relativity clause: "knowledge" is read against the interpretation context —
  declarations that merge with the data, plus `REGISTRY_VERSION`. **Holds
  today** (eager/sparse root-equality oracles; live canonical-root runs on
  real Swarm refs).
- **G2 — Monotonicity under merge.** Merge is union followed by
  re-reduction. `is_below` answers that are true stay true; `get`/`get_any`
  results only grow. The one documented exception: a `remove` loses to a
  concurrent re-add (the grow-only stance). **Holds today** (I7,
  `test_multiwriter.py`).
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
  today** (two- and three-writer tests).
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
head applied to a node, `in(japan)`, `about(mars)`, `for(alice)`, ordered
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
   (`for(group) ⊑ for(member)`: what is for a group is for each member).
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

**Narrower relations** (ROLES.md §4, step 3.5) are admissible on the same
terms: a declaration that one head is a narrower relation than another
(`departure ⊑ from`, giving `departure(x) ⊑ from(x)`) is an inclusion
between two heads with no composition. Its form is not designed yet and
will land as its own clause change.

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
  qualities (`blue`, `weight(3kg)`) take items directly. An entity
  (`japan`, `mars`, `alice`) takes only its own instances and phases
  (`medieval-japan ⊑ japan`); whatever else is related to it goes under a
  dimension over it (`in(japan)`, `about(mars)`, `for(alice)`). `in` is for
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
  `weight(..5kg) ∧ location(EU)` — proof, not disclosure"). Tripwire: a real
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
