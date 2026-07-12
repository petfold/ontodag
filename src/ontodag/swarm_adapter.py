"""SwarmOntoDAG — an OntoDAG persisted through a record store.

Implements the design in docs/SWARM_DESIGN.md:

- One record per node, keyed by the node name (§3): ``{"up": [...],
  "down": [...], "count": int, "payload": ref-or-None, "meta": {...}}``
  with `up`/`down` sorted so the encoding is deterministic.
- Hydrate the whole graph into memory once, operate in RAM, and push
  changes back through staged puts + ``commit()`` (§6). Mutation semantics
  (acyclicity, transitive reduction, counts) are entirely inherited from
  `OntoDAG` — this class only adds persistence.
- ``commit()`` diffs the current graph against the last-synced records and
  stages only what changed, so the store's structural sharing keeps small
  changes small.

The store is duck-typed (``get``/``put``/``delete``/``keys``/``commit``),
matching ``recordstore.RecordStore``; this module deliberately imports
nothing from `recordstore`, keeping the core↔recordstore dependency
one-directional even here (see tests/test_boundaries.py).
"""

from ontodag.dag import Item, OntoDAG


class SwarmOntoDAG(OntoDAG):
    def __init__(self, record_store):
        super().__init__()
        self.store = record_store
        self._synced = {}          # key -> record as of the last commit/hydrate
        self._payloads = {}        # name -> swarm ref
        self._metas = {}           # name -> dict
        self._hydrate()

    # ------------------------------------------------------------------ sync

    def commit(self):
        """Stage every changed node record, commit, return the new root."""
        current = {name: self._record_for(node)
                   for name, node in self.nodes.items()}
        for name, record in current.items():
            if self._synced.get(name) != record:
                self.store.put(name, record)
        for name in self._synced:
            if name not in current:
                self.store.delete(name)
        root = self.store.commit()
        self._synced = current
        return root

    def _record_for(self, node):
        return {
            "up": sorted(parent.name for parent in node.parents
                         if self.nodes.get(parent.name) is parent),
            "down": sorted(child.name for child in node.neighbors),
            "count": node.descendant_count,
            "payload": self._payloads.get(node.name),
            "meta": self._metas.get(node.name, {}),
        }

    def _hydrate(self):
        records = {name: self.store.get(name) for name in self.store.keys()}
        if not records:
            return
        # Records are the canonical, already-reduced state, so the graph is
        # reconstructed directly instead of replayed through put().
        for name in records:
            if name != self.root.name:
                self.add_node(Item(name))
        for name, record in records.items():
            node = self.nodes[name]
            for child_name in record["down"]:
                node.neighbors.add(self.nodes[child_name])
            node.descendant_count = record["count"]
            if record.get("payload") is not None:
                self._payloads[name] = record["payload"]
            if record.get("meta"):
                self._metas[name] = record["meta"]
        self._synced = records

    # ------------------------------------------------------------- mutations

    def put(self, subcategory, super_categories, optimized=False,
            payload=None, meta=None):
        super().put(subcategory, super_categories, optimized=optimized)
        name = subcategory.name
        if payload is not None:
            self._payloads[name] = payload
        if meta is not None:
            self._metas[name] = meta

    def remove(self, node_to_remove):
        super().remove(node_to_remove)
        self._payloads.pop(node_to_remove.name, None)
        self._metas.pop(node_to_remove.name, None)

    def merge(self, other_dag):
        super().merge(other_dag)
        # Carry node extras from the other side; ours win on conflict.
        if isinstance(other_dag, SwarmOntoDAG):
            for name, payload in other_dag._payloads.items():
                self._payloads.setdefault(name, payload)
            for name, meta in other_dag._metas.items():
                self._metas.setdefault(name, meta)
