# Codes and factors: the graph, its code, and independent aspects

Status: **plan, 2026-11-12. Built: the probe**
(`experiments/codes_probe.py`), which prints every number in §4 and §7,
**and step 1** (`experiments/context_export.py`, §8), on Peter's answer
to question 51 the same day: B. The rest continues `SEMANTIC_CODES.md`,
parked since 2026-07-20 and still parked (§4 says why), with two things
that note lacks: a code that may be partial, with a mark saying where it
is whole (§5), and factors (§7). The learner's side of the same questions
is in mdl-fca's `docs/06-roadmap.md` §10 and §11; the vocabulary's own
shape is question 52, in ontodag-core's `docs/UPPER.md` §17.

## 1. The two concerns (Peter, 2026-11-12)

1. OntoDAG works on the graph and never on the neural code, which FCA
   calls the context. Some operations may be cheaper on the code, or on a
   partial conversion, where some concepts hold part of their intents and
   extents and are marked incomplete. The answers must stay the same.
2. FCA factors contexts and writes lattices as products. Where aspects
   are independent (colour and shape), the product holds many
   combinations that mean little, and a factored form is far smaller.
   mdl-fca meets the same question: it may be easier to learn the code
   than the DAG.

The short answers:

1. Yes. The store is already a partial conversion in six places (§2),
   each with its own rule. A code pays most where an answer is counted or
   browsed and little where things are filed, and at the size of today's
   stores nothing is slow enough to need it (§4).
2. The stored graph is already the factored form. The product appears
   only in what could be derived from it: a full lattice, or an index
   that ignores the factors. There the factors are what keeps a code
   small (§7).

## 2. What exists today

In FCA's terms an OntoDAG is the context whose objects and attributes are
both the nodes, with a cross where the row's node is below the column's
(`paper/sections/06-dictionary.tex`). A row is a node's ancestors, its
intent. A column is a category's cone, its extent. The concept lattice of
that context is the Dedekind–MacNeille completion of the stored order.

OntoDAG stores neither rows nor columns. It stores each node's parents,
the fewest ancestors from which the rest follow. Beside the graph it
keeps these pieces of the code:

| Piece | In the code's terms | Whole? |
|---|---|---|
| `descendant_count` on every node | the size of every column, exact, kept current by delta | yes for asserted edges; a term's count leaves out what the computed order adds |
| the `is_below` memo (`DAG._memo`) | single cells, yes or no, kept until the next write | the cells that were asked |
| the value indexes per head (`_Intervals`, `_Prefixes`, `_Rectangles`) and the argument index | the computed order among a head's terms, found by range, not by scan | yes |
| published cone summaries (`cones.py`) | whole columns as sorted names, for categories of 64 members or more, in a store of their own | those columns; the manifest names the root they describe |
| `browse.refinements` | the rows of an answer's members, climbed one by one and summed by column | a sample of 2,000 when the answer is larger, and it says so |
| `LazyOntoDAG`, `SparseOntoDAG` | a graph only partly in memory | stubs mark what is not loaded |

The planner (`OntoDAG.get`) uses the counts and, through `is_below`, the
memo. It drops a term that is an ancestor of another, orders the rest by
count, walks the smallest cone, and then chooses for each further term,
from the number of candidates left, between walking that term's cone and
climbing from each candidate.

So "a partial conversion with marks" describes what the code does
already. Two things are missing: one rule for all the pieces (§5.1), and
the rows of the vocabulary (§5.3).

## 3. One order, three codes

- **The stored code**: a node's parents. Reduction makes them an
  antichain (I2: no parent stands above another).
- **The closed code**: all its ancestors. This is the row of the context,
  FCA's intent, and `code(x)` in `SEMANTIC_CODES.md` §2.
- **A partial code**: anything between, a set that holds the parents and
  holds only ancestors.

Each of the first two gives the other. Closing the stored code is a
climb; reducing the closed code gives the parents back; both results are
unique. The stored code is the smallest, and a change touches it least:
a new edge high in the graph is one edge in the stored code and a new
entry in the row of everything below.

The closed code factors through the stored one. For the leaves L and the
categories V,

```
closed(L × V)  =  parents(L × V)  ∘  closed(V × V)     (Boolean product)
```

since an item's ancestors are its parents' ancestors put together. This
is a Boolean factorisation of the context, the decomposition Belohlavek
and Vychodil study, with the categories as the factors, and the stored
graph carries it through every level. When `is_below` climbs, it computes
one row of the product, for the one who asked.

In the neural reading the edges are the weights and the closed code is
the activity: switch a node on, let activation spread upward, and the
units that fire are its row. The stored code names the units to switch on
by hand.

mdl-fca draws the same model upside down. Its concepts point down to what
they imply, and an object switches on an antichain of concepts and gets
everything reachable. A concept's children there are a node's parents
here, and an object's code there is an item's parent set here. So the
theorem of mdl-fca's `note/product-of-dags-note.tex` holds for an OntoDAG
store as it stands (§7.1).

## 4. Measurements

`python3 experiments/codes_probe.py`, about a minute. The vocabulary is
core v14 and the ten domain packs, merged. The population is the same
store with 30,000 items, each filed under one category drawn at random
from each of three top-level cones (`physical-object`, `event`,
`information`). The population is made up: it shows the arithmetic, not
how people file. Times are from one run on this laptop and move by a
tenth or two from run to run.

The vocabulary:

| | |
|---|---|
| nodes | 11,643 |
| stored edges | 12,995 |
| nodes with something below them | 2,848 |
| nodes with several parents | 1,279 (11.0%) |
| ancestors of a node | mean 5.3, median 5, most 19 |
| pairs in the order (the ones of the closed code) | 61,826, 4.8 times the edges |
| rows and columns built as Python integers | 61 ms, 18.8 MB |
| cones whose size differs from the stored count (I5) | 0 |
| `is_below` for a random pair: a climb, the code | 6.8 µs, 1.1 µs |
| `is_below` for a node and an ancestor: a climb, the code | 3.5 µs, 0.85 µs |

The population (41,643 nodes, 102,995 edges):

| | |
|---|---|
| a `put` of an item under three categories | 286 µs in the first thousand, 273 µs in the last |
| an item's closed code, its stored code | 17.6 ancestors, 3.0 parents |
| two broad terms from two aspects (smaller cone 832, answer 179): the planner today | 5.7 ms |
| the same walk, candidates settled by the vocabulary's codes | 2.6 ms |
| cone bit sets, the answer listed | 0.75 ms |
| cone bit sets, the answer counted | 0.005 ms |
| cone bit sets for the 8,255 categories | 38 MB |
| refinements of an answer (1,446 members on average): climbing | 50.1 ms |
| the same from the vocabulary's codes | 24.7 ms |
| the same from cone bit sets, whatever the answer's size | 21.1 ms |

What they say:

1. **Nothing here is slow.** A two-term query over 30,000 items takes
   5.7 ms, and a climb takes 4 to 7 µs because the vocabulary is shallow.
   The gates of `SEMANTIC_CODES.md` §8 stay shut for every store we have.
2. **Where a code pays**, most first: counting an answer (a thousand
   times), listing an intersection (seven to ten times, run to run),
   refinements (twice, and no longer tied to the answer's size, which is
   why browsing samples 2,000 members today), a membership test inside a
   query (twice).
3. **Filing had waste of its own, removed the same day.** As first
   measured a put took 0.88 ms: 45% of it asked each of the 50 declared
   roles, on every edge, whether it named the new node, and two of the
   four climbs an edge made looked for something below a fresh leaf. The
   argument index answers the first, and nothing is below a fresh leaf,
   so a put now takes 0.25 ms (`tests/test_hops.py`,
   `TestFilingAsksNoRole`). Of that, 39% is the `is_below` climbs a code
   would shorten, and 5% the upkeep of roles. A code is not what filing
   needed.
4. **Dense bit sets grow as categories times nodes**: 38 MB at 41,643
   nodes. Past 10^5 nodes they need a compressed form (Roaring bitmaps,
   or runs).

## 5. Partial codes

### 5.1 The rule that keeps the answers

A piece of the code may be partial if it carries a mark that says whether
it is whole, and if it is read like this:

- A row that holds A answers *yes*. A row marked whole that lacks A
  answers *no*. A partial row that lacks A answers nothing, and the
  caller climbs as today.
- A column likewise: the members it lists are members, and only a whole
  column shuts anything out.

An index that cannot answer never guesses. `is_below` stays fail-closed
(G4), and the planner's rule covers the index too: it steers time, never
an answer.

### 5.2 OntoDAG needs the mark anyway: the computed order

Rows and columns built from asserted edges are whole only where no term
is involved, because a term's place is computed from its name and never
stored. An item under `image-dataset` is below `about(information)` only
through the computed step from `about(image)`, which no stored edge
shows.

The probe uses two marks. A row is whole when the node is no term and no
term stands above it. A column is whole when no term stands below the
category. 7,754 of 8,255 categories have whole rows and 8,018 of 8,254
have whole columns. Read by §5.1 with a climb for the rest, the codes
gave the planner's answers for all 200 queries and the climbed counts for
all 57,821 answer members; the probe asserts both. Without the marks they
differ.

The planner already knows one such partial figure: a term's count. It
calls such a term unsized, walks it only so far, and otherwise probes.

### 5.3 Close the vocabulary, not the store

Keep closed rows only for nodes with something below them. A leaf keeps
its parents, and its row is its parents' rows put together when asked.

- **Size.** 53,140 pairs for the population's 8,255 categories, beside
  90,000 item edges the store holds anyway. Closing every node would take
  632,282.
- **Upkeep.** Filing a leaf changes no row. A leaf that gets its first
  child gains a row made from its parents' rows. An edge between two
  categories changes the rows of the categories below the lower one: a
  cost counted in categories, never in items. A removal rebuilds the same
  rows. A replay drops the rows and builds them again, about 70 ms for
  the whole vocabulary.
- **Scope.** Rows follow asserted edges, as counts do. The computed order
  stays in its own indexes.

### 5.4 Names the idea has elsewhere

- **FCA.** A pair of a set of objects and a set of attributes where each
  object has each attribute, not yet closed, is a *preconcept*; with one
  side closed it is a *semiconcept* (Wille). An *iceberg lattice* keeps
  only the concepts with large extents (Stumme and others); the cone
  summaries are an iceberg of columns.
- **Graph databases** call these reachability labels. Interval labels
  over a spanning tree (Agrawal, Borgida and Jagadish;
  `SEMANTIC_CODES.md` §5). 2-hop labels (Cohen and others), where each
  node keeps part of its ancestors and part of its descendants, and the
  two parts together settle every pair. GRAIL (Yildirim and others) and
  Bloom-filter labels (Su and others), which settle most *no*s at once
  and climb for the rest. All are partial codes read by §5.1's rule, and
  all were built for graphs of millions of nodes.
- **Data cubes**: which views to keep (`SEMANTIC_CODES.md` §9).

## 6. What FCA's algorithms offer

The algorithms on Uta Priss's page
(https://upriss.github.io/fca/fcaalgorithms.html) and their neighbours
fall into three groups.

1. **Those that list every concept**: NextClosure (Ganter), Close-by-One
   and its descendants FCbO and In-Close. OntoDAG refuses that list,
   since it can grow exponentially (`paper/sections/07-differences.tex`),
   so they have no place on the query path. They fit a derived store
   built from a pinned root: the implication lint and the exploration of
   `paper/sections/12-directions.tex` (D4, D6), suggestions of meets
   worth naming, and a baseline for mdl-fca. The step they need is small:
   write a store's context in the format those programs read (§8,
   step 1).
2. **Those that add one object to a built lattice**: AddIntent (van der
   Merwe, Obiedkov and Kourie). This is the upkeep a memo of meets would
   need, the canonical placement of `SEMANTIC_CODES.md` §10: a new item
   joins every kept meet whose terms are all among its ancestors, and its
   own row finds them.
3. **Those that find one concept's neighbours** without the rest of the
   lattice (Bordat; Lindig). Ferré's logical information systems browse a
   store this way and never build its lattice; Carpineto and Romano treat
   retrieval with concept lattices at length. `browse.refinements` takes
   the same step, and these systems are its closest relatives.

All three work on rows and columns as bit sets and close by AND, the
operation measured in §4.

One more tool is *clarification*: objects with equal rows are one object.
Items with the same parents have the same row, so an index from each
distinct parent set to its items would let a query or a count run over
the sets. In the made-up population the sets were drawn at random and
nearly all differ. In a real store the files of one folder may share
theirs. Step 1 counts them: the shipped vocabulary's 8,795 leaves have
2,944 different parent sets, a third as many, and a store of real items
(9,651 Wikidata instances filed under the place categories by
ontodag-core's `tools/instances.py`) has 9,876 objects in 802 different
rows, a twelfth.

## 7. Factors

### 7.1 The store is already the factored form

mdl-fca's note proves that two generators over separate attributes, laid
side by side, represent the product of their two lattices: the generator
grows as a sum while the lattice grows as a product. An OntoDAG store is
such a generator. The categories of each aspect stand side by side, an
item under `red` and `square` is its pair of parents, and no node
`red-square` exists unless someone names one. `USER_GUIDE.md` says it of
coordinates: "Three coordinates as three supercategories *is* the product
of three orders, and `get` intersects it."

The population, counted three ways:

| | |
|---|---|
| stored: the items' edges | 90,000 |
| pairs of categories from two aspects that hold something | 522,475, with 66,942 different answers, 66,405 of them no stored node's cone |
| pairs of categories from two aspects | 15,848,444 |

The store grows with what is filed, a lattice built from it with what
occurs together, and the product with what could. Meets of three
categories come on top of these.

### 7.2 Where the product does appear

- **A completed lattice.** Never built.
- **An index that numbers every node once.** `SEMANTIC_CODES.md` §5
  numbers the nodes along one spanning tree so that a cone becomes a few
  runs. For the vocabulary alone that works: 13,871 runs for 11,643
  nodes. For the population it gives 308,552 runs for 632,282 members,
  about half, because an item has one place in one numbering, under one
  of its parents, and is a run of its own for every ancestor of the
  others.
- **Named combinations in a vocabulary.** A pack that names `red-wine`
  beside `red` and `wine` stores one cell of the product by hand, and the
  node is not the meet (`SEMANTIC_CODES.md` §10). In the shipped
  vocabulary 1,279 nodes have several parents: 694 stand under several
  top-level categories and 585 under one. 731 of them hold, at this root,
  everything below all their parents. (That only 11% of the vocabulary's
  nodes have several parents is good news for an index and bad news for
  the vocabulary: Peter reads it as cross-connections missing, which is
  question 52, in ontodag-core's `docs/UPPER.md` §17.)
- **A memo of meets** (`SEMANTIC_CODES.md` §9). To admit the meet of two
  independent categories is to pay for one cell of the product.

### 7.3 What factors buy

- **An item needs no code of its own.** Its code is one small antichain
  per aspect: its parents. This is §5.3 seen from the factors' side.
- **Within one aspect the vocabulary is close to a tree**, so runs and
  interval labels work there.
- **A conjunction across aspects is a box**: one range in each. Where
  each aspect is a tree and an item has one place in it, a range tree
  answers such a query in the answer's size plus a logarithmic term, for
  every pair of categories at once, and takes little more room than the
  items. A memo of meets needs a cell per pair. Nothing else in this note
  turns "a query costs its smaller cone" into "a query costs its answer".
  The typed dimensions are aspects by declaration (a time is an interval,
  a place a rectangle), so a query over a time, a place and a category is
  already a box; today each has its own index and `get` intersects.
- **The planner** could size an answer before any walk: cones from
  independent aspects overlap as chance predicts, so the shares multiply.
- **Browsing** could group the refinements by aspect.
- **Pictures.** FCA draws a product as a nested line diagram.

### 7.4 Factors are derived, never declared

The standing rules settle this. A declared aspect with force ("a thing
has one colour") is negation, and negation fights merge. So a factor is
read from a pinned root and kept beside the store, as cone summaries are.
It changes when the root changes, and it steers time and display, never
an answer. The declared dimensions stay as they are. Librarians call this
faceted classification (Ranganathan; `PHILOSOPHICAL_LANGUAGES.md`); ROLES
kept the word *facet* out of OntoDAG's vocabulary, and this note says
*factor*.

Three ways to read factors from a root:

1. **The top-level categories.** The shipped vocabulary has 16. 9,348 of
   its 11,643 nodes stand under one of them, 2,206 under two and 88
   under three or four.
2. **Counts.** Two groups of categories are independent when their cones
   overlap as chance predicts. This is mdl-fca's test, that a concept
   across two factors pays no rent, and it needs items, not only a
   vocabulary.
3. **FCA's own.** The arrow relations of a reduced context, which take
   polynomial time to compute, describe every way to write its lattice as
   a subdirect product (Ganter and Wille, chapters 3 and 4). But the
   finest such writing is too fine to use: for a distributive lattice it
   has one two-element factor per attribute, which is the code itself.
   The algebra alone does not pick the few coarse factors that matter.

The plan is to start from the first and check it with the second on a
real store.

### 7.5 FCA's statements of the same facts

Two blocks of attributes over the same objects (apposition) give a
lattice that embeds in the product of the two blocks' lattices and equals
it when every combination occurs. The direct sum of two contexts gives
exactly the product of their lattices. Every finite lattice is a
subdirect product of ones that factor no further (Birkhoff). mdl-fca's
note, §5, sets these beside its theorem.

## 8. Steps, each behind its gate

0. **Done:** the probe.
1. **Done (2026-11-12): write a store's context for other programs.**
   `experiments/context_export.py`, no new command. From a store or from
   shipped packs it writes a Burmeister `.cxt` file, FCA's common
   exchange format (ConExp and In-Close read it), the same table as a
   `.npy` array for mdl-fca, and a `.json` file with the names, the
   store's own edges among them and the knowledge id the table was made
   from. The objects are the store's items, the attributes the categories
   above them, a cross the order `get` answers by. For the shipped
   vocabulary: 8,795 objects, 2,847 attributes, 39,522 crosses (265 of
   them from the computed order of terms), 2,944 different rows. Below
   `place` alone: 439 objects, 183 attributes, 1,601 crosses, 175
   different rows. For the store of real places (§6): 9,876 objects by
   397 attributes, of whose 366 categories mdl-fca's learner returns 291
   to within one attribute (its roadmap §11). **The table belongs to one
   knowledge id.** A new
   version of a pack, or a changed store, has another id, and the script
   is run again; the script itself reads the store through `ontodag.open`,
   `get` and `get_ancestors`, and need not change with it.
2. **Rows for the vocabulary, in memory**, behind `is_below`'s last step,
   the planner's probe and `browse.refinements`. Gate: a real store where
   one of the three takes long enough to notice. Oracle: the climb, with
   the index on and off, on random stores and at random points of a
   replay. Count-based test: filing a leaf touches no row. The state is
   declared in `_declare_state` and fed through `_on_node_added`.
3. **Columns as bit sets**, for `odag count` and for refinements without
   a sample. Gate: as step 2, and a compressed form before 10^5 nodes.
   Oracle: I5, a column's size is the stored count.
4. **Factors read from a root** (§7.4, the first way, checked by the
   second on a real store), used to group refinements and to size
   answers.
5. **A memo of meets** that knows the factors, and box queries over the
   typed dimensions (`SEMANTIC_CODES.md` §9). Gate: a query log.

Steps 2 to 5 keep `SEMANTIC_CODES.md` §8's order and add to it the marks
of §5 and the factors of §7.

## 9. Question 51: what to do first (decided B by Peter, 2026-11-12)

Step 1 is built (§8). The question as it was put:

A two-term query over 30,000 made-up items takes 5.7 ms today and would
take under a millisecond with bit sets. No store we have is that large.

- **A. Leave it parked.** The probe and this note are the result.
  For: nothing is slow, and there is no code to carry. Against: we learn
  nothing more until something hurts.
- **B. Step 1 now.** For: it is small, an experiment script with no
  public surface; it gives mdl-fca real ontologies to learn from at once;
  and it lets us run FCA's programs on OntoDAG's data and see the lattice
  of a real store. Against: one more script to keep.
- **C. Steps 2 and 3 now.** For: browsing loses its sample, and counts
  become cheap. Against: it goes against the gates, and it adds state to
  a class of 5,000 lines whose size the review already questioned
  (item 14), for stores of a few thousand nodes.

Recommended: **B, then wait.** It costs least, and it is the one step
that serves both projects.

## 10. What stays out

No change to the stored form, the contract, the registry or any root. No
new kind. No declared factors. Codes do not become names
(`SEMANTIC_CODES.md` §1). Nothing a learner finds enters the shared graph
except as someone's asserted claim (`paper/sections/08-learn-from-fca.tex`).

## References

- R. Agrawal, A. Borgida, H. V. Jagadish, "Efficient Management of
  Transitive Relationships in Large Data and Knowledge Bases," SIGMOD
  1989.
- R. Belohlavek, V. Vychodil, "Discovery of optimal factors in binary
  data via a novel method of matrix decomposition," J. Comput. Syst.
  Sci. 76, 2010.
- J. P. Bordat, "Calcul pratique du treillis de Galois d'une
  correspondance," Math. Sci. Hum. 96, 1986.
- C. Carpineto, G. Romano, *Concept Data Analysis: Theory and
  Applications*, 2004.
- E. Cohen, E. Halperin, H. Kaplan, U. Zwick, "Reachability and Distance
  Queries via 2-Hop Labels," SODA 2002.
- S. Ferré, O. Ridoux, "An introduction to logical information systems,"
  Inf. Process. Manag. 40, 2004.
- B. Ganter, "Two basic algorithms in concept analysis," 1984.
- B. Ganter, R. Wille, *Formal Concept Analysis: Mathematical
  Foundations*, 1999.
- C. Lindig, "Fast concept analysis," ICCS 2000.
- D. van der Merwe, S. Obiedkov, D. Kourie, "AddIntent: A New
  Incremental Algorithm for Constructing Concept Lattices," ICFCA 2004.
- G. Stumme, R. Taouil, Y. Bastide, N. Pasquier, L. Lakhal, "Computing
  iceberg concept lattices with Titanic," Data Knowl. Eng. 42, 2002.
- J. Su, Q. Zhu, H. Wei, J. X. Yu, "Reachability Querying: Can It Be
  Even Faster?", IEEE TKDE 29, 2017.
- R. Wille, "Boolean Concept Logic," ICCS 2000.
- H. Yildirim, V. Chaoji, M. J. Zaki, "GRAIL: Scalable Reachability
  Index for Large Graphs," PVLDB 3, 2010.
- mdl-fca: `note/product-of-dags-note.tex`, `docs/06-roadmap.md`.
