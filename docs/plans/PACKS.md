# Packs: Published Ontologies, Adoption, Collisions, and Trust

Status: **discussed with Peter 2026-08-20; Part II (§10–§14) records the
decisions.** Part I (§1–§9, the 2026-08-01 draft) is kept as the
discussion record; its §9 sheet is resolved item-by-item in §13, and the
freeze this document used to impose is dispositioned in §14. Where Part I
and Part II disagree (notably §5's dependency manifest), Part II wins and
Part I carries an inline note.

## 1. What a pack actually is (and the naming question)

There is no pack *object* in the system, and perhaps there shouldn't be.
What shipped as "unit packs" is an instance of a pattern the project has
been converging on all week: **a published ontology with a pinned root,
adopted by explicit, idempotent merge.** The same shape already appears
as:

- the **prelude** (standard dimension declarations);
- **unit packs** (vocabulary declarations);
- the planned **lexicon stores** of `SURFACE_LAYER.md` §12 (names and
  translations);
- the **upper-ontology answer** ("don't bake one in — publish it, merge
  it");
- the research-horizon **private overlays** ("your private DAG will be a
  pack too" — Peter, correctly: a company's private subgraph over a public
  base is adoption-by-merge with access control on top).

So "pack" names a **role, not a kind**: *an ontology whose purpose is to
be merged into others*. Whether that role deserves the word "pack" —
versus *overlay*, *module*, *vocabulary*, or simply "a published
ontology" — is genuinely open (§9.1; resolved in §13). The risk of "pack" is that it
suggests a sealed artifact with an installer; the reality is subgraphs
and merge. The risk of having *no* word is that the adoption workflow
(preview, verify, endorse, merge) still needs a name for its object.

## 2. What is shipped today, and its actual trust surface

`ontodag.packs` ships three packs **as code**, distributed with the
package. That means their trust story today is exactly pip's: whoever
trusts `ontodag` trusts its packs — no new trust surface exists yet. The
scary questions in this document are about the step that does *not* exist:
packs distributed by third parties. That step is now **gated on this
discussion**.

What the shipped mechanism already refuses (verified, tested):

- **Redefinition and shadowing of built-ins.** `unit(BTC=1/2ETH)` and
  `unit-family(BTC)` are refused loudly — the shitcoin-named-BTC attack
  fails at the arithmetic layer, because unit declarations carry semantics
  (factors, families) that can *disagree detectably*.
- **Script lookalikes.** Suffixes are ASCII-only, so `unit-family(ВТС)`
  (Cyrillic) is refused at the grammar.
- **Silent adoption.** Nothing merges without an explicit command, and
  merge is idempotent — adopting twice is not adopting harder.
- **Content drift.** Golden roots pin each shipped pack version; a pack
  *is* a fingerprint.

What the mechanism admits, and cannot ever refuse by arithmetic: a
**plausible new name** — `unit-family(XBT)`, a token named almost-BTC, a
category named almost-yours. That is semantic spoofing, and it is a trust
problem (§4), not a grammar problem.

## 3. The collision problem: units are the easy case

Unit declarations conflict *detectably* because they carry meaning.
General node names do not. **`merge` unions same-named nodes silently** —
that is its job, and for shared vocabulary it is exactly right ("your
`Flight` and my `Flight` are one category" is the whole point of
canonical merging). But it means two packs that each define `Mercury` —
planet in one, element in the other — merge into a single wrong node with
**no error**. Nothing in the system can currently even *report* this,
because from the inside it is indistinguishable from agreement.

This is not a new problem: it is the roadmap's **Namespaces** item
(reconciling naming across independent DAGs) and `SURFACE_LAYER.md` §12's
fork — arriving with production urgency, because packs are precisely the
mechanism that makes strangers' names flow into your graph. Positions,
not decisions **[decided 2026-08-20 — §10 principle 4 and §13 items
9.3/9.5/9.7]**:

- **Diff-preview adoption** (cheap, high value, buildable now):
  `odag pack --diff` / a pre-merge report computing what the pack would
  add *and which of your existing names it touches* — collisions become
  visible even where they cannot be refused. `RecordStore.diff` and
  `OntoDAG.merge`-on-a-copy make this mostly plumbing.
- **Same-name-different-parents is not refusable** in general: shared
  vocabulary *should* merge, and whether `Mercury` means your `Mercury`
  is undecidable from names. Structural heuristics (disjoint parent
  cones → warn) can flag, never decide.
- **Namespace prefixes by convention** (`chem:Mercury`) are social, not
  structural — worth a documented convention for pack authors, not a
  mechanism.
- **Provenance-gated adoption**: merge the pack, but record pack-origin
  assertion records for everything it brought (the write surface's
  machinery, replayed for merges) — then `review` can answer "which pack
  said this?" and reader policy can discount un-endorsed packs. Turns
  collisions from silent to *auditable*.

## 4. Security: the shitcoin walk-through, and the trust primitive

The attack Peter named: publish a pack, call your token `BTC`, get
someone to trade against it.

1. Naming it literally `BTC` (or redefining the unit): **refused** —
   conflicts with the built-in table (verified).
2. Homoglyphs: **refused** — ASCII grammar.
3. Naming it `XBT`, `BTCx`, `Bitcoin2`: **admitted** — no arithmetic can
   know it's a lie. From here on, security is trust:

- **The trust primitive is the root, not the name.** You never "install
  BTC support"; you merge a *fingerprint* — one you reviewed, or one
  people you trust endorsed. Adopt-by-root makes integrity free
  (content-addressing) and makes "which pack exactly?" a 64-hex answer.
- **Authenticity**: pack discovery via signed feeds (exists — the same
  `SwarmFeedPointer` machinery), so "the fiat pack, as published by key
  K" is checkable.
- **Endorsement**: the provenance/review machinery generalizes — an
  endorsement record whose subject is *a pack root* ("K stands behind
  root `649b0050…` as the crypto-majors pack") gives web-of-trust over
  packs, and `review` answers "do people I trust endorse this?" *before*
  the merge. (Needs a pack-root subject form in `PROVENANCE.md` — §9.4.)
- **The residue is social**, exactly as in every package ecosystem
  (npm typosquatting is this problem). Our structural advantages over
  name-registry ecosystems: no name race (roots, not names, are the
  identity), refusal on redefinition, explicit merge, and an audit trail
  when provenance-gated adoption lands.

## 5. Do packs form a DAG?

Naturally, yes — and pleasingly, out of existing parts. A pack is
`(root, dependencies = other pack roots, version lineage = its feed
history)`. Adoption is the merge of the dependency closure, and because
merges commute and are idempotent, **adoption order cannot matter** —
the pack graph is a DAG whose "build" is order-free, which package
managers never get to say. Chained unit declarations across packs
already exercise this (a pack may define `kilderkin` in terms of another
pack's `firkin`; unresolved bases refuse loudly and name the missing
pack). Dependencies would ride in a manifest *beside* the pack store
(the cone-index pattern), not inside it. **[Amended 2026-08-20, §10
principle 2: dependencies ship as closure — the pack includes the claims
it assumes — and the manifest survives as provenance metadata only. The
`firkin` case then needs no resolution step at all: the declaration
travels inside.]**

And per `SURFACE_LAYER.md` §11 — build it out of OntoDAG — the **pack
index can itself be an ontology**: packs as items categorized under
`unit-pack` / `lexicon` / `upper-ontology`, values carrying roots,
discoverable with the one query primitive. Who publishes and endorses
that index is an open trust question (§9.6; resolved in §13), not a
mechanism question.

## 6. Where do packs live?

Target state: **Swarm stores with signed feeds** — publish the pack
store (root = integrity), point a feed at it (stable address =
authenticity + updates), adopt by root. Every piece exists and is
live-tested; nothing new is needed except the `odag pack` command
learning `swarm:`/root/feed sources. The shipped `ontodag.packs` should
be understood as **bootstrap distribution** — and there is an honest
irony to name: shipping packs as Python data re-couples vocabulary to
releases, the exact thing graph-declared units decoupled. That is
acceptable for three blessed packs and wrong as a pattern; migrating
them to published stores is the natural next step *after* this
discussion settles the trust workflow. **[Settled 2026-08-20: it is
build-order item 1, §14.]**

## 7. Can we trust packs? (the model in one box)

| layer | mechanism | status |
|---|---|---|
| integrity | content-addressed root; golden-root pins | exists |
| authenticity | signed feed per publisher | exists |
| refusal | unit conflicts, built-in shadowing, grammar | exists, tested |
| visibility | diff-preview before merge | buildable now |
| attribution | pack-origin provenance on adopted content | design needed |
| endorsement | provenance records on pack roots; `review` | subject form needed |
| the residue | lookalike names, semantic spoofing | social; culture + UI |

## 8. The adoption algebra (answers to Peter's sequencing questions, 2026-08-01)

Settled by the merge semantics rather than by choice, so recorded as
facts:

- **Units did not need to wait for this discussion** — the graph-declared
  mechanism is the substrate any pack ecosystem needs, and the rejected
  alternative (everything built-in) would have permanently claimed ~170
  spellings in the code table. Pack claims are soft; built-in claims are
  hard.
- **Code-shipped packs migrate to published packs seamlessly**: pack
  content is deterministic, so publishing today's `crypto-majors` v1 to
  Swarm yields *the very golden root already pinned* — early adopters and
  later adopters converge byte-identically. `ontodag.packs` then shrinks
  to a shim that knows fingerprints.
- **Updates are additive; corrections are interventions.** Merging a new
  pack version can add declarations (idempotent, converging) but can
  never change or retire one — the surviving old declaration meets the
  new one and refuses loudly. Correcting a unit's meaning requires the
  adopter to `remove` the old declaration node deliberately, then adopt.
  This is the right default (a unit silently changing meaning is the
  disaster class) and a real constraint on pack evolution.
- **No name is blocked globally.** Conflicts are per-store: two packs may
  define `XBT` differently and each serve their own communities. If two
  stores that disagree ever merge, the collision surfaces loudly at first
  parse — for units, declarations travel with the data, so cross-store
  collisions arrive *with* the merge instead of hiding inside it. (Bare
  names lack this; that gap is §3.)
- **Built-in claims are for-a-major.** A built-in suffix cannot be
  redefined by any pack while it stays in the table — the argument for a
  minimal table, and for §8.10 below.

## 9. Open questions (the sheet)

1. **Naming**: is "pack" the word, given that preludes, lexicons, upper
   ontologies and private overlays are the same role? Candidates:
   overlay, module, vocabulary, published ontology.
2. **Diff-preview adoption**: build `odag pack --diff` (and the same for
   any merge) as the immediate collision-visibility measure?
3. **Does pack growth wait on Namespaces?** The collision problem *is*
   the Namespaces problem; how much pack ecosystem is safe to grow before
   that research item gets real?
4. **Pack-root subjects in provenance**: the endorsement-of-a-root record
   form (`PROVENANCE.md` addition) — the enabler for web-of-trust over
   packs.
5. **Provenance-gated adoption**: should merging a pack record
   pack-origin assertions for everything it brings (auditable
   collisions), and at what cost?
6. **The index**: an ontology of packs — who publishes it, who endorses
   it, is there more than one?
7. **Compatibility**: unit-level compatibility of two packs is
   *mechanically checkable* (resolve the union of declarations; conflict
   = incompatible). Is that worth surfacing as `odag pack --check`?
   General-name compatibility is only reportable, never decidable.
8. **Migration of the shipped packs** to Swarm distribution, and whether
   `ontodag.packs` then shrinks to a bootstrap shim.
9. **Private overlays**: same mechanism plus access control — does the
   research-horizon item fold into this document?
10. ~~**Tighten the built-in table to pure measurement?**~~ **Accepted
    and done (2026-08-01):** BTC/ETH/BZZ/xBZZ/DAI/xDAI moved to the
    `crypto-core` pack (v1, golden root `4d501a43…`); the built-in table
    (247 suffixes) now holds only what physics fixes, so **no
    market-shaped suffix is hard-claimed for a registry major,
    anywhere**. `sat` costs one `odag pack crypto-core`.

---

# Part II — Decisions (2026-08-20, discussed with Peter)

The discussion this document existed to gate has happened. Part II
records what was decided and why, compactly; the arguments live in the
2026-08-20 session. The headline: **almost everything is forced by the
values** (canonical form, total idempotent merge, monotone-and-
computable, receiver sovereignty, fail-closed), and §12 separates what
was derived from what was bet.

## 10. The principles

First, the languages survey that framed them, distilled to four lessons:
inclusion must be idempotent (C's `#include` is the anti-pattern;
Python's `sys.modules` the fix — our merge is the guard built into the
algebra); pins are content hashes (lockfiles, `go.sum` — adopt-by-root
is our native form); the diamond-dependency problem dissolves under
idempotent union (npm/cargo solve with version solvers what we get
free); and naming is the one genuine fork (qualified names à la
ML/Java/RDF vs. hash-or-opaque identity à la Unison/Nix/Wikidata).

1. **A pack is a store. Full stop.** A published ontology with a root
   (exact pin) and optionally a signed feed (updatable latest). Adoption
   is `merge`; distribution is the existing store tiers (file / `rs:` /
   `swarm:`). Nothing new exists to design, host, or trust. "Pack" stays
   the word (§13, 9.1): it names a *role* — an ontology whose purpose is
   to be merged — not a kind.
2. **Dependencies are closure, not manifest** (amending §5). A pack
   includes the claims it assumes; content addressing makes shared
   closures byte-shared, and idempotent merge makes double-inclusion a
   no-op, so there is no resolver and no version solver. The dependency
   DAG survives as *provenance metadata* ("built from prelude v3 +
   crypto-core v1"), consumed by humans and previews, never by the
   machine. The exception rule: **include what you assume, reference
   what you consult** — a huge reference ontology (Wikidata-derived) is
   pinned by root and consulted lazily, never embedded. Cost accepted
   with eyes open: closure couples roots down the chain, so a dependency
   *correction* (the rare, loud intervention class) cascades into
   downstream republishes. Scale note: preludes and packs are tens to
   low hundreds of claims — closures are kilobytes.
3. **The prelude is pack zero.** Its only principled specialness is that
   the interpreter *dereferences its names* (the kind nodes registry
   code looks up), so it is version-locked to the code — Python's
   `builtins`, exactly. Fold it into `odag pack`'s listing; keep
   `odag prelude` as an alias; everything the code does not dereference
   belongs in ordinary packs. (Distribution tier ≠ governance tier: a
   top/core ontology is pack-tier by *distribution* under this rule,
   while `EVOLUTION.md` rightly argues prelude-grade *governance* for it
   — small, coarse-but-true, admission a one-way door. Both are true at
   once.)
4. **Names stay identity; collisions are detected, not prevented.** The
   opaque-identity road (Unison/Wikidata: names as bindings to minted
   IDs) is *named and declined*, on the convergence argument: two
   strangers who file the same fact converge to the same bytes only
   because the name is the identity; mint IDs and equal knowledge gets
   unequal roots — G1's spirit broken. The namespace answer is therefore
   Wikipedia's, not Wikidata's: a flat human-readable namespace,
   **parenthetical qualification where ambiguity is real** (authoring
   discipline in the pack style guide), plus detection at the adoption
   boundary (preview, warnings — §13, 9.2/9.7). The binding layer
   (SKOS-style name→name relations, `SURFACE_LAYER.md` §12) is recorded
   as the *additive escape hatch*, not a v1 blocker — and it now has a
   worked encoding: `fr(Mercure=Mercury (planet))` declaration nodes,
   the unit-declaration pattern verbatim, in `SURFACE_LAYER.md` §12
   (2026-08-20). (The precise
   boundary with SEMA-style hash identity — the stranger test, and why
   display forms do not cross it — is drawn in `SEMA.md`, "Why the
   name-binding layer is still not SEMA".) **The ledger has
   two entries, not one** (§12): collisions (same name, different
   concept — detectable, warnable) and **synonyms/translations**
   (different name, same concept — silent *disconnection*, which
   detection cannot see at all; the G1 synonym hazard at ecosystem
   scale, and the standing argument for eventually building the binding
   layer).
5. **Trust = pin, preview, endorse — and packs are data, never code.**
   Adopting a pack executes nothing; the worst case is a false or
   confusing claim, which is visible in the preview, diffable,
   attributable, and removable — a strictly weaker threat model than any
   code package ecosystem. The residue (lookalike names) stays social,
   as §4 concluded.

**The adoption spectrum**, tying principle 1 to size: **consult** (a
`LazyOntoDAG` over the published root + cone summaries — query without
hydration, zero local claims) → **partial adoption** (`odag excerpt
--context` against the pack yields exactly the mergeable fragment) →
**full adoption** (merge the store). All three grades exist in shipped
machinery today. Corollary for teaching errors: generalize the shipped
pack-aware unknown-*unit* hints to unknown *names* checked against known
pack manifests ("found in the geo pack: …").

## 11. Privacy, curation, and guarantees (the composition)

**Privacy divides at a theorem.** Claims within one canonical store
cannot have per-reader visibility: the root hashes everything, and
transitive reduction does not survive projection. So **structure-privacy
= per-audience stores (overlays)**, composed by merge in a session that
holds the keys, never committed as a whole — and **content-privacy = the
category key graph** of `act-categories/DESIGN.md` (per-document keys,
subsumption decrypts, one token per edge, one bridge per grant). They
unify at one seam: an encrypted overlay's blobs take their key from the
audience's node in the key graph, making "a private overlay" and "a
document category with an audience bridge" one mechanism. Supporting
rules: **a private overlay is a pack whose audience is one** (folding
§9.9 in — same object, same adoption, different key management);
**audience is contagious along derivation** (a store's provenance
sibling, cone index, and timeline inherit its audience; public indexes
never list private packs); missing keys are **fail-closed** (a smaller
but valid store — no new query semantics); the one new safety mechanism
is the **leak lint** (committing to a wider audience a claim whose names
hydrated from a narrower layer warns); and **you leak at the granularity
you fetch** — consulting a public ontology from a private context should
fetch an enclosing cone or mirror the whole store (free, it is public),
which is the `offline-essential` retention class doing double duty
(`PROJECTIONS.md` §7). Composition cases verified in discussion:
sign-then-encrypt (provenance works inside overlays); bonds on subjects
are hash-blind (adjudication reveals to the adjudicator); endorsing an
encrypted root is discounted by reader-side trust to endorsers who can
have read it.

**Curation is receiver-sovereign and audits are data.** Publication is
permissionless, so curation is filtering at adoption, never gating —
ucomm's principle again. The model is cargo-vet, not app stores: a
curator is an identity publishing endorsement records over pack roots;
a curation index is itself an ontology (packs as items, categorized by
domain and tier — SEMA's ironclad/honesty-dependent/experimental tiers
are a good borrowing) and is *itself a pack*; competing indexes coexist
and the adopter's trust list decides. **Deprecation comes free**: the
endorsement-of-a-root record has its dual already in the provenance
vocabulary — a signed retraction of a pack root. Tooling checks feed and
provenance for deprecation before adopting; already-adopted stores get
the intervention playbook.

**Guarantees form an assurance ladder**, ascending in cost and
assurance; the adopter picks the rung the use case needs:
root (integrity, free) → signed feed/records (attribution) →
endorsements (web of trust) → **bonds** (factbond — someone loses money
if it's wrong). Unit packs are the *ideal* bond subject: violations are
mechanically adjudicable arithmetic. The MCP annotation slot for
guarantee status is already reserved (`CONTRACT.md` open question 6).

## 12. Forced vs. chosen (the register)

**Forced by the values** (derivations, not bets): privacy-per-store;
merge stays total, compatibility is diagnostics; diamond dependencies
dissolve; adopt-by-root; receiver-side curation; fail-closed keys;
sign-then-encrypt; audience contagion.

**Chosen, eyes open** (cheap to decide now, expensive to re-decide
later):

1. **Names-as-identity** — trades collision-immunity and multilinguality
   for stranger-convergence; both ledger entries above; reversible only
   additively (binding layer).
2. **Closure over manifest** — trades correction-cascade cost for
   no-resolver simplicity; a bet that corrections stay rare and loud.
3. **The retraction wall at ecosystem scale** — a wrong claim in a
   widely adopted pack resurrects against removal among syncing peers;
   curation, preview and bonds mitigate *before* adoption, nothing in
   the algebra fixes *after*. Accepted as the known price of monotone
   merge (its fourth appearance, counting §6 of act-categories — 
   "revocation is strictly forward-looking" is the same wall in crypto
   clothing). If a core value is ever re-examined, it will be because of
   this.

**Empirical risk, substantially retired**: key-management UX — the
people-DAG of act-categories factorizes audiences (a share is a bridge
token, not a new store), and personal leaf keys are SwarmID's job, not
ours (`PROJECTIONS.md` §6).

## 13. Resolutions to the §9 sheet

1. **Naming**: keep "pack" (§10, principle 1).
2. **Diff-preview**: yes — but on `merge` itself, where every merge
   deserves it; `odag pack` needs *no new verb* (adoption = merge +
   preview + optional adoption record). `ontodag.compare` /
   `diff --additions` is most of the implementation.
3. **Wait on Namespaces?** No: grow with detection + qualification
   discipline; the binding layer is the additive escape hatch. The
   synonym cost (§10.4) is recorded as the price.
4. **Pack-root subjects**: yes — endorsement of a root, and its
   retraction dual is deprecation for free (§11).
5. **Provenance-gated adoption**: per-claim origin is **not stored** —
   it is *recomputable* (membership in a pinned root's claim set), the
   canonical-recomputability rule again. Optionally one root-grain
   adoption record where provenance is enabled.
6. **The index**: competing indexes, each itself a pack; receiver
   sovereignty decides; door left open to ecosystem coordination
   (Solar Punk ideabox — a pack index and SwarmID's Persistent Core
   "small resolution records as shared infrastructure" are cousins).
7. **Compatibility check**: unit-level mechanical check runs inside the
   merge preview (resolve the union; conflict = incompatible);
   general-name overlap is a *warning* on the same preview (disjoint
   parent regions → flag), reportable never decidable.
8. **Migrate shipped packs to Swarm**: yes, build item 1 — published
   root must equal the shipped golden root (test-pinned), after which
   `ontodag.packs` shrinks to the bootstrap shim.
9. **Private overlays**: folded in (§11) — a pack with an audience of
   one.
10. Already done 2026-08-01.

## 14. Freeze disposition and build order

The freeze this document imposed is **lifted, into the following order**
(items 1–3 unblocked now; item 4 tripwire-gated):

1. **Merge preview + publish the three shipped packs to Swarm** (golden
   test: published root == shipped root; early and late adopters
   converge byte-identically). **[Built 2026-08-20: `merge FILE --diff`
   and `pack NAME --diff` — additions, the mechanical unit-compat check
   (conflict = exit 1, nothing merged), the unrelated-classification
   warning on shared *categories* (leaves exempt: multi-parent filing is
   normal). Golden tests: CLI `rs:` adoption reproduces the sha256
   golden roots, and each pack's **Swarm/BMT fingerprint is pinned in
   advance** (`SWARM_GOLDEN_ROOTS` in `tests/test_packs.py` — BMT is a
   hash, computable offline), so live publication is verifiable before
   it happens. The remaining live half — pushing the chunks to a Bee
   node, and above all publishing feeds, which requires deciding **whose
   key signs the official packs** (a publisher-identity decision, not
   code) — is deployment. **PUBLISHED 2026-08-20** (Bee 2.8.1 light
   node, Gnosis mainnet, batch `c931c8a5…`, keyless — no feed): all four
   packs pushed via `odag -f swarm:pack-NAME pack NAME`, every store
   root **equal to its pre-pinned BMT fingerprint**, all four
   `isRetrievable: true`, and the full adoption loop proven
   scorched-earth: a reader with *nothing but the root* hydrated
   crypto-core from the network (`RecordStore.at(root, BeeBytesStore)` +
   `LazyOntoDAG`), merged it into their own fresh BMT store, and
   **recommitted to the byte-identical root** — convergence over the
   real network — then parsed `price(5000sat)` → `price(1/20000BTC)`
   through the network-adopted vocabulary. Adopt-by-root is live;
   what still waits on the publisher-key decision is only the *feed*
   (authenticity + updates). The four fingerprints: crypto-core
   `bbd0a930…`, crypto-majors `83337936…`, stablecoins `5bcad36b…`,
   fiat-iso4217 `36a9e1e2…` (full values in `tests/test_packs.py`).]**
2. **Collision warnings in the preview + name-level pack hints** in
   unknown-name errors. **[Built 2026-08-20, with an honesty
   correction: `put` now names its missing parents and hints a pack
   only when adopting it would actually create the node
   (`packs_declaring_node`) — today's unit packs ship no filable
   categories, so bare `BTC` correctly gets no hint (adopting
   crypto-core would not make the put succeed, and a teaching error
   must never teach a falsehood). The hint starts firing the day a
   pack ships real categories.]**
3. **The overlay-view seam + single-audience encryption** (shared
   obligation with `PROJECTIONS.md` §5; an `EncryptedBytesStore` or
   Swarm encrypted uploads — the audience-of-one case, which is what the
   personal-data use actually needs first). **[Both halves done
   2026-08-20: the overlay seam shipped in 0.18.0; single-audience
   encryption landed the same day — `ontodag.encstore`
   (AES-SIV, deterministic so G1 holds within one audience), the
   `store_key` setting, marker-decides semantics, siblings inheriting
   the audience, wrong keys refusing at open. Scope: `rs:` stores;
   encrypted `swarm:` waits on a blobs seam in recordstore's
   `local_first_store`. The wrapper is the seam the act-categories key
   graph plugs audience keys into — §11's unification point exists in
   code now.]**
   3½. **The act-categories crypto spike**: reproduce one of Bee's Go
   ACT test vectors in Python (hours) — retires the only real unknown in
   its Phase 1 without committing to the weeks. **[Done 2026-08-20:
   `experiments/act_crypto_spike.py` matches Bee v2.8.1 bit-for-bit on
   generated vectors (incl. the 31-byte stripped-x trap pair) and Bee's
   own upstream fixed vector — record in act-categories DESIGN.md §5.]**
4. **act-categories Phase 1 on a tripwire**: the first real
   multi-audience need (a second person/team reading a *category* of
   content; ucomm or ontodag-fs reaching shared deployment). It needs
   **nothing from upstream Bee** — Phase 1 is client-side against a
   stock node by design; Phase 2's header is convenience for third-party
   clients, filed later *with* working evidence. Scope lever recorded:
   if the first consumer is a closed all-odag group, ACT compatibility
   itself is deferrable (own-format encryption over the same token
   graph, ~half the estimate), added when interop matters.

"Further shipped packs" stays discouraged not by freeze but by pattern:
publishing is now the way (item 1); code distribution remains bootstrap
only. New vocabulary continues to gate on nothing — graph-declared
units made that a data question, which was the point.
