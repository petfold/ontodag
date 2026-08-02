from ontodag.dag import DAG, OntoDAG, Item

# Version of the higher-layer contract this package implements
# (docs/CONTRACT.md — what agents and inference layers may assume).
# Bumped on any clause change; agreed at 0.1 on 2026-08-01.
CONTRACT_VERSION = "0.1"


def __getattr__(name):
    # Optional features, reached lazily so that `import ontodag` needs
    # nothing but the standard library (tests/test_boundaries.py, B1). Each
    # one that depends on a package outside the base install turns a missing
    # dependency into an error that names the extra to install, rather than
    # a ModuleNotFoundError naming a package the reader then has to map back
    # to a pip command.
    if name == "OWLOntology":
        try:
            from ontodag.owl import OWLOntology
        except ImportError as exc:
            raise ImportError(
                "OWL import/export needs the `owl` extra: "
                'pip install "ontodag[owl]"'
            ) from exc

        return OWLOntology
    # Rendering: an optional consumer of a DAG, never part of one. Its own
    # module since 2026-08-02, so the core carries no renderer.
    if name == "OntoDAGVisualizer":
        from ontodag.viz import OntoDAGVisualizer

        return OntoDAGVisualizer
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
