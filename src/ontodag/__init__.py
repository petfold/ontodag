from ontodag.dag import DAG, OntoDAG, Item, OntoDAGVisualizer

# Version of the higher-layer contract this package implements
# (docs/CONTRACT.md — what agents and inference layers may assume).
# Bumped on any clause change; agreed at 0.1 on 2026-08-01.
CONTRACT_VERSION = "0.1"


def __getattr__(name):
    # OWL support needs owlready2; import it only when actually used so the
    # core data structure works without it.
    if name == "OWLOntology":
        from ontodag.owl import OWLOntology

        return OWLOntology
    # Persistence is optional; keep plain `import ontodag` free of it
    # (tests/test_boundaries.py, B1). Eager and Lazy differ by *residency*
    # (whole store in RAM vs fetched as a query walks); both take any
    # duck-typed record store, so neither is tied to Swarm.
    if name == "EagerOntoDAG":
        from ontodag.eager import EagerOntoDAG

        return EagerOntoDAG
    # Same for the on-demand reader (it needs no recordstore import itself,
    # but belongs with the persistence layer, not the core).

    if name == "LazyOntoDAG":
        from ontodag.lazy import LazyOntoDAG

        return LazyOntoDAG
    # The partially-resident writer: LazyOntoDAG's residency model with
    # EagerOntoDAG's mutation semantics (ROADMAP "writing back from a
    # partially-loaded graph").
    if name == "SparseOntoDAG":
        from ontodag.lazy import SparseOntoDAG

        return SparseOntoDAG
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
