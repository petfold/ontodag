# Provenance: Attribution Without Breaking the Root

Status: **design note / discussion draft, 2026-08-01 (Peter + Claude).
Nothing implemented.** What *is* agreed: the agents-first decision
(`CONTRACT.md` §1) promotes provenance from the roadmap's research horizon to
a prerequisite — no agent write path ships before this note is settled. The
proposal in §3 is argued, not decided; open questions in §8. §7 (added later
the same day) records the economic extension of this layer — bonded
assertions, designed in the **factbond** sister repo.

Read first: `SWARM_DESIGN.md` §8 (the original provenance sketch this note
amends), `CONTRACT.md` §6–§7 (the obligations and verifiability clauses that
consume it), `SURFACE_LAYER.md` §14 (the risk that makes it urgent).

## 1. Why now

Agents write faster than anyone can review. Canonicity makes duplicates free
to *detect* and does nothing to make content *good* — that was §14's risk
paragraph, and its sketched mitigation was provenance plus endorsement. The
moment a model writes to a shared store, "who asserted this, on what basis,
and who has endorsed it" stops being a nicety and becomes the whole safety
story. It is also the substrate for three things already designed elsewhere:
eviction policy (regenerable vs irreplaceable, `SWARM_DESIGN.md` §6),
shared-vs-personal sync routing (§5), and the audit surface agents need
(`CONTRACT.md` §7's L1: trust decisions made explicit).

## 2. The constraint that shapes everything

**Attribution must not enter the knowledge root.**

The flagship guarantee (`CONTRACT.md` G1) is that equal knowledge yields an
equal root — two parties prove agreement by comparing one hash. If
who-said-it lives in the node records, the same knowledge asserted by
different authors produces different records, hence different roots, and
agreement-by-fingerprint dies. The same applies to `origin: asserted|derived`
tags, timestamps, and confidence: all of them vary between honest replicas
that hold *identical knowledge*.

This amends `SWARM_DESIGN.md` §8 in exactly one respect. Its taxonomy
survives untouched — `asserted` vs `derived`, `derived_from: (corpus_root,
learner_version)`, `endorsed` — but its "tag every node" cannot mean fields
in the node record. §8 was explicitly written as "no schema field yet"; this
note is the reason there will never be one *in the knowledge record*.

## 3. Proposal: a parallel provenance store

The project already has the pattern: cone indexes are a separate store with
its own root, published beside the data root, manifest-pinned
(`cones.py`). Provenance is the same move with different content:

- A **provenance store** maps an *assertion identity* (§7.1) to a set of
  signed provenance records. It merges by **union** — attributions are
  monotone facts about speech acts ("K said X"), so two provenance stores
  merge without conflict, and re-syncing is idempotent.
- Publication is a **pair of roots** `(knowledge_root, provenance_root)`,
  pinned together the way cone-index manifests pin
  `{data_root, registry_version}`. The knowledge root stays pure; a verifier
  who only cares about *what* is agreed never fetches provenance; a reviewer
  who cares about *who and why* fetches both.
- The knowledge-store schema changes **not at all**. This is the B1-shaped
  property of the design: provenance is layered beside the data, never inside
  it, and a store without a provenance sibling remains fully functional.

Sketched record shapes (all signed over content-addressed data, so
verifiable per `CONTRACT.md` Tier 2):

| record | fields (sketch) |
|---|---|
| assertion | subject, author key, basis `knowledge_root` the author wrote against, `origin: asserted \| derived`, `derived_from: (corpus_root, learner_version)?`, time?, signature |
| endorsement | subject, endorser key, basis root, time?, signature |
| retraction | subject, author key, basis root, time?, signature |

**Retraction is a speech act, not a deletion.** It records "this key no
longer stands behind this claim"; the knowledge-level grow-only stance
(`CONTRACT.md` G2) is untouched, and readers weigh retractions exactly as
they weigh endorsements — by policy. This gives `remove` a principled
companion instead of a fight with merge-as-union.

## 4. What survives from the §8 sketch, and where it moves

Every *use* §8 gave provenance works as well or better from a side store:

- **Eviction / postage** (§6): "derived ⇒ regenerable ⇒ droppable" is a
  local storage policy, read at stamp-management time — it never needed to be
  in the merged data.
- **Sync routing** (§5): "personal assertions durable, derived recomputable"
  is likewise the *deployer's* routing table.
- **mdl-fca integration**: a learner's proposals land as ordinary knowledge
  edges plus `origin: derived` assertion records pinning
  `(corpus_root, learner_version)`; endorsement is how a person promotes one.
  Nothing in the learner boundary (§8's in-memory contract) changes except
  that `put(..., origin=derived)` writes the provenance record beside the
  edge.

## 5. What agents add: two new axes

§8 had one axis — *how* a node came to be (asserted by a person vs derived by
a learner). Agent writes add *who* (a signing key), *when*, and *against what
basis* — because idempotent re-assertion, review queues, and dispute
resolution all need them. The agent write path, end to end:

1. agent proposes; core validates and canonicalizes (the elaboration
   contract, one level up — `CONTRACT.md` O4);
2. **canonical echo**: the agent is shown what will be *stored*, not what it
   typed;
3. on confirm: the knowledge edge lands in the data store, the signed
   assertion record lands in the provenance store, both committed and
   published as the root pair.

Endorsement then implements §14's review mitigation: **claims merge,
acceptance is policy** (the `SURFACE_LAYER.md` §11 criterion doing one more
job). A reader may render, trust, or act only on claims endorsed by keys they
choose — locally, without forking anyone's knowledge root. Volume agent
writes are gated on an endorsement workflow existing, not just this schema.

## 6. Confidence, weights, and everything else that must stay out

Probabilities and weights are excluded from knowledge identity by the
two-axis criterion (`CONTRACT.md` §5). If a consumer needs confidence, it is
provenance-store metadata (a field on the assertion/endorsement record, i.e.
a property of the *speech act*) or it lives entirely outside. The knowledge
store never learns about it either way.

## 7. Guarantees: the third trust leg (factbond)

Added 2026-08-01, after the bonded-statements discussion (the
prediction-markets transcript, now the **factbond** sister repo —
github.com/petfold/factbond, see its `docs/INTEGRATION.md`). The trust story
escalates in three legs: *it follows* (structural proofs, `CONTRACT.md` §7),
*someone said it* (this note), *someone will pay if it's wrong* (factbond —
a bonded assertion whose stake is slashed on successful dispute, plus
information insurance whose premium prices a claim's reliability).

What that means for this design, concretely:

- **The record shapes here are factbond's assertion layer minus money.**
  Its assertion tuple `(claimId, asserter, confidence, bondRef,
  livenessWindow, status)` maps field-for-field onto §3's records: subject +
  basis root = claimId, author key = asserter, §6's confidence = the stated
  confidence (which in factbond acquires an economic *function*: it sets the
  odds-weighted dispute ratio). The deltas are `bondRef` and liveness — so
  the record format should be **forward-compatible with bonding**: reserve
  the fields (or an extensible section) from day one, exactly as loopmarket
  carries `bond`/`oracle`/`arbitrator` in its offer encoding unenforced so
  ids don't churn when the machinery lands.
- **Status is derived, not stored-and-merged.** factbond's
  `Asserted/Certified/Contested/Refuted` is recomputable from the signed
  assertion + dispute records plus a clock — the cone-index pattern again.
  Only speech acts merge.
- **The same root-purity argument applies with more force.** Bonds,
  premiums and status must no more enter the knowledge record than
  attribution does: identical knowledge with different bonding must keep
  identical roots.
- **Subjects must be computable by adversaries.** A bond needs a claimId
  that asserter and challenger derive independently and identically — which
  strengthens the case for edge-grain subjects with canonical encodings in
  open question 1 below.
- **Retraction-as-speech-act is confirmed from the economic side**:
  factbond's `Refuted` emits an authenticated *correction feed*, never a
  corrected database — grow-only knowledge plus provenance-level correction,
  independently reinvented.

## 8. Open questions

1. **Subject identity — what exactly is attributed?** Edges `(child,
   parent)`, nodes, or whole `put` operations? Edge-grain matches merge (a
   merge is a union of edges) but one `put` asserts several edges that form
   one intentional act; an operation-grain subject needs a canonical encoding
   of the operation. Current lean: edge-grain with an optional operation
   grouping field, but this is the first thing to settle.
2. **Does the provenance store need semantic canonical form?** Probably not —
   its records are speech acts, not knowledge; union merge plus the trie's
   sorted canonical encoding should suffice, and "same attributions ⇒ same
   provenance root" follows from that alone. Confirm rather than assume.
3. **Timestamps.** Whose clock, and are they claims (unsigned hints inside
   the signed record) or anchored facts (feed index, on-chain anchor)? The
   cheap honest position: a timestamp is part of the signed claim — "K says
   it was Tuesday" — and anchoring is the upgrade path for when that isn't
   enough.
4. **Author identity.** Bare keys sign, but keys are not people or agents.
   Is there a claim shape linking a key to a name in the graph — and is that
   link itself just another attributed, endorsable assertion? (It is the
   `SURFACE_LAYER.md` §12 identity-vs-relation fork again, wearing
   authentication clothes.)
5. **Spam and volume.** Union-merge means anyone can flood a provenance
   store they can write to. Reader-side filtering by endorsement is policy
   and always works; is anything needed store-side (per-key stores merged by
   reference? quotas?), or is "you merge only provenance stores you choose"
   already the answer?
6. **Interaction with `remove`.** Should a knowledge-level `remove` be
   *required* to carry a retraction record, so the audit trail never has
   silent disappearances? (Lean: yes for agent-mediated writes, unenforced
   for direct human CLI use.)
7. **Schema versioning.** Nothing exists, so there is no migration burden —
   which is exactly why the record format should carry a version field from
   day one.
