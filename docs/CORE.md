# The `core` pack: an upper ontology built by consensus

Design record for `src/ontodag/core_ontology.py`, shipped as the pack
`core` (v4, 2026-09-03; v3 shipped in 0.19.1 and v2 in 0.19.0 the day
before, both superseded — see Versioning). The list is **generated** in the sister repository
[ontodag-core](https://github.com/petfold/ontodag-core); this page says
what the pack is for, how it was built, how a node earns its place, and
what it deliberately cannot do. `odag pack core --show` prints the list.

## Taxonomy without teeth

OntoDAG states subsumption and nothing else, so this top ontology has
**branches and no fences**. It can say that every plane ticket is a
transport ticket is a ticket is a document; it cannot say that a document
is not a mammal, and nothing here refuses a filing that mixes them (the
disjointness wall, `DATABASE_DIRECTION.md`). The discipline a top ontology
usually gets from partitions arrives here as convention, `merge --diff`
and `pack --diff` preview, and the review workflow on the agent surface,
never as refusal.

What the pack *does* give is the thing a flat tag set cannot: paths. Query
`document` and the invoice, the email and the plane ticket are all in the
cone; query `email human` and the mail filed under `email` and `man` is
found, because `man ⊑ human`. The pack's job is to make the common paths
exist before anyone has to build them.

## How version 2 was built

Version 1 (194 categories, hand-written from general knowledge) was
reviewed as good but too small and arbitrary-looking. Version 2 replaces
taste with witnesses:

- **Concepts** are Princeton Core WordNet's 3,299 most frequent nouns plus
  v1's names, each a WordNet synset. The synset is the hub: SUMO aligns
  through its own WordNet mapping, OpenCyc, schema.org, YAGO 4, BFO and
  DOLCE by name, with hand alignments where the automatic ones were wrong
  (WordNet's sense 1 of `whale` is "a very large person").
- **Edges** enter by **consensus**: an edge `A ⊑ B` is in when at least two
  independent sources entail it in their own graphs and none entails the
  reverse, or when Peter accepted it on review. Single-witness edges were
  read one by one against both glosses (about 1,900 judgements; roughly
  one in six rejected — parts filed as kinds, WordNet's wheeled-vehicle ⊑
  container chain, drugs under causal agent, disciplines nested where they
  are siblings). Sources disagreeing on direction leave both directions
  out; near-synonym pairs keep one name.
- **Names** are the one-way door, so they got the review time. A sense that
  shares its word with another sense has its own name (`book-copy`,
  `prepared-dish`, `capital-city`, `constituent-state`); where the more
  filed sense was the qualified one, it took the plain word (`accident`,
  `injection`, `match`, `notebook`, `seat`, `staff`, `claim`, `state`,
  `process`). Nothing is numbered.
- **v2 is a strict superset of v1**: every v1 claim is still entailed.

Every decision, with its reasons, is in ontodag-core's `docs/UPPER.md` §6;
the review files there rebuild the pack.

## How a node earns its place

Every node is inherited by the whole ecosystem and cannot be retracted by
merge (EVOLUTION.md §1: refinement converges, retraction needs
coordination). A version therefore commits exactly two things, **names**
and **the truth of every edge**, and never coverage: adding nodes,
inserting levels and deepening the top all propagate by merge. So the
admission test is *could we conceivably be wrong about it?*, never *would
it be useful?*, and versions are monotone.

- **Two witnesses or a ruling.** No edge rests on one source's habit.
- **Coarse-but-true beats fine-but-arguable.** `organism ⊑ agent` (SUMO and
  DUL) was rejected: a plant is not an agent except in a botanical sense.
- **One reading where a word has two.** A document is information only,
  never also an artifact, though a paper letter is one; a conversation is
  communication, not information, though it carries some.
- **Roles and stages are out.** `pet`, `child`, `adult` are not kinds.

## The ten branches

| branch | what goes under it | size |
|---|---|---|
| `physical-object` | artifacts, organisms, body parts, natural objects | ~1,100 |
| `event` | acts, activities, processes, natural events, changes | ~530 |
| `agent` | persons and groups: can act and be held responsible | ~440 |
| `attribute` | qualities, states, feelings, colours, shapes | ~400 |
| `information` | documents, messages, symbols, music, images, software | ~400 |
| `place` | regions, buildings, rooms, bodies of water, roads | ~180 |
| `substance` | food, materials, chemicals, drugs, fuels | ~170 |
| `cognition` | beliefs, concepts, ideas, skills, methods, the senses | ~120 |
| `possession` | money, debts, income, belongings | ~50 |
| `field-of-study` | sciences, humanities, arts, engineering, medicine, law | ~50 |

Multi-parent nodes are the point of the structure: `human` is a mammal and
a person; `building`, `landform` and `body-of-water` are physical and also
places; `map` is an image and a document.

## Quantities: the registry, not the pack

Measured dimensions (weight, length, temperature, energy, ...) and every
unit spelling (mile, gallon, calorie) belong to the unit registry and the
prelude; the pack ships none of them as categories, and neither the time
nouns nor the quantity nouns. It asserts the connection once, at kind
level: `linear-dimension`, `count-dimension` and `calendar-dimension` are
attributes, so every present and future head and every value inherits the
attribute branch (`geo-dimension` is left out: a geo value is a place).
The pack therefore presumes the prelude, and `pack core` applies it first.
Currency denominations (`dollar`, `penny`) are synonyms of the fiat pack's
unit spellings and are absent too; `money`, `cash`, `coin` stay.

## The sciences: hinges here, contents in packs

A science contributes its **hinge** to core — the highest node a
non-specialist files under (`disease`, `chemical-element`, `cell`,
`planet`) — so that a domain pack merges onto a shared anchor. Its
**contents** (the 118 elements, the tree of life, ICD) are packs with
their own sources and versioning. Numbers are values, not nodes;
mathematical structures need qualified names (`mathematical-group`) and
therefore belong in a pack. When unsure, pack.

## What it is not

- **Not roles.** `author`, `owner`, `sender`, `pet` are relations to a
  filler: dimension heads or plain categories on the item, per the
  flat-roles rule (USER_GUIDE §5.12).
- **Not the math skeleton.** Number kinds and the registry reflection are
  EVOLUTION.md §3's separate first upper pack; the three kind-level edges
  above are the only place the pack touches the registry.
- **Not inference.** The pack knows *that* every mammal is a vertebrate,
  never *why*.
- **Not the prelude.** PACKS.md principle 3: the prelude holds only names
  the interpreter dereferences. `core` is pack-tier by distribution and
  prelude-grade in governance: adopt it with one command, and expect its
  versions to be rare, argued, and monotone.

## Versioning and verification

**v3 supersedes v2 within a day.** v2 (0.19.0) shipped with 106 names that
still carried WordNet field suffixes (`condition.state`, `organ.body`,
`king.artifact`) — the naming pass had run before the attribute, possession
and cognition branches were added and was never re-run — and without the
three kind-level edges. v3 names every one of them by hand under the
decision-6 rule (the more-filed sense takes the word: `tooth` is the body
part and the gear tooth is `gear-tooth`), drops sixteen near-duplicates, and
carries the edges. A store that adopted v2 keeps its old names; nothing
merges them away, which is exactly why the fix went out the same day.



**v4 (0.20.0, 2026-09-03): Wikidata joins the witnesses.** 2,085 of the
core's concepts align to Wikidata exactly (through its WordNet synset ids,
P8814, and the 3.1→3.0 sense-key bridge), so the subclass edges among those
items are a fourth independent source. Against v3: 13 concepts newly
placed, about 80 gain a parent (`doctor ⊑ professional`, `singer ⊑
musician`; `cave`, `glacier`, `hill`, `ridge`, `mountain-range`, `valley`
and `cliff` ⊑ `landform`; `fog ⊑ cloud`; `bill ⊑ cash`; `option ⊑
contract`), nothing lost — published edges are sticky by construction, and
Wikidata's two contradictions of v3 (`money ⊑ currency`, `research-worker ⊑
scientist`) are queued for a ruling rather than retracted. Three **sense
corrections**, each an intervention against the published name and made
now because a sense, like a rename, never propagates by merge: `dividend`
is the company dividend (v3 had WordNet's "a bonus; something extra");
`meteorology` is the science (v3 had "predicting what the weather will be",
and unplaced); `star` is the physical star (v3 had "any celestial body
visible as a point of light" — the edge `star ⊑ celestial-body` is the same,
so only the alignment moved). Renames in the same pass: the cooking `pan`
takes the word and the chimpanzee genus is `genus-pan`; `pb` is
`lead-metal`. 2,929 listed categories.

**v5 (0.22.0, 2026-09-03): the planet.** One sense correction and one
concept, found by the second reading of the domain packs: `exoplanet ⊑
planet` was refused because core's `planet` was WordNet's *solar-system*
sense ("any of the nine large celestial bodies that revolve around the
sun", 09394007). It is now the generic body orbiting a star (09394646 —
what the word means; the edge `planet ⊑ celestial-body` is unchanged), and
the freed synset enters as **`major-planet ⊑ planet`**, WordNet's own second
lemma for it, placed by ruling (WordNet files both senses directly under
celestial body). The space pack's `planetary-body` collapses into `planet`,
and `inferior-`, `superior-`, `jovian-` and `outer-planet` hang from
`major-planet`. 2,930 listed categories. The same pass re-read every
single-source edge in the six domain packs that had had one reading
(medicine, ai, economics, computing, geography, space — 108 of 3,649
rejected, 3.0%; ontodag-core UPPER.md §9), so those seven pack modules
(physics included, for `outer-planet`) are **v2**.

The same weeks built **ten domain packs** in ontodag-core beside core —
physics, mathematics, chemistry, biology, medicine, ai, economics,
computing, geography, space, about 6,900 categories together — under the
policy of §7 there: hinges in core, contents in packs, everyday words never
taken by a pack. Since 0.21.0 they **ship in the wheel** (`odag pack geography`; each applies
core first, `ontodag.domain`), the reversible half of the PACKS.md Part II
decision — publishing them to Swarm later is the same stores. They fit: ontodag-core's
`tools/integrate.py` merges core and all ten into one store — 9,793
categories, the same root in every merge order, every cross-pack claim
resolving — with roots pinned in ontodag-core's UPPER.md §8.1.

`CORE_VERSION` bumps whenever the list changes; the list itself is
regenerated from ontodag-core's review files, never edited by hand.
`tests/test_packs.py` pins the pack's canonical root under both addressing
schemes, checks closure against the pack plus the prelude, a size window,
the motivating paths, that it carries no unit declarations, and that it
composes with the prelude idempotently. Adoption is a merge: idempotent,
order-free, previewable with `odag pack core --diff`.
