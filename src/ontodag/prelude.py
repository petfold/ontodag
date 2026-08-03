"""The standard prelude: common dimension declarations, adopted by merge.

The declaration-ceremony answer (SURFACE_LAYER.md §9.2, position recorded
2026-08-01): a fresh store shouldn't need three `put`s before the first
typed value works, but baking declarations into every new store would
change the canonical root of "empty" — adoption must be *explicit,
versioned, and visible in the fingerprint*. So the prelude is an ordinary
small ontology that you **merge in** (`odag prelude`, or
`dag.merge(prelude_dag())`): merge is idempotent and canonical, so
everyone who adopts the same prelude version contributes the identical
subgraph and converges on it — the merge-a-well-known-root story, with the
file shipped in the package and the prelude's own canonical root pinned by
a golden test (`tests/test_prelude.py`), so "prelude v1" *is* a specific
fingerprint. Publishing it as a Swarm store others sync is the same move
one deployment step later.

Contents are deliberately minimal and uncontroversial: the four kind nodes
the registry recognizes, and six everyday dimension heads in their obvious
kinds. Anything an application might dispute (domain vocabularies, upper
ontologies) is exactly what should ship as *separate* published preludes,
not here.
"""

from ontodag.dag import OntoDAG

# Bump when DECLARATIONS change; the golden-root test pins each version's
# canonical fingerprint, so a bump is visible, never silent.
# v2 (2026-08-01, UNITS.md D7): heads for the everyday families the full
# unit table (registry v3) brought in.
# v3 (2026-08-03, registry 4.1 / EVOLUTION.md §3): the count kind and the
# `count` head — whole numbers >= 1 of discrete things; count(0) refuses
# (an absence claim), fractions refuse (continuous stuff has dimensional
# heads). The kind can later gain an `integer-valued-dimension` parent
# additively when the math reflection lands (kind resolution stops at
# kind nodes, so structure above them is invisible to it).
PRELUDE_VERSION = 3

DECLARATIONS = (
    # the kind registry (names dimensions.py recognizes)
    ("dimension", ()),
    ("linear-dimension", ("dimension",)),
    ("calendar-dimension", ("dimension",)),
    ("prefix-dimension", ("dimension",)),
    ("dominance-dimension", ("dimension",)),
    ("count-dimension", ("dimension",)),
    # everyday heads, one per family where that is the obvious reading
    ("weight", ("linear-dimension",)),      # mass, anchored at kg
    ("length", ("linear-dimension",)),      # anchored at m
    ("duration", ("linear-dimension",)),    # anchored at s
    ("area", ("linear-dimension",)),        # anchored at m2
    ("volume", ("linear-dimension",)),      # anchored at m3
    ("speed", ("linear-dimension",)),       # anchored at mps
    ("pressure", ("linear-dimension",)),    # anchored at Pa; psi welcome
    ("temperature", ("linear-dimension",)), # kelvin-only (UNITS.md §2)
    ("energy", ("linear-dimension",)),      # anchored at J
    ("count", ("count-dimension",)),        # whole numbers of things, >= 1
    ("time", ("calendar-dimension",)),      # 2026 means the year
    ("geo", ("prefix-dimension",)),         # geohash-style cells
    ("size", ("dominance-dimension",)),     # does-it-fit tuples
)


def prelude_dag() -> OntoDAG:
    """The prelude as a fresh OntoDAG, ready to merge into any store."""
    dag = OntoDAG()
    for name, parents in DECLARATIONS:
        dag.put(name, list(parents))
    return dag


def apply(dag) -> None:
    """Merge the prelude into `dag` (any OntoDAG). Idempotent: applying it
    twice, or over a store that already declared some of it, adds only
    what is missing — merge semantics (I7)."""
    dag.merge(prelude_dag())
