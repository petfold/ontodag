# Provenance: Attribution Without Breaking the Root

Status: **agreed design, 2026-08-01 (Peter + Claude) — drafted, reviewed and
agreed the same day; all open questions resolved (the review record is §8).
The store layer is IMPLEMENTED** (same day, Phase 2 first movement):
`src/ontodag/provenance.py` — claim-grain subjects, the four signed record
types with `v` + namespaced `ext` from day one, `s/<subject-hash>/<record-
hash>` content-addressed keys (set semantics; re-assertion is deliberately a
new record), real secp256k1 signing via the same `bee` package the feed
pointer uses (duck-typed seam, lazy import) with `verify_record`, and
conflict-free direction-independent `union` for the per-writer deployment
shape. Tests: `tests/test_provenance.py`. **The write surface is implemented too**
(same day): `odag-mcp --write` — propose → canonical echo → confirm with a
deterministic proposal token recomputed against the current root (a moved
store refuses the stale confirmation), one signed assertion record per
claim beside every knowledge change, and `remove` emitting its retraction
records per §3's coupling rule; per-writer provenance lives in the
`NAME-prov` sibling store. See `AGENT_SURFACE.md` §6. **Not yet
implemented:** the endorsement/review workflow (§5) — required before
writes run at any volume. §7 records
the economic extension of this layer — bonded assertions, designed in the
**factbond** sister repo. One flagged residual: the
`payload(name, content-hash)` subject form (§3) is sketched, not worked —
and deliberately not implemented.

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

- A **provenance store** maps a *subject* to a set of signed provenance
  records. **Subjects are claims, not edges (decided 2026-08-01):** the
  ordered pair of canonical names `sub ⊑ sup` — stable under reduction and
  merge, where a stored edge is not (reduction can prune an asserted edge
  whose claim stays entailed: assert `X⊑A`, then `X⊑B, B⊑A` arrives and the
  edge vanishes from the canonical form while `is_below(X, A)` stays true).
  Node existence is the claim `X ⊑ *`; payload/meta attribution uses a
  `payload(name, content-hash)` subject form (sketched, not yet worked).
  Subjects are adversary-computable — any party derives the same subject
  from the same claim, parametric spellings already collapsed by
  canonicalization — which is what a later bonded claim needs (§7). An
  optional deterministic `group` field, the hash of the canonically-encoded
  operation `{op, item, supers sorted, basis root}`, links the several
  claims of one intentional act (`put(X, [A, B])`).
- The store merges by **union** — attributions are monotone facts about
  speech acts ("K said X"), so two provenance stores merge without conflict,
  and re-syncing is idempotent. **No semantic canonical form is needed**
  (decided 2026-08-01): there is no reduction or entailment on speech acts,
  so set equality is the only equality, and the trie's sorted encoding
  already gives "same attributions ⇒ same provenance root". Records are
  keyed `s/<subject-hash>/<record-hash>` — set semantics by content address
  (duplicates dedupe), subject-prefix lookup via the existing
  `keys(prefix)`, union merge via the or-set resolver pattern loopmarket
  already validated.
- Publication is a **pair of roots** `(knowledge_root, provenance_root)`,
  pinned together the way cone-index manifests pin
  `{data_root, registry_version}`. The knowledge root stays pure; a verifier
  who only cares about *what* is agreed never fetches provenance; a reviewer
  who cares about *who and why* fetches both.
- The knowledge-store schema changes **not at all**. This is the B1-shaped
  property of the design: provenance is layered beside the data, never inside
  it, and a store without a provenance sibling remains fully functional.

Record shapes (all signed over content-addressed data, so verifiable per
`CONTRACT.md` Tier 2). Every record carries a schema version `v` and a
**namespaced extensions map** from day one (decided 2026-08-01 — the
contract's annotations-slot move applied to records; factbond's
`bondRef`/`confidence`/liveness ride there when they arrive); readers ignore
unknown record types, fields and namespaces, and the store manifest pins
`{format, schema version}` cone-index style:

| record | fields (beyond `v`, extensions, signature) |
|---|---|
| assertion | subject, author key, basis `knowledge_root` the author wrote against, `origin: asserted \| derived`, `derived_from: (corpus_root, learner_version)?`, time? |
| endorsement | subject, endorser key, basis root, time? |
| retraction | subject, author key, basis root, time? |
| binding | key, canonical name, basis root, time? — the self-signed key↔name link, endorsable by others (a web-of-trust edge). It cannot be a knowledge edge: "K speaks-for N" is a *relation*, which is walled — so it lives here as a speech act, disputable and endorsable like the rest. The knowledge graph never stores key material. |

Timestamps are **part of the signed claim** — "K says it was Tuesday" —
useful for ordering heuristics and review UIs, never load-bearing for merge
or identity; anchored time (feed index, on-chain anchor) is the upgrade
path, and its natural customer is factbond's liveness windows, so it belongs
to that contract. The same claim re-asserted later by the same key is
deliberately a *new record*: "I still stand behind this against root R₂" is
audit information.

**Retraction is a speech act, not a deletion.** It records "this key no
longer stands behind this claim"; the knowledge-level grow-only stance
(`CONTRACT.md` G2) is untouched, and readers weigh retractions exactly as
they weigh endorsements — by policy. This gives `remove` a principled
companion instead of a fight with merge-as-union.
**Coupling rule (decided 2026-08-01):** on the agent write surface, a
knowledge-level `remove` **must** emit the matching retraction record in the
same published pair — the audit trail never has silent disappearances, and
the agent surface is exactly where audit is the point. Direct human
CLI/library use: recommended, unenforced. The coupling lives in the write
surface, never in `dag.py` — the core stays provenance-free (the B1
discipline).

**Deployment shape (decided 2026-08-01): per-writer stores.** Each writer
publishes their own provenance store under their own signed feed; readers
and aggregators fold exactly the stores they *choose* by union merge
(O(divergence) on the canonical trie) — loopmarket's one-book-per-maker
shape, same machinery. Admission is by **reference, not write access**, so
spam needs no store-side mechanism (no quotas, no stake): a flooder is
simply un-merged, and "everything K ever asserted" is auditable and
revocable as a unit. Economic spam pricing (assertion fees) arrives later as
factbond's layer.

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

## 8. Review record (2026-08-01 — all open questions resolved)

Reviewed with Peter the same day the note was drafted; all seven resolutions
accepted and folded into §3 above. Kept here so the decisions and their
reasons stay findable:

1. **Subject identity** → **claims, not edges** (§3). The draft's edge-grain
   lean was found broken against the core's own behavior: transitive
   reduction can prune an asserted edge whose claim stays entailed, so an
   edge-grain subject dangles under canonicalization. Subjects are
   `sub ⊑ sup` canonical-name pairs (`X ⊑ *` for existence,
   `payload(name, content-hash)` for payload — the one sketched-not-worked
   residual), plus the deterministic operation `group` hash linking one
   intentional act's claims.
2. **Semantic canonical form** → not needed: no reduction or entailment
   exists on speech acts, so set equality is the only equality.
   Content-hash keys under subject-hash prefixes; union merge via the
   or-set resolver already validated in loopmarket.
3. **Timestamps** → part of the signed claim ("K says it was Tuesday"),
   never load-bearing for merge or identity; anchored time is the upgrade
   path and belongs to factbond's contract (liveness windows).
   Re-assertion is deliberately a new record — audit information.
4. **Author identity** → `binding` records, the fourth type: self-signed
   key↔name links, endorsable by others (web-of-trust). Never a knowledge
   edge — "speaks-for" is a relation, which is walled. The §12
   identity-vs-relation fork resolved the same way once more: the binding
   is a claim (merges); whose binding you trust is policy.
5. **Spam and volume** → per-writer stores folded by explicit choice
   (§3 deployment shape). Admission is by reference, not write access, so
   no store-side quotas or stakes: un-merge the flooder. Economic pricing
   (assertion fees) is factbond's layer.
6. **`remove` coupling** → required on the agent write surface (retraction
   record in the same published pair), recommended-unenforced for direct
   human use; the coupling lives in the write surface, keeping the core
   provenance-free (§3 coupling rule).
7. **Schema versioning** → `v` on every record; unknown record types,
   fields and namespaces ignored; manifest pins `{format, schema version}`;
   and a namespaced extensions map per record — the contract's
   annotations-slot move applied to records, where factbond's fields ride.
