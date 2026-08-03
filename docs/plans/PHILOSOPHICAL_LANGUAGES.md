# Philosophical languages, taxonomic names, and OntoDAG

Status: **notes for interest and inspiration**, not design. Collected 2026-07-20 from a
design conversation about semantic codes (see `SEMANTIC_CODES.md` for the engineering
counterpart). Possibly useful later for a paper's related-work or epigraph material.

The question that summoned this history: *should a concept's name encode its meaning?*
OntoDAG's answer (names stay arbitrary and stable; meaning lives in a derived code —
`SEMANTIC_CODES.md`) turns out to be a position in a debate that has run for about
seven centuries. Nearly every design constraint we derived independently was first hit
by someone below.

## The combinatorists and taxonomists

**Ramon Llull, *Ars Magna* (c. 1305).** The ancestor of the whole tradition: a set of
primitive concepts arranged on rotating paper wheels, whose combinations were supposed
to generate — mechanically — all true propositions. The first claim that *conceptual
structure is combinatorial* and that reasoning could be outsourced to a mechanism
operating on symbols. Leibniz read him closely (and said so, in the *Dissertatio de
arte combinatoria*, 1666).

**Francis Lodwick, *A Common Writing* (1647) and George Dalgarno, *Ars Signorum*
(1661).** The 17th-century English movement (Royal Society milieu): artificial
vocabularies in which a word's letters walk down a taxonomy. Dalgarno's radicals
assign the first letter to the highest genus, the second to a subdivision, and so on —
a prefix code over a concept tree.

**John Wilkins, *An Essay Towards a Real Character, and a Philosophical Language*
(1668).** The fullest attempt, and the closest historical match to the "tree-like
code" option. Wilkins divided the universe into 40 genera, subdivided by "differences"
and then "species," and made spelling mirror classification. Borges's summary example:
*de* means an element; *deb*, the first of the elements, fire; *deba*, a portion of the
element of fire, a flame. Two properties fall out immediately:

- **Prefix sharing = semantic proximity.** Mammals, dogs, and spaniels share a prefix;
  sorted order is taxonomic order; a range scan is a subtree. This is exactly the
  locality that a lexicographic index (like recordstore's radix trie) would love and
  that arbitrary names cannot provide.
- **The "Real Character."** The written form denotes *ideas*, not sounds — the same
  move as content addressing: the name is derived from the thing, not assigned to it.

And two failure modes, which are precisely OntoDAG's two design constraints:

- **It is a tree.** A concept with two legitimate genera has no legal name. Wilkins
  visibly agonizes over placements because the code *forces* a unique parent — the
  multi-parent problem, 1668 edition. (A prefix code embeds a tree order; no linear
  key space can embed a partial order with genuine multiple parents. See
  `SEMANTIC_CODES.md` §5 for the modern statement and the partial escape.)
- **Meaning-bearing names are brittle.** Revise the taxonomy — and taxonomies are
  always revised — and every word in the dictionary changes. The language ossifies
  or shatters; there is no third option.

## Leibniz: reasoning as calculation

**Gottfried Wilhelm Leibniz, *characteristica universalis* and *calculus
ratiocinator*.** Less lexicographically detailed than Wilkins, but deeper: symbols
whose structure reflects conceptual structure *so that inference becomes computation*
("Calculemus!" — when men disagree, let them calculate). His concrete scheme, from the
1666 *Dissertatio* and later fragments, is startlingly modern: assign **prime numbers
to primitive concepts and products to composites**, so that a concept's number is the
product of its constituents' primes. Then:

> A subsumes B  ⟺  code(A) **divides** code(B)

Divisibility of squarefree numbers *is* set containment — Leibniz's encoding and the
ancestor-set bitvector of `SEMANTIC_CODES.md` are the same lattice written in
multiplicative and Boolean notation respectively. The bitwise-AND subsumption test
(Aït-Kaci et al. 1989) and a roaring-bitmap cone intersection are small realized
fragments of the *calculus ratiocinator*. Gödel numbering (1931) is the same trick
pointed at syntax instead of concepts — arithmetization as the universal encoding move.

## The critics

**Jorge Luis Borges, "El idioma analítico de John Wilkins" (1942).** The resident
skeptic. The essay's famous fictional taxonomy — the *Celestial Emporium of Benevolent
Knowledge*, whose animals include "those that belong to the emperor," "embalmed ones,"
"those that tremble as if they were mad," "those drawn with a very fine camelhair
brush," and "those that from a long way off look like flies" — makes the argument that
**every classification of the universe is arbitrary and conjectural**, because we do
not know what the universe is. Translated into this project's terms: no single
taxonomy deserves to be baked into *identity*. It is, constructively read, the
argument for OntoDAG's multi-writer design — committed roots, per community, per
purpose, mergeable but never final. Wilkins wanted the one true tree; the answer here
is closer to Borges: canonical *forms*, plural.

**Borges again, "Funes el memorioso" (1942).** The complementary pathology: Funes,
after his accident, remembers everything and therefore cannot generalize — he is
"virtually incapable of general, platonic ideas," troubled that the dog seen at 3:14 in
profile should share a name with the dog at 3:15 seen frontally. Funes cannot think,
because **thinking is abstraction, and abstraction is compression**. This is the
MDL-FCA thesis in fictional form: a concept deserves to exist only if it compresses
experience enough to pay for its own description. Funes is the degenerate case where
the codebook equals the data — MDL gain identically zero.

**Michel Foucault, *Les mots et les choses* / *The Order of Things* (1966).** Opens by
confessing the book was born from laughing at Borges's Chinese encyclopedia — the laugh
that shakes "all the familiar landmarks of thought." Foucault's *epistemes* are the
historical observation that classification schemes are not refined over time so much as
*replaced* — supporting evidence for keeping identity out of the classification, since
the classification will not survive, and for treating any committed DAG as a snapshot
of one episteme rather than an approach to the final one.

**Umberto Eco, *The Search for the Perfect Language* (1993).** The definitive survey
of this entire tradition, Llull through Esperanto, and the best single source if any of
this reaches a paper.

## The librarians (applied Wilkins, and the applied fix)

**Melvil Dewey (1876) and UDC.** Wilkins's true heirs: meaning encoded in the
identifier, hierarchical prefix semantics, physical shelf adjacency as semantic
proximity (the *locality payoff*, actually realized — browsing a shelf is a range
scan). And the same brittleness, actually paid: whole fields of knowledge wedged into
ossified top-level divisions chosen in the 1870s.

**S. R. Ranganathan, Colon Classification (1933).** The escape from the tree, from
inside library science: describe a work by a *set of independent facets* (personality,
matter, energy, space, time) rather than one path. Structurally this is the move from
Wilkins's path-code to the FCA intent-set — from tree coordinates to attribute
vectors. Faceted classification is the librarians' independent discovery that the
lattice, not the tree, is the honest shape.

## The scientists (codes and surrogate keys, coexisting)

**Linnaean binomial nomenclature (1753).** A one-level taxonomic code: the genus is a
prefix carrying real classification. And a working demonstration of the instability
cost: every taxonomic revision renames species, synonymy databases exist purely to
track the churn, and the nomenclature codes (ICZN/ICN) are largely machinery for
managing renames. One level of meaning in the name already costs this much.

**IUPAC systematic names vs. CAS registry numbers.** Chemistry has the purest
meaning-bearing names anywhere — an IUPAC name *is* the molecular structure, decodable
by algorithm — and even there, practice keeps **both**: the systematic name (the code)
and the CAS number (the arbitrary surrogate key), because structures get re-perceived,
names have variants, and databases need stable join keys. The strings-vs-codes
resolution OntoDAG adopts (arbitrary name for identity, derived code for structure) is
exactly the chemists' settlement.

## The counterpoint: natural language and the constructed pragmatists

**Saussure's arbitrariness of the sign.** Natural languages survive millennia of
conceptual change precisely because names do *not* encode meaning — an arbitrary sign
is a stable sign. This is the deep reason "words, not pointers, not codes" wins for
identity.

**Volapük (Schleyer, 1879) and Esperanto (Zamenhof, 1887).** Regular morphology,
simplified grammar — but deliberately *not* taxonomic vocabularies. Their (relative)
success versus the total extinction of the philosophical languages is a natural
experiment: regularity helps, semantic encoding in roots does not survive contact with
change. Two exceptions prove the rule: **Solresol** (Sudre, 1827), words built from
solfège syllables with semantic categories by initial syllable, and **Ro** (Foster,
1904), a full Wilkins-style taxonomic vocabulary ("bofoc" red, "bofod" orange) —
both worked exactly like Wilkins and died exactly like Wilkins, Ro being criticized
in its own time because words for similar things were too similar to distinguish
reliably (a *disadvantage* of semantic locality no one in 1668 had considered:
error-correcting codes want *distance*, not proximity).

## Modern descendants

- **Opaque URIs + ontologies (the Semantic Web settlement).** W3C best practice is
  explicitly Saussurean: identifiers should be opaque; meaning lives in asserted
  triples *about* the identifier. Names-vs-codes, resolved the same way.
- **WordNet, Cyc.** Large concept graphs with arbitrary identifiers and explicit
  subsumption links — DAGs, not trees, both having learned the multi-parent lesson.
- **Sparse distributed representations / vector symbolic architectures** (Kanerva's
  SDM and hyperdimensional computing; Plate's holographic representations). The
  "neural binary representation" idea in earnest: concepts as high-dimensional sparse
  binary vectors where overlap is similarity, union/binding is composition, and a
  code's *bits are features*. The ancestor-set code of `SEMANTIC_CODES.md` is exactly
  such a representation whose feature alphabet is the category set itself — and sparse
  coding theory says the efficient code allocates short/dense codes to frequent
  concepts, which is what an MDL objective (mdl-fca) does automatically.
- **Földiák, "Sparse neural representation for semantic indexing" (ESCOP 2003)** —
  the direct ancestor of this project's code-primary view: concepts as sets of active
  units instead of nodes-and-links ("explicit links are not even necessary"),
  inheritance as subset structure between feature sets, set algebra for defining
  concepts and expressing queries, retrieval as maximal-overlap search with a
  generality/specificity display. Its per-concept fresh feature (`animal := thing ∪ !`)
  is precisely the reflexive bit of the ancestor-set code — the arbitrary surrogate
  key embedded inside the meaning-bearing code. Poster:
  https://drive.google.com/file/d/0BzC4pqiFnDxcNnpFTm9qYWpqejg/view?usp=sharing
  (local copy: `docs/escopill2.pdf`, kept untracked).
- **Order embeddings (Vendrov et al. 2016) and Poincaré/hyperbolic embeddings (Nickel
  & Kiela 2017).** The continuous relaxation: learn vectors such that subsumption is
  coordinate-wise dominance or hyperbolic proximity. Trees embed in hyperbolic space
  with arbitrarily low distortion; DAGs only approximately — the same tree/DAG
  obstruction, reappearing in Riemannian geometry.

## The lessons, compressed

| Historical fact | OntoDAG design decision it supports |
|---|---|
| Wilkins's tree forced unique parents | Prefix/path codes rejected; only set/bitvector codes respect a DAG (`SEMANTIC_CODES.md` §5) |
| Wilkins/Dewey ossification; Linnaean renaming churn | Meaning-bearing names are unstable → names stay arbitrary identity |
| IUPAC + CAS coexistence | Keep *both*: stable surrogate name + derived structural code |
| Leibniz's primes (divisibility = subsumption) | The code lattice; subsumption as a bit test |
| Borges/Foucault: all taxonomies conjectural | No single official DAG; multi-writer roots, merge, overlays |
| Funes: no compression, no thought | mdl-fca: concepts must pay for themselves (MDL) |
| Ranganathan's facets | Intents/attribute-sets over paths; FCA as the honest formalism |
| Ro's confusable words | Semantic locality is for *indexes*, not for human-facing names |
| Solresol/Ro dead, Esperanto alive | Regularity survives; semantic encoding in identity does not |
