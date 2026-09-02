"""The `core` pack: a small upper ontology, adopted by merge.

**Taxonomy without teeth — read this first.** OntoDAG states subsumption
and nothing else. It cannot say that two categories are disjoint, so this
top offers *branches* and never *fences*: filing a `spreadsheet` under
`mammal` is wrong, and nothing here refuses it (the disjointness wall,
`DATABASE_DIRECTION.md`). The discipline a top ontology usually gets from
partitions arrives here as convention, `merge --diff` preview and the
review workflow instead. What this pack does give is the thing a flat tag
set lacks: **an email from a man is an email from a human**, a **plane
ticket is a transport ticket is a ticket is a document**, and a query for
`document` finds both — because the path is there and a query is the
intersection of cones.

**Admission rule (EVOLUTION.md §3).** Every node here is a commitment the
whole ecosystem inherits and no one can retract by merge, so the test for
admission is *could we conceivably be wrong about it?* — not *would it be
useful?*. Coarse-but-true wins over fine-but-arguable: `dog ⊑ mammal` is
in, `pet` (a role, not a kind) is out; `document ⊑ information` is in,
`document ⊑ physical-object` (also true of a paper letter) is not, because
one reading had to be chosen and the informational one is the one people
file by. Coverage is deliberately NOT a goal: growth belongs below this
line, in domain packs, where being wrong is survivable. Sources were read
for their *decisions* (BFO/DOLCE for the physical/event/information split,
schema.org for the everyday size, Cyc for the individual/collective and
tangible/intangible care) and none was imported — Wikidata's P279 top is
a quarry for domain packs, not a skeleton.

**What it is not.** No roles (`author`, `owner`, `pet`): those are the
flat-roles pattern of USER_GUIDE §5.12, spelled as dimension heads by the
user who needs them. No math skeleton (EVOLUTION.md §3 — a separate,
better-founded first pack). No disjointness, no axioms, no inference: it
will know *that* every mammal is a vertebrate, never *why*.

**Names.** Lowercase, hyphenated, singular, English. Names are identity
in OntoDAG (PACKS.md principle 4), so a pack node named `train` would
*become* your `train` on merge — that is the point (convergence) and the
hazard (collision). The names below were chosen to be the ones a person
would type; where a common word is a role or is ambiguous (`bus` the
vehicle vs. `bus` the service, `medicine` the field vs. the drug) the
pack either avoids it or picks the reading and says so in a comment.

Bump `CORE_VERSION` whenever `CORE` changes: `tests/test_packs.py` pins
the pack's canonical root per version, so a change is visible, never
silent.
"""

CORE_VERSION = 1

# (name, parents). Top-level branches have no parents (they sit under `*`).
# Order is irrelevant to the result (I3); it is kept readable by branch.
CORE = (
    # ---- the top-level branches -------------------------------------------
    ("physical-object", ()),      # bounded, located, has extent
    ("substance", ()),            # stuff: matter by kind, not by piece
    ("agent", ()),                # can act and be held responsible
    ("event", ()),                # happens; has a time extent
    ("information", ()),          # content: copyable without loss
    ("place", ()),                # a location one can be at
    ("field-of-study", ()),       # a subject matter, for filing "about"

    # ---- physical objects --------------------------------------------------
    ("natural-object", ("physical-object",)),
    ("celestial-body", ("natural-object",)),
    ("planet", ("celestial-body",)),
    ("landform", ("natural-object", "place")),
    ("mountain", ("landform",)),
    ("island", ("landform",)),
    ("body-of-water", ("natural-object", "place")),
    ("river", ("body-of-water",)),
    ("lake", ("body-of-water",)),
    ("sea", ("body-of-water",)),

    ("artifact", ("physical-object",)),      # made by an agent
    ("tool", ("artifact",)),
    ("device", ("artifact",)),
    ("computer", ("device",)),
    ("phone", ("device",)),
    ("camera", ("device",)),
    ("machine", ("artifact",)),
    ("vehicle", ("machine",)),
    ("land-vehicle", ("vehicle",)),
    ("car", ("land-vehicle",)),
    ("truck", ("land-vehicle",)),
    ("bicycle", ("land-vehicle",)),
    ("watercraft", ("vehicle",)),
    ("ship", ("watercraft",)),
    ("boat", ("watercraft",)),
    ("aircraft", ("vehicle",)),
    ("airplane", ("aircraft",)),
    ("helicopter", ("aircraft",)),
    ("spacecraft", ("vehicle",)),
    ("building", ("artifact", "place")),
    ("house", ("building",)),
    ("furniture", ("artifact",)),
    ("clothing", ("artifact",)),
    ("container", ("artifact",)),
    ("musical-instrument", ("artifact",)),

    # ---- organisms (physical objects that are alive) -----------------------
    ("organism", ("physical-object",)),
    ("plant", ("organism",)),
    ("tree", ("plant",)),
    ("flower", ("plant",)),
    ("fungus", ("organism",)),
    ("mushroom", ("fungus",)),
    ("microorganism", ("organism",)),
    ("bacterium", ("microorganism",)),
    ("animal", ("organism",)),
    ("vertebrate", ("animal",)),
    ("mammal", ("vertebrate",)),
    ("human", ("mammal", "person")),        # the species is also a person
    ("man", ("human",)),
    ("woman", ("human",)),
    ("child", ("human",)),
    ("adult", ("human",)),
    ("dog", ("mammal",)),
    ("cat", ("mammal",)),
    ("horse", ("mammal",)),
    ("cattle", ("mammal",)),
    ("whale", ("mammal",)),
    ("bird", ("vertebrate",)),
    ("fish", ("vertebrate",)),
    ("reptile", ("vertebrate",)),
    ("amphibian", ("vertebrate",)),
    ("invertebrate", ("animal",)),
    ("insect", ("invertebrate",)),
    ("bee", ("insect",)),
    ("arachnid", ("invertebrate",)),
    ("spider", ("arachnid",)),
    ("mollusc", ("invertebrate",)),

    # ---- substances --------------------------------------------------------
    ("material", ("substance",)),
    ("metal", ("material",)),
    ("food", ("substance",)),
    ("fruit", ("food",)),
    ("vegetable", ("food",)),
    ("meat", ("food",)),
    ("grain", ("food",)),
    ("dairy-product", ("food",)),
    ("drink", ("substance",)),
    ("water", ("drink",)),
    ("fuel", ("substance",)),
    ("drug", ("substance",)),                # the substance; the field is `medicine`

    # ---- agents ------------------------------------------------------------
    ("person", ("agent",)),
    ("organization", ("agent",)),
    ("company", ("organization",)),
    ("government", ("organization",)),
    ("nonprofit", ("organization",)),
    ("school", ("organization",)),
    ("university", ("school",)),
    ("software-agent", ("agent",)),
    ("group", ("agent",)),                  # a collective that acts as one
    ("team", ("group",)),
    ("family", ("group",)),
    ("community", ("group",)),

    # ---- events ------------------------------------------------------------
    ("activity", ("event",)),
    ("work", ("activity",)),
    ("sport", ("activity",)),
    ("meeting", ("activity",)),
    ("journey", ("activity",)),
    ("transport", ("event",)),               # moving people or goods
    ("flight", ("transport",)),
    ("communication", ("event",)),
    ("conversation", ("communication",)),
    ("phone-call", ("communication",)),
    ("transaction", ("event",)),
    ("payment", ("transaction",)),
    ("purchase", ("transaction",)),
    ("sale", ("transaction",)),
    ("performance", ("event",)),
    ("concert", ("performance",)),
    ("natural-event", ("event",)),
    ("earthquake", ("natural-event",)),
    ("storm", ("natural-event",)),
    ("flood", ("natural-event",)),
    ("birth", ("event",)),
    ("death", ("event",)),

    # ---- information -------------------------------------------------------
    ("document", ("information",)),
    ("message", ("document",)),
    ("email", ("message",)),
    ("letter", ("message",)),
    ("text-message", ("message",)),
    ("chat-message", ("message",)),
    ("report", ("document",)),
    ("article", ("document",)),
    ("book", ("document",)),
    ("note", ("document",)),
    ("manual", ("document",)),
    ("form", ("document",)),
    ("certificate", ("document",)),
    ("legal-document", ("document",)),
    ("contract", ("legal-document",)),
    ("financial-document", ("document",)),
    ("invoice", ("financial-document",)),
    ("receipt", ("financial-document",)),
    ("ticket", ("document",)),
    ("transport-ticket", ("ticket",)),
    ("plane-ticket", ("transport-ticket",)),
    ("train-ticket", ("transport-ticket",)),
    ("bus-ticket", ("transport-ticket",)),
    ("event-ticket", ("ticket",)),
    ("spreadsheet", ("document",)),
    ("presentation", ("document",)),
    ("web-page", ("document",)),
    ("image", ("information",)),
    ("photograph", ("image",)),
    ("drawing", ("image",)),
    ("diagram", ("image",)),
    ("map", ("image", "document")),
    ("video", ("information",)),
    ("film", ("video",)),
    ("audio", ("information",)),
    ("music-recording", ("audio",)),
    ("podcast", ("audio",)),
    ("voice-message", ("audio", "message")),
    ("dataset", ("information",)),
    ("software", ("information",)),
    ("application", ("software",)),
    ("software-library", ("software",)),
    ("operating-system", ("software",)),

    # ---- places ------------------------------------------------------------
    ("continent", ("place",)),
    ("country", ("place",)),
    ("region", ("place",)),
    ("settlement", ("place",)),
    ("city", ("settlement",)),
    ("town", ("settlement",)),
    ("village", ("settlement",)),
    ("street", ("place",)),
    ("venue", ("place",)),

    # ---- fields of study (for filing what something is *about*) ------------
    ("science", ("field-of-study",)),
    ("natural-science", ("science",)),
    ("physics", ("natural-science",)),
    ("chemistry", ("natural-science",)),
    ("biology", ("natural-science",)),
    ("astronomy", ("natural-science",)),
    ("earth-science", ("natural-science",)),
    ("social-science", ("science",)),
    ("economics", ("social-science",)),
    ("psychology", ("social-science",)),
    ("sociology", ("social-science",)),
    ("formal-science", ("science",)),
    ("mathematics", ("formal-science",)),
    ("computer-science", ("formal-science",)),
    ("logic", ("formal-science",)),
    ("humanities", ("field-of-study",)),
    ("history", ("humanities",)),
    ("philosophy", ("humanities",)),
    ("linguistics", ("humanities",)),
    ("literature", ("humanities",)),
    ("art", ("field-of-study",)),
    ("music", ("art",)),
    ("engineering", ("field-of-study",)),
    ("medicine", ("field-of-study",)),       # the field; the substance is `drug`
    ("law", ("field-of-study",)),
    ("business", ("field-of-study",)),
)
