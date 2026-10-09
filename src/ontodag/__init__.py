from ontodag.dag import DAG, OntoDAG, Item

# Version of the higher-layer contract this package implements
# (docs/CONTRACT.md — what agents and inference layers may assume).
# Bumped on any clause change; agreed at 0.1 on 2026-08-01, amended to
# 0.2 on 2026-10-06 (what an arrow means; dimensions over nodes).
CONTRACT_VERSION = "0.5"


def open(spec=None, *, as_of=None):
    """Open a store the way `odag` does, as a `Store` (`ontodag.stores`).

    `spec` names the store: a file (`.od`, or `.owl`/`.omn` by extension),
    `rs:PATH` or `swarm:NAME`, made absolute like odag's `-f`. None opens
    the active store, found by the settings' one rule (flag > environment
    > config file > default; `ontodag.settings`). `as_of` reads a past
    version instead (any prefix of a root `odag history` shows), read-only.

    Nothing is read until the store is used: `store.dag` loads it (and is
    where a store that cannot be opened raises odag's ValueError),
    `store.view()` adds the configured overlays for answering,
    `store.save(message=None)` writes the DAG back.

        store = ontodag.open("rs:~/work/travel")
        store.dag.put("kyoto", ["japan"])
        store.save(message="kyoto")

    Named like the builtin on purpose (`gzip.open`, `shelve.open`): it is
    reached as `ontodag.open`, never imported bare."""
    from ontodag.settings import resolve_store
    from ontodag.stores import Store

    return Store(resolve_store(spec), as_of=as_of)


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
    # What `odag set` reads and writes, and the stores `open` returns:
    # standard library only, but reached on first use like the rest, so
    # `ontodag.settings` works after a bare `import ontodag`.
    if name in ("settings", "stores"):
        import importlib

        return importlib.import_module(f"ontodag.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
