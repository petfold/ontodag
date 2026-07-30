"""EagerOntoDAG — an OntoDAG persisted through a record store, loaded whole.

Named for its *residency*, not its backend: it hydrates the entire store into
RAM on construction. Its sibling `LazyOntoDAG` fetches records as a query
walks them. Neither knows anything about Swarm — the store is duck-typed, so
memory, a Bee node, or anything else with the same five methods works
identically. Swarm is chosen one layer down, by whoever builds the record
store (`recordstore.swarm_store(...)` is the one call that does it).

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

The store is duck-typed (``get``/``put``/``delete``/``keys``/``commit``,
plus an optional ``items()`` used for batched hydration when present),
matching ``recordstore.RecordStore``; this module deliberately imports
nothing from `recordstore`, keeping the core↔recordstore dependency
one-directional even here (see tests/test_boundaries.py).
"""

from ontodag.dag import Item, OntoDAG, _name_of


class EagerOntoDAG(OntoDAG):
    def __init__(self, record_store):
        super().__init__()
        self.store = record_store
        self._synced = {}          # key -> record as of the last commit/hydrate
        self._payloads = {}        # name -> swarm ref
        # node meta lives on Item.metadata (records' "meta" field)
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
            # copied: _synced keeps these records, so aliasing the live dict
            # would make later in-place metadata edits invisible to the diff
            "meta": dict(node.metadata),
        }

    def _hydrate(self):
        records = dict(self._all_records())
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
                node.metadata = dict(record["meta"])
        self._synced = records

    def _all_records(self):
        """Every ``(key, record)`` in the store, batched where the store allows.

        A store with ``items()`` (recordstore >= 0.5) fetches value blobs
        concurrently in bounded windows, so a cold hydrate costs a few sweeps
        instead of one network round trip per node. Stores without it — the
        duck-typed minimum this module documents — fall back to serial gets.
        """
        items = getattr(self.store, "items", None)
        if callable(items):
            return items()
        return ((name, self.store.get(name)) for name in self.store.keys())

    # ------------------------------------------------------------- mutations

    def put(self, subcategory, super_categories, optimized=False,
            payload=None, meta=None):
        super().put(subcategory, super_categories, optimized=optimized)
        # Plain strings accepted, like OntoDAG; parametric sugar stores
        # under the canonical name (weight(3kg) -> weight(3000000mg)).
        name = self._canonical_name(_name_of(subcategory))
        if payload is not None:
            self._payloads[name] = payload
        if meta is not None:
            self.nodes[name].metadata = dict(meta)

    def remove(self, node_to_remove):
        name = self._canonical_name(_name_of(node_to_remove))
        super().remove(node_to_remove)
        self._payloads.pop(name, None)

    def merge(self, other_dag):
        super().merge(other_dag)  # carries Item.metadata (ours win per key)
        # Carry payloads from the other side; ours win on conflict.
        if isinstance(other_dag, EagerOntoDAG):
            for name, payload in other_dag._payloads.items():
                self._payloads.setdefault(name, payload)

    def sync(self, other_root, bytes_store=None) -> str:
        """Fold a peer's published state into this graph, commit the union,
        return the new root — the multi-writer merge *rule* of
        SWARM_DESIGN.md §5.

        Reconciliation is deliberately graph-level, not per-record:
        transitive reduction and descendant counts are properties of the
        whole graph, so no per-key resolver can uphold them. Divergent
        versions are hydrated and folded through ``OntoDAG.merge`` (the I7
        semantics — commutative, idempotent, union of assertions re-reduced
        against the combined order, parametric dimension terms included),
        then recommitted; the canonical trie turns convergence into a string
        comparison — two writers syncing each other's roots land on the
        byte-identical root.

        Semantics that follow from union (both documented walls, not bugs):
        a removal does not survive a peer's concurrent re-add (the grow-only
        stance of DATABASE_DIRECTION.md's deletion wall), and a peer may
        legitimately hold assertions that this side's put-time lints would
        have refused together (e.g. an item under two disjoint parametric
        terms — a provably empty concept, visible, queryable as empty).

        Cross-process pointer racing is the deployment layer's business
        (feed `compare_and_set` loops, loopmarket's aggregator); this method
        is the fold they call.
        """
        self.merge_published(other_root, bytes_store)
        return self.commit()

    def merge_published(self, root, bytes_store=None) -> bool:
        """Merge a published version identified by its `root`, and say whether
        anything came of it.

        Roots are canonical (same knowledge ⇒ same root), which turns "do I
        already have this?" into a string comparison: if `root` equals ours,
        that version's content is exactly our committed content, so the union
        adds nothing and no records are read at all. Otherwise the other root
        is opened over the same blobs and merged normally.

        Note the short-circuit stays correct even when *we* have uncommitted
        changes: our current graph is then a superset of our committed content,
        which the equal root proves equals theirs — so the union still adds
        nothing.

        The same reasoning does **not** license short-circuiting `merge()` on a
        live `EagerOntoDAG` by comparing `store.root`: the other object may hold
        uncommitted changes its root does not reflect, and skipping would
        silently drop them.
        """
        from recordstore import RecordStore

        if root is not None and root == self.store.root:
            return False                      # already have exactly this
        other = EagerOntoDAG(
            RecordStore.at(root, bytes_store or self.store.blobs))
        self.merge(other)
        return True
