# Roles as Dimensions: One Meaning for Below

Status: **discussion draft, 2026-10-06** (the review of the
`swarm-sharing` branch with Peter, which turned from keys to what a
sharing edge means; revised the same day after his questions on roles
and dimensions, spelling, and Tokyo and Japan, and his decision to call
them all dimensions). §8 records what Peter settled; everything else is
open. It was proposed, like BINDING.md, as a scoped amendment to the
contract's standing decision that the core gains no further
expressiveness, staying in front of the arbitrary-relations wall
(DATABASE_DIRECTION.md) rather than crossing it. Peter accepted the
amendment as **contract 0.2** on 2026-10-06 (CONTRACT.md §2, §5.1 and
O6). Examples marked *today* were executed against 0.28.0; everything
else is proposed. **Built since (2026-10-06, unreleased):** steps
3.1–3.4 of §9 — the one meaning in HOW_IT_WORKS.md, the transitive kind
that `in` is declared under (DIMENSIONS.md §16), the enclosing kind for
`about`, `from`, `to` (§17), and the reversed kind for `for` (§18).
Peter then settled three more points: `in` covers places and parts but
not membership, `geo` stays apart from `in` for now, and the second kind
is called `enclosing-dimension` (§8, items 8–10).

## 0. In short

- **Below means one thing:** inclusion between classes of items. `x ⊑ y`
  says every item in x is in y.
- **There are three kinds of name.** Items go directly under the *kinds*
  they are (`book`, `planet`) and the *qualities* they have (`blue`,
  `weight(3kg)`). Only *entities* (`japan`, `mars`, `john`) need a
  relation in between: `in(japan)`, `about(mars)`, `for(john)`.
- **The single edge type stays.** The relation lives in the name, not in
  the edge.
- **Relations to entities are dimensions too.** `about(mars)` is a
  dimension term whose argument is a node, as `weight(3kg)` is one whose
  argument is a value. Both are a head applied to an argument, and the
  head's kind says how terms are ordered. Users declare dimensions
  freely today; only kinds are in code.
- **One word: dimension**, for both (§8). Nothing stored is renamed.
- **What's new:** three kinds (transitive, enclosing and reversed), a way
  to declare a narrower relation, and one guard.
- **Not changed:** BINDING.md's limit. Flat terms are sound as long as
  each one is a claim on its own: Zermatt in Switzerland and in the Alps
  is two true claims. A two-leg journey, whose `from` and `to` must stay
  paired, still needs bundles.

## 1. The problem

OntoDAG deliberately has one edge type. It doesn't separate *instance of*
from *kind of* the way Cyc (`isa`/`genls`) and Wikidata (P31/P279) do,
because the line between them is less stable than it looks: an instance
can turn out to be a category later. `linux` names one operating system,
and yet the computing pack files `android ⊑ linux`, treating it as a
family. With one edge type, nothing has to be retyped when that happens.

In practice, though, "below" has been used for more than one thing:

| Edge | Meant | Inclusion? |
|---|---|---|
| `dog ⊑ mammal` | dogs are mammals | yes |
| `mars ⊑ planet` | Mars is a planet | yes: a class with one member |
| `medieval-japan ⊑ japan` | Japan in one period | yes: a phase of Japan |
| `old-atlas ⊑ blue` | the atlas is blue | yes, reading `blue` as "blue things" (§2) |
| `tokyo ⊑ japan` | Tokyo is in Japan | only if both name regions (§5) |
| `boarding-pass ⊑ japan` | it belongs to the Japan trip | no |
| `email ⊑ john` | about John, or readable by John | no |

The last three use an entity as if it were a quality: "things in Japan",
"things about John". That reading is sound on its own. The trouble is
one name standing for two classes: `mars` the planet, one member of
`planet`, and `mars` as "things about Mars". Where the two meet in one
cone, transitivity joins them and the answers go wrong. *Today*, with the
shipped `space` pack adopted (`odag pack space`):

```
$ odag put mars-rover-photo.jpg mars photograph
$ odag get planet photograph
mars-rover-photo.jpg
$ odag below mars-rover-photo.jpg celestial-body
true
```

It matters more for OntoDAG than for a tagging tool:

- **Merge.** Two writers can each be consistent while their union
  isn't. Packs make that routine: adopt `space` into a store whose photos
  sit under `mars`.
- **Certificates.** The `true` above can be proved to a stranger
  (`prove_below`).
- **Sharing.** SHARING.md Q1 hit the same collision: one address means
  "from Alice" in one store and "for Alice" in another.

## 2. One meaning, three kinds of name

Every node is a class of items, and `x ⊑ y` means every item in x is in
y. That is how the FCA paper reads OntoDAG (a node is an attribute of
the items below it), and it is how typed values have always worked:
`weight(3kg)` is the things that weigh 3 kg, not the quantity.

**The test for any edge:** whatever is true of every y must be true of x.
`medieval-japan ⊑ japan` passes: Japan is a country, and so was medieval
Japan. `tokyo ⊑ japan` fails: Japan is a country, and Tokyo is a city.

Names come in three kinds, and the test treats them differently:

- **Kinds** are common nouns: `dog`, `city`, `planet`, `book`. Items go
  under what they are. An individual is a kind with one member
  (`mars ⊑ planet`), and it can gain members later: `japan` gains its
  phases, `medieval-japan ⊑ japan`, with nothing retyped.
- **Qualities** are adjectives, and every typed value is one: `blue`,
  `heavy`, `weight(3kg)`, `time(2026)`. Items go under what they have. A
  quality reads as the things that have it, so `blue` is blue things, and
  `blue ⊑ color` says blue things are colored things, which is still true.
  `old-atlas ⊑ blue` passes the test. Core's attribute branch reads
  naturally this way, and so do the dimension declarations: `weight` is
  things that have a weight, `linear-dimension` things with some linear
  measure, and `attribute` things with some attribute. That is why a crate
  under `weight(3kg)` is below `attribute` *today*, and correctly so: the
  crate has an attribute.
- **Entities** are proper names: `japan`, `tokyo`, `mars`, `john`,
  `linux`. They have kinds of their own (Tokyo is a city), which the
  things related to them don't share, so the adjective reading fails:
  things in Tokyo aren't cities. Only an entity's instances and phases go
  directly under it. Everything else goes under a relation of it.

Every failure in §1 is an entity used as a quality.

## 3. Relations are dimensions

A head names a relation between an item and an argument. `weight(3kg)`
relates an item to a value (it weighs 3 kg); `about(mars)` relates an
item to a node (it is about Mars). The mechanism is the same: a term is a
head applied to an argument, and the head's **kind** says how terms are
ordered. Arithmetic kinds (linear, calendar, count, prefix) order values
from their spelling; the graph kind orders nodes by the graph. Nothing in
the code separates the two, and this draft doesn't either.

The docs have used three words for this: a *dimension* is a head filed
under a kind node (`weight`), a *role head* is a head filed under another
head (`posted` under `time`, DIMENSIONS.md §14), and a *kind* is how
terms are ordered. From here on, all of them are **dimensions** (§8).
`about`, `in` and `for` are dimensions whose arguments are nodes, and a
dimension filed under another dimension takes its values. *Role*
survives only as the description-logic word for the relation a
dimension names, as in BINDING.md.

`about` exists *today*, declared under the graph kind (DIMENSIONS.md
§15, 0.26.0). In the same store as §1:

```
$ odag put graph-dimension dimension
$ odag put about graph-dimension
$ odag put mars-rover-photo.jpg 'about(mars)' photograph
$ odag get planet photograph
$ odag get 'about(planet)' photograph
mars-rover-photo.jpg
$ odag below mars-rover-photo.jpg 'about(celestial-body)'
true
$ odag below mars-rover-photo.jpg celestial-body
false
```

`about(mars) ⊑ about(planet) ⊑ about(celestial-body)` follows from
`mars ⊑ planet ⊑ celestial-body`. The photo is about a celestial body,
and it is not a planet.

Entities relate to each other through heads too: `tokyo ⊑ city` and
`tokyo ⊑ in(japan)`, never `tokyo ⊑ japan`. People are ordered by kinds,
`alice ⊑ sales-employee ⊑ employee`, not by `in` (§5).

**A quality needs no head.** `old-atlas ⊑ blue` already says it. A
`color(...)` head would give blue things a second name, `color(blue)`,
and what was filed under one name would not be found under the other.
Heads are for qualities whose values are computed (`weight(3kg)`), and
for relations to entities (`in(japan)`).

## 4. Kinds, and narrower relations

The code separates names from kinds. Heads are declared in a store, any
number of them; kinds are in code, and each has its own correctness
argument. *Today*, after `odag prelude`, a user's own dimensions need no
code, whether new or taking another dimension's values:

```
$ odag put reach linear-dimension
$ odag put robot-arm 'reach(80cm)'
$ odag below robot-arm 'reach(..1m)'
true
$ odag put arrival time
$ odag put flight-ba123 'arrival(2026-10-06T10:00:00Z)'
$ odag get 'arrival(2026-10)'
arrival(2026-10-06T10:00:00Z)
flight-ba123
```

A user's own *kind* is refused, since a kind is code:

```
$ odag put my-kind dimension
$ odag put smell my-kind
$ odag put rose 'smell(sweet)'
odag: unknown super-category: 'smell(sweet)' (create with `odag put NAME` first)
```

That refusal is right, but its message isn't. It suggests creating
`smell(sweet)` as a plain name, which would make an opaque atom; it
should say that `my-kind` is not a kind and list the ones that are.

Dimensions over nodes follow the same split:

- **Names: any number, declared in the store**, by a user or a pack:
  `received`, `departure`, `arrival`, `check-in`.
- **Kinds: few, in code.** Node arguments need three. Below, `⊑*` is the
  combined order:

| Kind | Rule | Example | Today |
|---|---|---|---|
| follows the order | `R(x) ⊑ R(y)` iff `x ⊑* y` | `about(mars) ⊑ about(planet)` | works (graph kind) |
| follows the order and `in` | `R(x) ⊑ R(y)` iff `x ⊑* y` or `x ⊑* in(y)` | `in(tokyo) ⊑ in(japan)`; `departure(gate-b12) ⊑ departure(lhr)` | missing |
| reversed | `R(y) ⊑ R(x)` iff `x ⊑* y` | `for(employee) ⊑ for(alice)` | missing |

"Missing" was checked. A photo under `in(tokyo)` is not below `in(japan)`
today, whether `in` takes `geo`'s values or is a graph-kind head. Built
since: the second row as the transitive and enclosing kinds (steps
3.2–3.3), the third as the reversed kind (step 3.4).

Proposed assignment:
- `in`, `about`, `from` and `to` follow the order and `in`. For `in`
  itself, that is transitivity. Built as two kinds: `in` under the
  transitive kind (DIMENSIONS.md §16), and the heads that follow `in`
  without chaining under the enclosing kind (§17).
- `for` is reversed (§6), and follows kinds only, not `in` (§7).
- Heads whose argument is a kind rather than an entity, such as
  loopmarket's `transport(...)`, only follow the order.
- Dimensions over time (`posted`, `received`) stay what they are: they
  take `time`'s values.

**Narrower relations.** A departure is a narrower kind of "from", so
`departure(lhr) ⊑ from(lhr)` should hold; today it doesn't (checked).
This needs a declaration of its own, because filing one head under
another already means something else (DIMENSIONS.md §14): the lower head
uses the upper head's *space* and kind, without being a narrower
relation. The difference is real. `max-load` declared under `weight`
takes weight values, but a truck with `max-load(3000kg)` doesn't weigh
3000 kg, and *today* it is correctly not below `weight(3000kg)`. It is
below the bare head `weight`, though, which reads "has a weight": a small
wrong answer that the same separation fixes. So "uses that space" and "is
a narrower relation" are two declarations (§8).

This is the same split as units (any unit may be declared, but only by
reduction to a built-in anchor), and as core and the packs. **Anything
is allowed as a name; a new kind needs code** and a correctness
argument.

**Style rule**, which the surface layer can teach: *a head names one
relation; types and limits go in the argument.*

- `departure-from-gate(B12)` becomes `departure(gate-b12)`.
- `check-in-by(10:00)` becomes `check-in(..10:00)`, a range on a time
  dimension.
- `received-date(...)` becomes `received(2026-10-06)`.

**Narrower relations make free naming safe.** If one person declares
`departure` and another `departs`, both as narrower relations of `from`,
a query for `from(lhr)` finds both. The few broad relations are where
stores meet when they merge.

## 5. `in`, for places and parts

One relation covers places and parts, because they chain together: Tokyo
in Japan in Asia, an engine in a car in a garage (so the engine is in
the garage). A separate `part-of` relation would chain identically, and
would give users two names to choose between.

**Membership is not `in`** (settled, §8). The first draft had a third
case, Alice in sales in Acme, but membership chains wrongly with the
other two. If the sales department is in the Ljubljana office and Alice
is "in" sales, then `in` puts Alice in the Ljubljana office, though she
may work from home (checked on the 3.3 code: `alice ⊑ in(sales)` and
`sales ⊑ in(ljubljana-office)` give `alice ⊑ in(ljubljana-office)`).
Membership is said by kinds instead: `alice ⊑ sales-employee ⊑ employee`.
That passes §2's test, since whatever is true of every sales employee is
true of Alice. It also separates two things that membership by `in` ran
together: the department, an entity with a location
(`sales-department ⊑ in(ljubljana-office)`), and its staff, a kind with
members (`sales-employee`). The code can't enforce this, since it can't
tell a person from a place, so it is a modeling rule for the docs and
the surface layer to teach.

**Regions are the exception that proves it.** If `tokyo` and `japan` name
regions (sets of places on the map), then `tokyo ⊑ japan` is plain
inclusion. That is how the geo dimension treats places today: a place is
below the cells it lies in, and `geo(u2e4)` means "located in the cell
u2e4". But a region is not a city, so the same names can't also be the
city and the country. This draft keeps the names for the entities and
says containment with `in`. Note that `medieval-japan ⊑ japan` is a
*phase*, not a region: as regions, medieval Japan isn't inside modern
Japan (the borders moved), but as a phase it passes the test of §2.

`in` is **strict**: Japan is not in Japan, so `get in(japan)` lists what
is inside Japan, not Japan itself.

**What `in(in(japan))` means.** `in(japan)` is the things located in
Japan: Tokyo, Mount Fuji, a photo taken in Kyoto. Applying `in` again,
`in(in(japan))` is the things located in something that is located in
Japan. A photo taken in Tokyo is one: it is in Tokyo, and Tokyo is in
Japan. Tokyo itself is one only if it lies in something that is in
Japan, such as the Kanto region. Nobody needs to type this. It matters
because terms nest, so every nesting needs exactly one meaning and one
name.

**Isn't that the same as `in(japan)`, since `in` is transitive?** Only in
one direction. Transitivity says that if X is in Y and Y is in Japan,
then X is in Japan, so everything in `in(in(japan))` is in `in(japan)`.
The other direction would need everything in Japan to be inside
*something else* that is in Japan, and transitivity doesn't say that.
"Less than" on whole numbers shows the gap: anything less than something
less than 5 is less than 5, but 4 is less than 5 without being less than
anything that is less than 5. In a store: if the Louvre's pyramid is
filed directly in the Louvre, in no wing, then it is in the Louvre but in
nothing that is in the Louvre, so `in(in(louvre))` (things in some part
of the Louvre, such as the Mona Lisa in the Denon wing) is the smaller
class.

On a continuous map the two would coincide, since anything inside Japan
lies inside some smaller region of Japan. But a store only knows the
parts it has been told about: it is like the whole numbers, not the
line. The two would also coincide if Japan counted as inside itself,
because then anything in Japan is "in something that is in Japan",
namely Japan. That is the reflexive reading this draft avoids. One class
with two names would need a rule rewriting `in(in(x))` to `in(x)`; two
different classes need no rule.

Strictness needs one **guard**, the counterpart of the cycle check:
refuse any edge after which something would be inside itself
(`x ⊑* in(x)`). Without it, `x ⊑ y` together with `y ⊑ in(x)` would make
`in(x)` and `in(y)` contain each other, giving one class two names,
which the core forbids (DIMENSIONS.md §15, I1). Every such case passes
through `x ⊑* in(x)`, so one guard covers them all.

`about` follows `in` too: a photo about Tokyo is about Japan. Library
thesauri make the same choice, searching a narrower *partitive* term
under its broader one.

## 6. Reversed dimensions, and the word "contravariant"

Access runs against membership: what is for the whole group is for each
member. So `for` reverses the order it follows. `alice ⊑ employee` gives
`for(employee) ⊑ for(alice)`, and `alice ⊑ sales-employee` gives
`for(sales-employee) ⊑ for(alice)`. SHARING.md Q1 rejected a
`shared-with(alice)` role term because role heads were covariant; a
reversed dimension removes that objection.

The words come from category theory. A map between two orders is
**covariant** if it keeps their direction, and **contravariant** if it
reverses it. The closest everyday analogy is from programming: function
parameters are contravariant. If every cat is an animal, a function that
accepts any animal can be used wherever one that accepts cats is
needed, and `for(G)` behaves like such a parameter: "for any member of
G". Tensor calculus uses the same word for components that change
opposite to their basis. What the two uses share is only "the opposite
direction": there is no metric or index here, so that analogy stops at
the word. User-facing docs can just say "reversed".

## 7. Sharing with `for`

Today (SHARING.md §2) a group is filed below its members:
`employees ⊑ ada`, `employees ⊑ bob`. That uses each person as a
quality ("things for Ada"). It collides with "from" facets (Q1), and it
can't coexist with membership, because `employees ⊑ ada` and
`ada ⊑ employees` form a cycle.

With `for`:

- people and groups are ordered by kinds
  (`alice ⊑ sales-employee ⊑ acme-employee`);
- items are filed under `for(...)`, for example
  `q3-plan ⊑ for(sales-employee)`;
- **what Alice may see is everything below `for(alice)`.** It is still
  one cone, because
  `for(acme-employee) ⊑ for(sales-employee) ⊑ for(alice)` is computed.

`for` follows kinds only, not `in`. Following `in` would turn a location
fact into an access grant: whoever filed Alice as living in Tokyo would
thereby give her whatever is `for(japan)`. Access should change only when
someone files a person under a group.

Consequences:

- Members still don't see each other, and groups are no longer shared
  as items: `bob` is below no `for(...)` term.
- Public content goes under `for(everyone)` or `for(person)`, whichever
  node every person is under.
- The key plan needs no new mechanism, since it already follows computed
  edges. Its walk becomes `for(alice)`, then `for(sales-employee)`, then
  `for(acme-employee)`, then down to the items. A principal is a person,
  and their grantee entry opens `for(alice)`.
- Q1's leaning, a declared `principal` node, may give way to its option
  (c): whatever is below a `for(...)` term is shared, and the term says
  so.

## 8. Decisions and open questions

**Settled 2026-10-06** (Peter accepted the leanings):

1. One structural relation, `in`, for places and parts (§5). The first
   version included membership; item 9 took it out.
2. `about` follows `in` (§5).
3. Terms render readably: `in(tokyo)` as "in Tokyo".
4. US spelling in the syntax: `color`, not `colour`.
5. One word, **dimension**, for heads over values and over nodes alike.
   *Facet* was rejected: it means faceted classification, which is a
   different thing. *Role* would have meant renaming the six node names
   the prelude stores; keeping *dimension* renames nothing.
6. `in` is strict, with the guard of §5.
7. Qualities read as adjectives (§2), so a quality needs no head and the
   blue book needs no `color(...)`.

Settled later the same day, after step 3.3:

8. The kind for `about`, `from` and `to` is called **`enclosing-dimension`**
   (DIMENSIONS.md §17), for what it follows: whatever encloses the
   argument. It was `relation-dimension` while unreleased, but every
   head names a relation, so that name didn't say which.
9. **Membership is said by kinds, not by `in`** (§5):
   `alice ⊑ sales-employee ⊑ employee`. Membership by `in` chained into
   location.
10. **`geo` and `in`: (a) now, (b) as the target.** They stay apart, and
    meet by assertion: filing a cell under a named place,
    `geo(u2e4) ⊑ in(ljubljana)`, puts whatever is located in the cell, at
    any precision, `in(ljubljana)`, while Ljubljana stays a city
    (checked). The reverse is not derived. The bridge (b) comes when a
    consumer needs named places and cells in one query. It became sound
    only with item 9, because a member of a department is nowhere on the
    map. `in` stays the wider of the two: it also takes places with no
    coordinates, such as Middle-earth, and places whose coordinates
    don't help, such as an aisle in a supermarket.
11. **The contract is amended to 0.2** (CONTRACT.md): what an arrow means
    (§2), dimensions over nodes as a scoped exception to "no further
    expressiveness" (§5.1), and the writer's obligation O6. A new kind is
    a clause change; a new head never is.
12. **A relation term goes only under its head** (applied by Claude in
    step 3.4 as a consequence of item 11; confirmed by Peter the same
    day: "We expect very large graphs, so exponential is out of the
    question"). Filing
    `for(board)` under `secret` says that everything for the board is
    secret: a rule, which §5.1 keeps out. Random worlds showed the cost of
    allowing it: the evaluation went exponential. What it would have said
    can be said per item (file the minutes under both), or by a layer
    above the store.

**Open:**

- **Where the standard dimensions live.** The code would refer to `in` by
  name, so by PACKS.md's tiering rule (the prelude holds the names the
  interpreter dereferences) `in` belongs in the prelude, probably with
  `about`, `for`, `from` and `to`. Changing the prelude moves its golden
  root and, through core, the root of every pack and every published
  pack store (DIMENSIONS.md §15). *Leaning:* do it once, together with
  the pack audit.
- ~~**`geo` and `in`.**~~ Settled as item 10. The options were (a)
  *leave them apart*, each answering its own queries, nothing changing
  for loopmarket; (b) *bridge them*, letting `in(x)` follow x's cell, a
  cross-head rule; (c) *migrate* loopmarket's `from`/`to` from roles of
  `geo` to the enclosing kind over named places, which renames stored
  values and so needs a coordinated release of both repos.
- **How to declare a narrower relation** (§4), as distinct from "uses
  that space".
- ~~**Transitive dimensions besides `in`.**~~ Answered by step 3.2: the
  kind is general (`transitive-dimension`), so `in` is one head under it
  and a user's `descended-from` or `upstream-of` is another, each with
  the guard (DIMENSIONS.md §16).
- **How the surface knows a name is an entity**, so that it can offer a
  dimension, such as `about(...)` or `in(...)`, when someone files under
  it. Candidates: any node with a kind above it in a pack, or an
  explicit declaration. *Leaning:* offer, never rewrite silently.
- ~~**The contract.**~~ Settled as item 11.
- **The audience dimension's name:** `for` or `shared-with`.
- **US spelling in names.** Core and the domain packs hold 17 names with
  British spellings (`orange-colour`, `ash-grey`, `centre`, `storey`, …).
  Six are paired with a US spelling of another sense, so the spelling is
  what tells the two apart: `draught` (air) and `draft` (text),
  `programme` (a show) and `program` (software), `centre` (a place) and
  `center` (a building), `mould` (a container) and `mold` (a fungus),
  `honour` (status) and `honor` (a quality), `labour` (a class) and
  `labor` (work). Those need real names, not respellings. `storey` would
  become `story`, which an everyday sense already owns. Renames don't
  travel by merge (EVOLUTION.md), so they belong in the same core version
  as the audit.

## 9. What changes, and in what order

**Code.** The two missing kinds, narrower relations and the guard, each
inside the one combined order: `is_below`, `get`, reduction, the lazy
reader and certificates. This is the same kind of work as role heads
(#15) and the graph kind (#19). As with role heads, the new computed
edges need re-reduction when the entities they depend on move
(DIMENSIONS.md §14, "stored form stays canonical"). Against the
contract's two axes (CONTRACT.md §5): it is monotone; and the order stays
computable from names plus the graph, as it does for role heads and the
graph kind, because kinds are fixed in code and users can't add axioms.
That second claim is what the property tests in step 3.2 must back.

**Core and packs change less than it looks.** They were built from is-a
sources, and is-a edges are right under this reading.
- A narrow scan of the 7,734 pack edges (named suspects only, not an
  audit) found about a dozen part-of edges. Most are hand-asserted crypto
  terms in economics (`mempool ⊑ bitcoin`, `beacon-chain ⊑ ethereum`),
  plus `air-mass ⊑ atmosphere`. They become `in(...)` or `about(...)`. A
  real audit would use ontodag-core's evidence files, since Wikidata
  keeps part-of separate from subclass-of.
- CORE.md's reason for hooking the dimension kinds under `attribute`
  says "a value is an attribute" and "a geo value is a place". Under §2 a
  value is a quality of the items under it, and the edge stays; only the
  sentence changes.
- The spelling renames of §8.

**Usage changes more than the vocabulary does.** People file under
`about(mars)` instead of `mars`, and the surface layer has to make that
easy. Existing stores stay valid: a store that files under a bare
`japan` and never says `japan ⊑ country` is consistent, and the surface
can offer the rewrite (`odag move`) when a pack makes the name an
instance.

**Order** (proposed):

1. **main:** this draft.
2. **main:** the `act` token fix (a rotated child's token reused its
   unrotated parent's keystream; found in the swarm-sharing review),
   with the CHANGELOG correction, plus the branch's independent pieces:
   the pure-Python secp256k1 fallback with its tests, and the web
   command-count fix. It's small and independent of everything here, so
   it can be released on its own.
3. **main, step by step.** Each step is additive with the suite green,
   and nothing is released until the last:
   1. ~~the one meaning and the three kinds of name, stated~~ — done
      2026-10-06 in HOW_IT_WORKS.md §1, and in CONTRACT.md as 0.2;
   2. ~~`in`: strict, transitive, the guard; property tests for
      reduction and merge, as role heads had~~ — done 2026-10-06 as the
      general transitive kind (DIMENSIONS.md §16, registry 4.3,
      `tests/test_transitive.py`);
   3. ~~`about`, `from` and `to` following `in`~~ — done 2026-10-06 as
      the enclosing kind (DIMENSIONS.md §17): `about`, `from`, `to` are
      heads a store declares under it. `geo` stays apart (§8 item 10);
   4. ~~reversed `for`, following kinds only (§7)~~ — done 2026-10-06
      as the reversed kind (DIMENSIONS.md §18). Building it found two
      things: a term filed under anything but its head states a rule and
      made the evaluation exponential, so all three relation kinds now
      refuse it (§8 item 12); and an edge could close a loop through a
      computed link it creates, in the graph kind and role heads too, now
      refused;
   4a. ~~output-sensitive hops~~ — done 2026-10-07 (DIMENSIONS.md §19),
      after Peter's "we expect very large graphs". Filing is flat in the
      number of terms per head for every kind (0.3–0.9 ms per put at
      3,200 terms), queries cost in proportion to their answers, deep
      chains file at 0.22 ms per place. Two more exponential paths found
      and removed on the way (the meet fallback, the graph kind's parse
      re-checks);
   5. narrower relations;
   6. the surface layer: offer `about(...)`, `in(...)` and `for(...)` for
      entity names, and render them;
   7. the prelude's new dimensions, the pack audit and the spelling
      renames, so golden roots move once; packs republished to Swarm;
   8. the guide's examples; release.
4. **swarm-sharing:** rebase onto main once `for` lands (step 3.4), then
   do the keyplan consolidation with principals as people and shares
   under `for(...)`; merge when it's done.

**Where this draft goes as it lands.** It stays in `plans/` while it is
discussed, since `docs/` describes only what is shipped. As each step is
built, its part moves into a design record: the one meaning and the
three kinds of name into HOW_IT_WORKS.md and CONTRACT.md (done, 0.2);
the new kinds and narrower dimensions into DIMENSIONS.md, as sections
after §15, the way §14 and §15 were added when they shipped; and §7 into
SHARING.md. This file then shrinks to a pointer.
