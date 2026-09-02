# The `core` pack: a small upper ontology

Design record for `src/ontodag/core_ontology.py`, shipped as the pack
`core` (v1, 2026-09-02). This page says what the pack is for, how a node
earns its place, and what the pack deliberately cannot do. The list itself
is the module; `odag pack core --show` prints it.

## Taxonomy without teeth

OntoDAG states subsumption and nothing else, so this top ontology has
**branches and no fences**. It can say that every plane ticket is a
transport ticket is a ticket is a document; it cannot say that a
document is not a mammal, and nothing here will refuse a filing that
mixes them (the disjointness wall, `DATABASE_DIRECTION.md`; factbond is
its second consumer). Cyc's upper levels got most of their discipline
from partitions that turned wrong filings into contradictions. Ours will
have Cyc's taxonomy without Cyc's teeth: the discipline arrives as
convention, `merge --diff` and `pack --diff` preview, and the review
workflow on the agent surface, never as refusal.

What the pack *does* give is the thing a flat tag set cannot: paths.
Query `document` and the invoice, the email and the plane ticket are all
in the cone; query `human` and everything filed under `man`, `woman`,
`child` is there. An email filed under `email` and `man` (the sender's
category, spelled as a plain parent) is found by `email human`. That is
the whole mechanism, and the pack's only job is to make the common
paths exist before anyone has to build them.

## How a node earns its place

Every node here is inherited by the whole ecosystem and cannot be
retracted by merge (EVOLUTION.md §1: refinement converges, retraction
needs coordination). So admission is a one-way door, and the test is
**could we conceivably be wrong about it?**, never *would it be useful?*

- **Coarse-but-true beats fine-but-arguable.** `dog ⊑ mammal` is in.
  `pet` is out: it is a role, not a kind, and roles are the user's flat
  dimension heads (USER_GUIDE §5.12).
- **One reading where a word has two.** A paper letter is a physical
  object *and* information. The pack files `document` under
  `information` only, because that is the reading people file by, and
  says so. Likewise `medicine` is the field and `drug` the substance;
  `flight` is the event of flying, `airplane` the vehicle;
  `transport` is the event of moving people or goods, so the worked
  example's `transport` acquires `event` as a parent on merge and
  nothing else changes.
- **Coverage is not a goal.** The pack stops where being wrong would
  start to be survivable, which is where domain packs begin. That is
  why there is no `pet`, no `smartphone`, no `startup`, no `jazz`.
- **Names are identity.** A pack node called `car` becomes *your* `car`
  on merge. That is the convergence property doing its job, and also
  the collision hazard PACKS.md principle 4 describes: `pack --diff`
  shows the shared names before you adopt.

Sources were read for their decisions and none was imported: BFO and
DOLCE for the object / substance / event / information split, schema.org
for what "everyday size" looks like, Cyc for the care over individual vs.
collective and tangible vs. intangible. Wikidata's P279 top was not used
even as a quarry here (instance/subclass muddles); it remains the right
source for *derived domain* packs.

## The seven branches

| branch | what goes under it | why it is a branch |
|---|---|---|
| `physical-object` | natural objects, artifacts, organisms | bounded, located, has extent |
| `substance` | materials, food, drink, fuel, drugs | stuff by kind, not by piece |
| `agent` | persons, organizations, groups, software agents | can act and be held responsible |
| `event` | activities, transport, communication, transactions, natural events | happens; has a time extent |
| `information` | documents, images, video, audio, datasets, software | content that copies without loss |
| `place` | continents to streets, venues; also landforms and buildings by a second parent | a location one can be at |
| `field-of-study` | sciences, humanities, arts, engineering, medicine, law, business | what something is *about*, for filing by subject |

`human` has two parents, `mammal` and `person`: the species is also an
agent. `building`, `landform` and `body-of-water` are physical and also
places. `map` is an image and a document; `voice-message` is audio and a
message. Multi-parent nodes are the point of the structure, and the
reduction keeps them canonical.

## What it is not

- **Not roles.** `author`, `owner`, `sender`, `pet` are relations to a
  filler. Spell them as dimension heads or plain categories on the item
  that has them, per the flat-roles rule.
- **Not the math skeleton.** Number kinds and the registry reflection
  (`count-dimension ⊑ integer-valued-dimension`) are EVOLUTION.md §3's
  separate, better-founded first upper pack.
- **Not inference.** The pack knows *that* every mammal is a vertebrate,
  never *why*; nothing is derived except cone membership.
- **Not the prelude.** PACKS.md principle 3: the prelude holds only names
  the interpreter dereferences (the kind nodes). `core` is pack-tier by
  distribution while EVOLUTION.md argues prelude-grade governance for it,
  and both are true at once: adopt it with one command, and expect its
  versions to be rare and argued.

## Versioning and verification

`CORE_VERSION` bumps whenever the list changes. `tests/test_packs.py`
pins the pack's canonical root under both addressing schemes, so
adopting it into any `rs:` store reproduces one fingerprint and
publishing it to Swarm reproduces the other, and a silent change is
impossible. The same file checks closure (every parent is in the pack),
no duplicates, the size bound (under 200), the motivating paths, that it
carries no unit declarations, and that it composes with the prelude.

Adoption is a merge, so it is idempotent and order-free, previewable
with `odag pack core --diff`, and reversible only the way any addition
is: by `undo` locally, never by merge.
