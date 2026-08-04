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
        # The root of this dag's own hydrate/commit lineage — what its
        # in-memory state is a mutation of. `store.root` is not a substitute:
        # a transient-window deployment rebinds `store` to a fresh handle
        # (possibly already at a peer's moved head), and a shared pointer can
        # move under a live handle, so only the dag itself can say which
        # root it last synced with.
        self.base_root = getattr(record_store, "root", None)
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
        self.base_root = root
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
        # under the canonical name (weight(3000g) -> weight(3kg)).
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
        versions are folded with the I7 semantics — commutative,
        idempotent, union of assertions re-reduced against the combined
        order, parametric dimension terms included — reading only the
        records that actually diverged (``merge_delta``), then
        recommitted; the canonical trie turns convergence into a string
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
        already have this?" into a string comparison: if `root` equals ours
        — `base_root`, the root of our own hydrate/commit lineage — that
        version's content is exactly our committed content, so the union
        adds nothing and no records are read at all. Otherwise the other root
        is opened over the same blobs and merged normally. (`store.root`
        would be the wrong side of the comparison: under transient windows
        the handle is rebound to a fresh window whose root is the *peer's*
        moved head — equality there means "this is the thing to merge",
        the opposite of "already have it".)

        Note the short-circuit stays correct even when *we* have uncommitted
        changes: our current graph is then a superset of our committed content,
        which the equal root proves equals theirs — so the union still adds
        nothing.

        The same reasoning does **not** license short-circuiting `merge()` on a
        live `EagerOntoDAG` by comparing `store.root`: the other object may hold
        uncommitted changes its root does not reflect, and skipping would
        silently drop them.

        The fold itself is delta-driven (`merge_delta`): only the records
        that actually moved between our lineage and `root` are read, so
        folding a peer costs the divergence, never the store.
        """
        if root is not None and root == self.base_root:
            return False                      # already have exactly this
        return self.merge_delta(root, bytes_store)

    def merge_delta(self, other_root, bytes_store=None) -> bool:
        """Fold the state at `other_root` in by walking only the DIVERGENCE.

        Semantically the same union as hydrating the peer and calling
        ``merge()`` — fresh ``Item``s, ours-win metadata and payloads,
        edges replayed through ``add_edge`` so reduction (combined order)
        and counts are re-derived, never reconciled (SWARM_DESIGN.md §5's
        count rule) — but driven by ``RecordStore.diff`` between our own
        lineage (``base_root``) and the peer's root, so the cost is
        O(divergence × ancestor cones) instead of O(store). Replay order
        is irrelevant because ``add_edge`` maintains the complete
        redundancy rectangle (the 2026-08-04 reduction fix): the result
        is the unique reduction of the asserted union either way.

        The one diff walk yields two products:

        - **The fold.** Keys whose record moved between base and peer are
          folded from the peer's side; peer-ABSENT keys fold nothing (the
          union keeps ours — the grow-only stance). Locally *dirty* keys
          (including local uncommitted removals) are re-unioned from
          ``_synced`` — their peer-side record provably equals that
          baseline whenever they are absent from the diff, so no fetch.
        - **The rebase.** When this dag's store window is already AT
          ``other_root`` (the transient-window save flow rebinds the
          store to a fresh window at the moved head before syncing),
          ``_synced`` is rewritten to describe that head, restoring
          ``commit()``'s invariant that the baseline matches the root
          being committed onto. Without it, a record the peer deleted
          and we still hold stages nothing — the deletion silently wins
          in the store while memory keeps the node, and store and memory
          diverge. With it, commit stages exactly union-vs-head.

        Unlike ``merge()``, no trailing duplicate-root-edge sweep runs:
        after the reduction fix the sweep is a no-op on any store built
        through ``add_edge``, and folding must not pay a whole-graph walk
        to clean legacy hand-forged shapes (``ontodag.migrate`` is the
        tool for those).
        """
        from ontodag._extras import require
        rs = require("recordstore", "store", "sync()")

        blobs = bytes_store or self.store.blobs
        snapshot = rs.RecordStore.at(self.base_root, blobs)
        diff = list(snapshot.diff(other_root))
        diff_keys = {key for key, _, _ in diff}

        touched = {}                     # name -> the peer-side record
        for key, _mine, theirs in diff:
            if theirs is not rs.ABSENT:
                touched[key] = theirs
        for key, record in self._synced.items():
            if key in diff_keys:
                continue
            node = self.nodes.get(key)
            if node is None or self._record_for(node) != record:
                touched[key] = record    # peer's copy equals our baseline

        # Pass 1: nodes, ours-win metadata and payloads (merge()'s policy).
        for key in sorted(touched):
            if key == self.root.name:
                continue                 # the root always exists; up is []
            record = touched[key]
            node = self.nodes.get(key)
            if node is None:
                self.add_node(Item(key, metadata=record.get("meta") or {}))
            else:
                for meta_key, value in (record.get("meta") or {}).items():
                    node.metadata.setdefault(meta_key, value)
            if record.get("payload") is not None:
                self._payloads.setdefault(key, record["payload"])
        # Pass 2: replay the peer's asserted edges. Every parent a peer
        # record names exists by now: an unchanged-in-both parent is
        # already ours, a changed or peer-new one is in the diff, and a
        # locally-removed one is dirty — all land in pass 1.
        for key in sorted(touched):
            if key == self.root.name:
                continue
            node = self.nodes[key]
            for parent_name in touched[key]["up"]:
                parent = self.nodes.get(parent_name)
                if parent is not None:
                    self.add_edge(parent, node)

        if getattr(self.store, "root", None) == other_root:
            for key, _mine, theirs in diff:
                if theirs is rs.ABSENT:
                    self._synced.pop(key, None)
                else:
                    self._synced[key] = theirs
        return bool(touched)
