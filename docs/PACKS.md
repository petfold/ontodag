# Packs: Published Ontologies, Adoption, Collisions, and Trust

Status: **discussion draft, 2026-08-01 (prompted by Peter: "we should have
had more discussion on packs — it goes way beyond units"). Nothing here is
decided; §8 collects the open questions.** This document exists to be
argued with, and to gate the *next* step of packs (third-party
distribution, more shipped packs) — not the current one, whose trust
surface is analyzed in §2 and is deliberately narrow.

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
ontology" — is genuinely open (§8.1). The risk of "pack" is that it
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
not decisions:

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
  the merge. (Needs a pack-root subject form in `PROVENANCE.md` — §8.4.)
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
(the cone-index pattern), not inside it.

And per `SURFACE_LAYER.md` §11 — build it out of OntoDAG — the **pack
index can itself be an ontology**: packs as items categorized under
`unit-pack` / `lexicon` / `upper-ontology`, values carrying roots,
discoverable with the one query primitive. Who publishes and endorses
that index is an open trust question (§8.6), not a mechanism question.

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
discussion settles the trust workflow.

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

## 8. Open questions (the sheet)

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
