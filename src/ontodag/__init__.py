from ontodag.dag import DAG, OntoDAG, Item, OntoDAGVisualizer


def __getattr__(name):
    # OWL support needs owlready2; import it only when actually used so the
    # core data structure works without it.
    if name == "OWLOntology":
        from ontodag.owl import OWLOntology

        return OWLOntology
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
