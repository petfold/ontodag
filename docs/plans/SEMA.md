# SEMA and OntoDAG — relation, lessons, collaboration options

*Discussion note, 2026-08-17. Based on the SEMA preprint ("Sema: When the Hash
Is the Word", Henrik Westerberg, Emergent Wisdom — revised 2026-08-15,
https://emergentwisdom.org/papers/sema.pdf) and the repository
https://github.com/emergent-wisdom/sema. Nothing here is agreed or scheduled;
the pack-shaped options are behind the PACKS.md freeze like everything else.*

## What SEMA is

One author (Henrik Westerberg), preprint + working code (PyPI `semahash`,
MCP server, ~11 GitHub stars, active). The primitive is
`word = hash(canonical(definition))`: a **Pattern Card** is a JSON behavioral
contract (mechanism, invariants, pre/postconditions, typed dependencies,
`extends`), canonicalized RFC-8785-style (NFC normalization, type-tagged
Merkle nodes, key-collision rejection) and Merkle-hashed field by field. The
digest is used *as a word inside agent messages* (`StateLock#c9c2`). A
fail-closed handshake compares the Merkle root of a selected context so two
agents can verify they resolved the same definitions before coordinating.
A bootstrap library of 457 cards forms a Merkle DAG (dependencies and
`extends` reference targets by full hash). Taxonomy placement (`_meta.path`,
tier, layer) is deliberately **unhashed** — "the mechanism is mathematics,
the taxonomy is politics." Storage is SQLite; distribution is a centralized
canonical-pull model.

## The structural relation

Both projects make the same theorem-shaped move — *canonicalize, then hash,
and identity becomes comparison* — at different grains, and the grain choice
buys opposite properties:

- **SEMA** gets per-concept verifiable identity but **has no merge algebra**.
  Its own "Synonymy Limit" section says so: behaviorally equivalent
  definitions hash differently, forks "coexist rather than collide," merging
  is "explicit alignment work outside the cryptographic layer." Distribution
  is centralized-pull precisely because there is no convergence rule. Its
  vocabulary-snapshot roots (sorted digest sets, RFC 9162 trees) are a
  hand-built canonical root for an unordered set — what recordstore's
  canonical radix trie does systematically.
- **OntoDAG** gets convergence — unique transitive reduction → canonical form
  → byte-identical roots across writers, insertion orders and gossip
  schedules (G1, I7) — but concepts are bare name strings; nothing binds
  `Japan` to a definition. That is the semantic-spoofing residue PACKS.md
  already names.

Each system's headline feature is the other's flagged gap.

Two more direct contacts:

- **Their handshake vs. our root citation.** SEMA builds a Merkle tree over a
  selected context subset because its store has no canonical whole-state
  root. OntoDAG's store has one by construction — every MCP answer cites it —
  and `is_below` certificates go further than SEMA's guarantee: not "we hold
  the same definitions" but "this answer is provably entailed by this root,
  verifiable offline." Their Babel-test finding — a tool-mediated HALT
  verdict overrides the model's conversational agreeableness — is independent
  empirical support for AGENT_SURFACE.md's bet that putting the decision in a
  deterministic tool moves the boundary away from model agreeableness.
- **Versioning is where OntoDAG/recordstore is plainly ahead.** SEMA's stated
  limitations: one active definition per handle, no archive of replaced
  versions, renames of referenced handles cascade hash changes through all
  dependents, and "keeping old pins resolvable requires a future multi-version
  content store." That future work is literally what recordstore is —
  content-addressed blobs that never collect, `at(root)` snapshots,
  history/undo timelines — plus `ontodag.migrate` as the re-canonicalization
  replay.

## What OntoDAG can learn or take

1. **The taper: fuzzy discovery → exact verification.** SEMA cleanly
   separates embedding/keyword search (high recall, no guarantees) from hash
   identity (coordination). Same split SURFACE_LAYER.md gropes toward.
   Concrete cheap consequence: a fuzzy `search` MCP tool returning
   *canonical names* — discovery is currently odag-mcp's weakest part (an
   agent must already know the vocabulary; `browse` is structural, there is
   no "how to handle errors → Retry" path).
2. **Content-bound definitions as an answer to name spoofing.** PACKS.md's
   trust model is adopt-by-root plus `binding` records (signatures, web of
   trust); SEMA's is hash-of-content. Genuinely different answers to the
   lookalike-name problem — the PACKS.md discussion should weigh both. SEMA's
   move eliminates "who signed this" for the *definition* while keeping the
   lookalike-handle residue (their short stubs are explicitly not a security
   boundary — the same social residue we identified).
3. **A worked JSON canonicalization for payloads.** PROVENANCE.md's flagged
   unworked residual is the `payload(name, content-hash)` subject form. SEMA
   has a worked, versioned canonicalization with real lessons across two
   versions — read it before that residual is ever worked, rather than
   rediscovering their v1 mistakes.
4. **Adversarial hardening of a shipped vocabulary.** Their tier system
   (ironclad / honesty-dependent / experimental), Devil's-Advocate passes and
   experimental-shelf split for dual-use patterns are curation methodology
   directly relevant to the packs governance questions — answered in practice
   there, even if manually.

## What SEMA could take from OntoDAG (the collaboration pitch)

Their taxonomy layer is an OntoDAG-shaped hole: deliberately unhashed,
single-hierarchy path lists, centrally curated by a human "Taxonomist," no
merge, no attribution, reclassification decisions living in commit history.
OntoDAG makes classification itself canonical, multi-parent, mergeable and
attributable — with the exact operations their refinement passes do by hand:
`move`/`reclassify` with contested-set reports, `remove --cone` with the
survival rule, claim-grain `diff`, `endorse`/`retract`/`review` with
per-author standing. Their `extends` edges already form an IS_A DAG that
would import into OntoDAG nearly losslessly.

Three graded options:

- **Cheap, one-directional:** export SEMA's `extends` + category structure
  into an OntoDAG store as a derived-pack *experiment* (public data). Tests
  both systems: does their 457-card lattice survive transitive reduction and
  multi-parent placement, and does a canonical root + CRDT merge actually
  solve their fork-coexistence problem? Weekend-scale, produces evidence for
  any outreach.
- **Substrate adoption (a pitch to Henrik, not work for us):** SEMA on
  recordstore instead of SQLite closes their historical-version-storage
  limitation for free, and Swarm gives them the decentralized distribution
  their paper says the primitive supports but the bootstrap doesn't build.
- **Layer composition:** the honest framing is a trust stack on different
  floors — SEMA: identity of rich definitions; OntoDAG: entailment over a
  canonical, mergeable state (certificates); provenance: attribution;
  factbond: economic guarantees. SEMA cards as content-addressed *payloads*
  hanging off OntoDAG nodes, OntoDAG holding the subsumption skeleton and the
  now-mergeable classification — same one-directional-dependency shape as the
  factbond relationship.

## Honest caveats

- **Layer mismatch is real.** SEMA hashes prose contracts nothing computes
  over — verification means "same bytes"; invariant enforcement is explicitly
  punted to the harness. OntoDAG's semantics are computable (cones, dimension
  arithmetic, certificates) but deliberately minimal. Composition, not merger.
- **Stage and bus factor:** single author, preprint, 11 stars — same weight
  class as OntoDAG. Cuts both ways: collaboration is one conversation away,
  but nothing there is a standard to align with yet.
- Their evaluation is thin by their own admission (N=5 demonstrations,
  confounded conditions); the durable contributions are the canonicalization
  mechanics and the framing, not the empirical claims.
- Their related work covers the content-addressing lineage (SDH, Trusty URIs,
  Unison, Agora) well but misses the order-theoretic/FCA line entirely —
  mutual citation would improve both papers (`ontodag-fca.tex` could cite
  SEMA in Part IV; their paper has no answer to "what should the *relations
  between* hashed definitions guarantee," which is exactly our contract).

## Suggested first moves

1. Run the export experiment (their `extends` graph into an OntoDAG store).
2. Email Henrik Westerberg (henrik.westerberg@emergentwisdom.org) — draft
   below — ideally with the experiment's result attached.
3. Hold anything pack-shaped behind the PACKS.md discussion per the standing
   freeze.

## Appendix: email draft to Henrik

Subject: **Sema × OntoDAG — two canonicalizations, opposite grains**

> Dear Henrik,
>
> I read "When the Hash Is the Word" with great interest — I work on a
> project called OntoDAG (https://github.com/petfold/ontodag, `pip install
> ontodag`) that I think sits one floor below Sema in the same building, and
> I wanted to compare notes.
>
> Both projects make the same move — canonicalize, then hash, so identity
> becomes comparison — but at opposite grains. Sema hashes each definition;
> OntoDAG hashes the whole knowledge state: it is a multi-parent subsumption
> DAG kept in transitively reduced form, and because the transitive reduction
> of a DAG is unique, equal knowledge produces a byte-identical canonical
> root regardless of insertion history or writer. That gives it the property
> your Synonymy Limit and distribution sections name as open: a commutative,
> idempotent merge — independently evolved stores converge to the same root,
> so forks reconcile instead of coexisting, with per-claim signed provenance
> in a parallel store for attribution.
>
> The complement runs the other way too: OntoDAG's concepts are bare names
> with no bound definition — exactly what Sema provides. And your
> historical-version-storage limitation (one active definition per handle,
> old pins unresolvable) is what our storage substrate, recordstore, does
> natively: a canonically-encoded content-addressed record store with
> snapshots at any past root, history/undo, and optional distribution on
> Ethereum Swarm via signed feeds.
>
> Concretely, two things I'd enjoy discussing:
>
> 1. Your `extends` edges form an IS_A DAG, and your unhashed taxonomy
>    overlay is precisely the layer OntoDAG makes canonical, multi-parent,
>    mergeable and attributable (with reclassification, cone deletion, and
>    claim-grain diff as verified operations). I'm tempted to import the
>    bootstrap library's structure into an OntoDAG store as an experiment —
>    happy to share the result.
> 2. Verifiability one level up: OntoDAG answers carry the store root, and
>    subsumption answers come with offline-verifiable Merkle certificates —
>    "this answer is entailed by this root" rather than "we hold the same
>    definitions." Your handshake and these certificates look like adjacent
>    floors of the same trust stack.
>
> If any of this sounds interesting, I'd be glad to talk.
>
> Best regards,
> Peter Földiák
