from ontodag.dag import DAG, OntoDAG, Item, OntoDAGVisualizer


def __getattr__(name):
    # OWL support needs owlready2; import it only when actually used so the
    # core data structure works without it.
    if name == "OWLOntology":
        from ontodag.owl import OWLOntology

        return OWLOntology
    # The Swarm adapter is optional persistence; keep plain `import ontodag`
    # free of it (tests/test_boundaries.py, B1).
    if name == "SwarmOntoDAG":
        from ontodag.swarm_adapter import SwarmOntoDAG

        return SwarmOntoDAG
    # Same for the on-demand reader (it needs no recordstore import itself,
    # but belongs with the persistence layer, not the core).
    if name == "LazyOntoDAG":
        from ontodag.lazy_reader import LazyOntoDAG

        return LazyOntoDAG
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
