from contextlib import contextmanager


class _EdgeSet(set):
    """A set of child Items that keeps each child's `parents` set in sync.

    Edges are object references in both directions (`neighbors` down,
    `parents` up). Several call sites — copy routines, tests building deep
    graphs — mutate `item.neighbors` directly rather than going through
    DAG.add_edge, so the reverse adjacency is maintained here in the
    container instead of in DAG methods.
    """

    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    def add(self, item):
        super().add(item)
        item.parents.add(self._owner)

    def remove(self, item):
        super().remove(item)
        item.parents.discard(self._owner)

    def discard(self, item):
        if item in self:
            super().discard(item)
            item.parents.discard(self._owner)

    def update(self, *iterables):
        for iterable in iterables:
            for item in iterable:
                self.add(item)

    def clear(self):
        for item in list(self):
            self.remove(item)

    def pop(self):
        item = super().pop()
        item.parents.discard(self._owner)
        return item


# --- experiment/delta-counts instrumentation ----------------------------
# Counts node expansions (one pop = one record fetch in a lazy remote
# setting) so the two count-maintenance algorithms can be compared.
# EXPERIMENT BRANCH ONLY — not for merge as-is.
STATS = {"descendants": 0, "affected": 0, "reachable": 0, "delta": 0}


class Item:
    def __init__(self, name, metadata=None):
        self.name = name
        self.parents = set()
        self.neighbors = _EdgeSet(self)
        self.descendant_count = 0
        # Non-structural annotations (e.g. a display label, an object
        # marker). Never identity: equality and hashing stay name-only.
        self.metadata = dict(metadata) if metadata else {}

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return f"Item({self.name}, [{', '.join(neighbor.name for neighbor in self.neighbors)}])"

    def to_dict(self):
        out = {
            "name": self.name,
            "neighbors": [neighbor.name for neighbor in self.neighbors],
            "descendant_count": self.descendant_count
        }
        if self.metadata:
            out["metadata"] = self.metadata
        return out


def _name_of(node_or_name):
    """Identity at the public boundary is the name: accept a plain string or
    anything with a `.name` (an Item), and return the name string."""
    return node_or_name if isinstance(node_or_name, str) else node_or_name.name


class DAG:
    def __init__(self, nodes=None):
        self.nodes = {}
        self._deferred_dirty = None  # a set while inside _batched_count_updates
        if nodes:
            for node in nodes:
                self.add_node(node)

    def add_node(self, node):
        """Add a node (Item) to the graph."""
        self.nodes[node.name] = node

    def add_edge(self, from_node, to_node):
        """Add a directed edge between two nodes."""
        if from_node.name not in self.nodes or to_node.name not in self.nodes:
            raise ValueError("Both nodes must exist in the graph.")

        if from_node == to_node:
            return
        if to_node in from_node.neighbors:
            return
        if self._is_reachable(to_node, from_node):
            raise ValueError(
                f"Edge {from_node.name} -> {to_node.name} would create a cycle."
            )

        from_node.neighbors.add(to_node)

        self._update_descendant_counts(from_node)

    def _is_reachable(self, start, target):
        """True if `target` is strictly reachable from `start` (iterative, early exit)."""
        seen = set()
        stack = [start]
        while stack:
            STATS["reachable"] += 1
            for neighbor in stack.pop().neighbors:
                if neighbor == target:
                    return True
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        return False

    def remove_edge(self, from_node, to_node):
        # Verify nodes exist
        if from_node.name not in self.nodes or to_node.name not in self.nodes:
            raise ValueError("Both nodes must exist in the graph.")

        # Remove child from parent's neighbors
        if to_node not in from_node.neighbors:
            raise ValueError("Edge does not exist.")
        from_node.neighbors.remove(to_node)

        self._update_descendant_counts(from_node)

    def _update_descendant_counts(self, parent):
        if self._deferred_dirty is not None:
            # Inside a batched operation: record the seed, refresh at the end.
            self._deferred_dirty.add(parent)
            return
        affected = set()
        self._get_affected_nodes(parent, affected)
        for node in affected:
            node.descendant_count = len(self.get_descendants(node))

    @contextmanager
    def _batched_count_updates(self):
        """Defer descendant-count refreshes until the enclosing operation ends.

        A multi-edge operation (put with several supers, remove's
        contraction, merge) otherwise recomputes counts once per edge.
        Re-entrant: only the outermost context flushes.
        """
        if self._deferred_dirty is not None:
            yield
            return
        self._deferred_dirty = set()
        try:
            yield
        finally:
            dirty, self._deferred_dirty = self._deferred_dirty, None
            affected = set()
            for seed in dirty:
                self._get_affected_nodes(seed, affected)
            for node in affected:
                node.descendant_count = len(self.get_descendants(node))

    def _get_affected_nodes(self, node, affected):
        """Get node and all its ancestors that need count updates"""
        frontier = [node]
        while frontier:
            current = frontier.pop()
            STATS["affected"] += 1
            if current in affected:
                continue
            affected.add(current)
            for parent in current.parents:
                # Only follow parents that belong to this DAG instance.
                if self.nodes.get(parent.name) is parent:
                    frontier.append(parent)

    def get_descendants(self, node, visited=None):
        # Identity at the public boundary is the name (a plain string or an
        # Item): traverse this instance's node, not the caller's object,
        # whose neighbors may be empty (e.g. a fresh Item used to query a
        # rehydrated DAG). An unknown name has no descendants.
        if isinstance(node, str):
            node = self.nodes.get(node)
            if node is None:
                return set()
        else:
            node = self.nodes.get(node.name, node)
        if visited is None:
            visited = set()
        if node in visited:
            return set()
        visited.add(node)
        descendants = set()  # Descendants of the current node
        frontier = [node]
        while frontier:
            STATS["descendants"] += 1
            for neighbor in frontier.pop().neighbors:
                descendants.add(neighbor)
                if neighbor not in visited:
                    visited.add(neighbor)
                    frontier.append(neighbor)
        return descendants

    def _has_ancestors(self, node, targets):
        """True if every Item in `targets` is a strict ancestor of `node`.

        A single upward walk over `parents`, early-exiting as soon as every
        target has been seen. Cost is bounded by `node`'s ancestor cone —
        shallow in typical category graphs — and never by the size of the
        graph or of any descendant cone. That bound is what makes this safe
        to call from the query planner (see `OntoDAG.get`): checking "is A an
        ancestor of X" downward from A can walk most of the graph when A is
        near the root, while checking it upward from X cannot.
        """
        missing = set(targets)
        seen = set()
        stack = [node]
        while stack and missing:
            for parent in stack.pop().parents:
                # Only follow parents that belong to this DAG instance.
                if self.nodes.get(parent.name) is not parent:
                    continue
                missing.discard(parent)
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        return not missing

    def get_ancestors(self, node, ignore=()):
        name = _name_of(node)  # a plain string is accepted too
        if name not in self.nodes:
            raise ValueError(f"Node {name} does not exist in the graph.")
        node = self.nodes[name]  # traverse our node, not the caller's

        ancestors = set()
        frontier = [node]
        while frontier:
            current = frontier.pop()
            for parent in current.parents:
                if parent in ancestors or parent in ignore:
                    continue
                # Only follow parents that belong to this DAG instance.
                if self.nodes.get(parent.name) is parent:
                    ancestors.add(parent)
                    frontier.append(parent)
        return ancestors

    def intersection_dag(self, other_dag):
        intersecting_dag = OntoDAG()

        # Add fresh copies of nodes that exist in both DAGs — never the
        # source Item objects themselves, so mutating the result cannot
        # write through to either source (I4).
        mapping = {}
        for node in self.nodes.values():
            if node.name == intersecting_dag.root.name:
                continue
            if node.name in other_dag.nodes:
                copy_item = Item(node.name)
                mapping[node.name] = copy_item
                intersecting_dag.add_node(copy_item)

        for root_subcategory in other_dag.root.neighbors:
            if root_subcategory.name in self.nodes:
                intersecting_dag.root.neighbors.add(mapping[root_subcategory.name])

        return intersecting_dag

    def topological_sort(self):
        # Iterative post-order DFS (I6: no recursion, deep graphs would hit
        # the Python recursion limit).
        visited = set()
        stack = []
        for start in self.nodes.values():
            if start in visited:
                continue
            visited.add(start)
            path = [(start, iter(start.neighbors))]
            while path:
                node, neighbors = path[-1]
                for neighbor in neighbors:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        path.append((neighbor, iter(neighbor.neighbors)))
                        break
                else:
                    stack.append(node)
                    path.pop()
        # Nodes in topological order, with the root first
        return stack[::-1]


class OntoDAG(DAG):
    def __init__(self):
        super().__init__()
        self.root = Item("*")
        self.nodes[self.root.name] = self.root

    def add_edge(self, from_node, to_node):
        """Add a directed edge between two nodes and remove unneeded edges from ancestors."""
        if from_node == to_node or to_node in from_node.neighbors:
            return
        # Skip the edge entirely if to_node is already reachable — adding it
        # would violate transitive reduction (and made results depend on the
        # order of super-categories in put).
        if self._is_reachable(from_node, to_node):
            return
        # Reject cycles before _remove_unneeded_edges mutates anything.
        if self._is_reachable(to_node, from_node):
            raise ValueError(
                f"Edge {from_node.name} -> {to_node.name} would create a cycle."
            )
        self._remove_unneeded_edges(from_node, to_node)
        super().add_edge(from_node, to_node)

    # Stand-in for the typical ancestor-cone size, which is not maintained
    # per node. Used only to choose between two *exact* operators in get(),
    # so a bad estimate costs time, never correctness. Deliberately biased
    # high (ancestor cones in category graphs are usually far smaller than
    # this) so the probe only fires when it is clearly the cheaper plan.
    _PROBE_COST_ESTIMATE = 16

    def get(self, super_categories):
        """Return all items that are subcategories of all specified super-categories.

        The result is the intersection of the query terms' descendant cones.
        The cheap, reliable decisions are planned up front; the decision that
        depends on information only produced by retrieval itself is made
        adaptively between steps. Every step is result-preserving.

        Planned in advance (the inputs — `descendant_count` — are exact,
        maintained statistics, so this needs no runtime correction):

        1. Terms are resolved by name and deduplicated (identity at the public
           boundary is the name, never the caller's object).
        2. A term that is an ancestor of another term is dropped: its cone is
           a superset of the other's, so it cannot narrow the intersection.
           The ancestry test walks *upward* from the smaller-count term via
           `_has_ancestors` (bounded by its shallow ancestor cone), never
           downward from the larger one (whose descendant cone may be most of
           the graph): planner work must scale with the query, not with the
           graph. `descendant_count` supplies the cheap necessary condition —
           a strict ancestor always has a strictly larger count.
        3. The surviving cones are ordered smallest-count-first (name as
           tiebreak, keeping traversal deterministic).

        Decided during retrieval: after each step the running result's size
        is known exactly — something no up-front plan can estimate, since
        cone overlap is not a per-term statistic — so before each remaining
        term the cheaper of two exact operators is chosen:

        - walk: traverse the term's whole cone and intersect
          (cost ~ its `descendant_count`);
        - probe: walk upward from each surviving candidate and keep those
          with every remaining term among their ancestors (cost ~
          len(result) x ancestor-cone size, independent of the remaining
          cones' sizes — and one pass settles *all* remaining terms).

        The loop also stops as soon as the running result is empty, so the
        largest cones are often never walked at all.

        Note for future optimizers: a node whose parents are exactly {A, B} is
        NOT the meet of A and B — put(X, [A, B]) creates a *sibling* of such a
        node, never a child of it — so rewriting a query through "meet-named"
        nodes (answering get([A, B, C]) as cone(AB) ∩ cone(C)) silently loses
        results. See docs/SEMANTIC_CODES.md §10 before adding such a rewrite;
        it is sound only with a canonical-placement invariant on put().
        """
        # 1. Resolve and deduplicate; terms may be name strings or Items
        # (names are the identity at the public boundary); an unknown term
        # has an empty cone.
        terms = {}
        for super_category in super_categories:
            node = self.nodes.get(_name_of(super_category))
            if node is None:
                return set()
            terms[node.name] = node
        if not terms:
            # Preserves the pre-planner behavior (set.intersection() with no
            # sets raised TypeError), with an intelligible message.
            raise TypeError("get() requires at least one super-category")

        # 2. Drop terms subsumed by another term.
        nodes = list(terms.values())
        minimal = [
            node for node in nodes
            if not any(
                other is not node
                and node.descendant_count > other.descendant_count
                and self._has_ancestors(other, (node,))
                for other in nodes
            )
        ]

        # 3. Smallest cone first.
        minimal.sort(key=lambda node: (node.descendant_count, node.name))

        # Adaptive execution: walk or probe, decided per step from the now-
        # known size of the running result.
        common_subcategories = self.get_descendants(minimal[0])
        for index, node in enumerate(minimal[1:], start=1):
            if not common_subcategories:
                break
            remaining = minimal[index:]
            probe_cost = len(common_subcategories) * self._PROBE_COST_ESTIMATE
            if probe_cost < sum(term.descendant_count for term in remaining):
                # One upward walk per candidate settles every remaining term.
                # (Candidates can never equal query terms: a surviving term
                # is an ancestor of no other term, so no term lies inside the
                # first term's cone — strict ancestry is the right test.)
                return {candidate for candidate in common_subcategories
                        if self._has_ancestors(candidate, remaining)}
            common_subcategories &= self.get_descendants(node)
        return common_subcategories

    def get_by_dag(self, query_dag):
        """
        Returns a new DAG with a new root, with the nodes that are intersected with the query nodes,
        including their common descendants.
        The highest level super-categories from the query DAG are added under the root, and their common descendants
        are added under the respective super-categories.
        """
        intersected_dag = self.intersection_dag(query_dag)
        intersected_dag_nodes = intersected_dag.nodes.values()

        copy_dag = self.copy_subdag(intersected_dag_nodes)
        copy_dag.prune_to_common_descendants(intersected_dag_nodes)
        return copy_dag

    def _remove_duplicate_root_edges(self):
        edges_to_remove = set()
        root = self.root
        for root_neighbor in root.neighbors:
            ancestors = self.get_ancestors(root_neighbor, ignore={root})
            if any(ancestor in root.neighbors for ancestor in ancestors):
                edges_to_remove.add(root_neighbor)

        for root_neighbor in edges_to_remove:
            self.remove_edge(root, root_neighbor)

    def _remove_unneeded_edges(self, from_node, to_node):
        """Remove unneeded edges originating from ancestors."""
        ancestors = self.get_ancestors(from_node)
        for ancestor in ancestors:
            if to_node in ancestor.neighbors:
                self.remove_edge(ancestor, to_node)

    def put(self, subcategory, super_categories, optimized=False):
        # Names are the identity at the public boundary: plain strings are
        # accepted anywhere an Item is (see "Identity" in CLAUDE.md).
        if isinstance(subcategory, str):
            subcategory = Item(subcategory)
        super_names = [_name_of(sc) for sc in super_categories]
        if any(name not in self.nodes for name in super_names):
            raise ValueError("One or more super-categories do not exist.")
        if subcategory.name == self.root.name and self.root.name in self.nodes:
            raise ValueError("Already exists as root.")

        if subcategory.name in self.nodes:
            existing = self.nodes[subcategory.name]
            # A re-put asserts the incoming metadata: its keys win.
            if subcategory is not existing and subcategory.metadata:
                existing.metadata.update(subcategory.metadata)
            subcategory = existing
        else:
            self.add_node(subcategory)

        super_categories = [self.nodes[name] for name in super_names]

        if not super_categories:
            super_categories = [self.root]

        if optimized:
            def element_set(dag, items):
                elements = set()
                for node in items:
                    ancestors = dag.get_ancestors(node, {dag.root})
                    elements.update(ancestors)
                return elements

            def extended_set(dag, nodes):
                extended_set = nodes.copy()
                for node in nodes:
                    down_set = dag.get_descendants(node)
                    for descendant in down_set:
                        if all(ancestor in extended_set for ancestor in dag.get_ancestors(descendant, {dag.root})):
                            extended_set.add(descendant)
                return extended_set

            def bottom_set(nodes):
                filtered = [node for node in DAG(nodes).topological_sort() if node in nodes]

                def has_no_neighbors(node):
                    return len(node.neighbors) == 0

                return list(filter(has_no_neighbors, filtered))

            elements = element_set(self, super_categories)
            extended = extended_set(self, elements)
            bottom = bottom_set(extended)
            super_categories = bottom

        with self._batched_count_updates():
            for super_cat in super_categories:
                self.add_edge(super_cat, subcategory)

    def remove(self, node_to_remove):
        # Accept a name string or any Item, and resolve to this instance's
        # node: a fresh Item("X") has empty parents/neighbors, so operating
        # on the caller's object instead of ours would orphan X's children
        # and corrupt the graph.
        name = _name_of(node_to_remove)
        if name not in self.nodes:
            raise ValueError(f"Item {name} does not exist.")
        if name == self.root.name:
            raise ValueError("Cannot remove the root.")
        node_to_remove = self.nodes[name]

        super_categories = {parent for parent in node_to_remove.parents
                            if self.nodes.get(parent.name) is parent}
        subcategories = set(node_to_remove.neighbors)

        with self._batched_count_updates():
            # Remove edges pointing from the removed node
            for subcategory in subcategories:
                self.remove_edge(node_to_remove, subcategory)

            # Remove edges pointing to the removed node
            for super_category in super_categories:
                self.remove_edge(super_category, node_to_remove)

            del self.nodes[node_to_remove.name]
            del node_to_remove

            # Add edges from all super-categories of the removed node to all its subcategories
            for super_category in super_categories:
                # If the node has any super-category other than the root, an edge from the root is not needed
                if super_category is self.root and any(super_cat != self.root for super_cat in super_categories):
                    continue
                for subcategory in subcategories:
                    self.add_edge(super_category, subcategory)
                self._update_descendant_counts(super_category)

    def merge(self, other_dag):
        """Merge another OntoDAG into this one.

        Args:
            other_dag (OntoDAG): The DAG to merge into this one.
        """
        if not isinstance(other_dag, OntoDAG):
            raise ValueError("Can only merge with another OntoDAG instance.")

        with self._batched_count_updates():
            # Pass 1: add all missing nodes (no edges yet). Metadata merges
            # per key with ours winning on conflict (same policy as the
            # payload/meta carry-over in SwarmOntoDAG.merge).
            for node_name, other_node in other_dag.nodes.items():
                if node_name not in self.nodes:
                    self.add_node(Item(node_name, metadata=other_node.metadata))
                else:
                    for key, value in other_node.metadata.items():
                        self.nodes[node_name].metadata.setdefault(key, value)

            # Pass 2: add edges in topological order (general → specific) using
            # add_edge so _remove_unneeded_edges prunes redundant edges correctly.
            for other_node in other_dag.topological_sort():
                self_node = self.nodes[other_node.name]
                for neighbor in other_node.neighbors:
                    if neighbor.name in self.nodes:
                        self.add_edge(self_node, self.nodes[neighbor.name])

            self._remove_duplicate_root_edges()

            # Update descendant counts
            for node in self.nodes.values():
                self._update_descendant_counts(node)

    def prune_to_common_descendants(self, interesting_nodes):
        # Gather each node's descendants in a list of sets
        sets_of_descendants = []
        for node in interesting_nodes:
            if node.name in self.nodes:
                sets_of_descendants.append(self.get_descendants(self.nodes[node.name]))
            else:
                sets_of_descendants = []
                break

        # If any interesting node is missing or there's nothing to keep, remove all but root
        if not sets_of_descendants:
            for n in list(self.nodes.values()):
                if getattr(self, 'root', None) and n is not self.root:
                    self.remove(n)
            return

        # Find the intersection of all descendant sets
        common_descendants = set.intersection(*sets_of_descendants)
        only_common_descendants = common_descendants.copy()

        # Include the interesting nodes themselves
        for node in interesting_nodes:
            if node.name in self.nodes:
                common_descendants.add(self.nodes[node.name])

        # Remove all other nodes from the DAG
        for n in list(self.nodes.values()):
            if n not in common_descendants and getattr(self, 'root', None) and n is not self.root:
                self.remove(n)

        # Remove duplicate edges between ancestors and lower level sub-categories
        for n in list(self.nodes.values()):
            for subcategory in list(n.neighbors):
                subcategory_ancestors = self.get_ancestors(subcategory, {self.root})
                for ancestor in subcategory_ancestors:
                    if ancestor in n.neighbors and subcategory in n.neighbors:
                        self.remove_edge(n, subcategory)
                        print(f'Removed edge {n.name} -> {subcategory.name}')

    def copy_subdag(self, nodes_to_copy):
        new_dag = OntoDAG()
        root_to_copy = None

        # Collect all nodes to copy, including descendants
        all_nodes_to_copy = set()
        for node in nodes_to_copy:
            if node.name == new_dag.root.name:
                root_to_copy = node
                continue
            original_node = self.nodes[node.name]
            all_nodes_to_copy.add(original_node)
            all_nodes_to_copy.update(self.get_descendants(original_node))

        mapping = {}

        # Create new items for all relevant nodes
        for node in all_nodes_to_copy:
            copy_item = Item(node.name, metadata=node.metadata)
            mapping[node] = copy_item
            new_dag.add_node(copy_item)

        # Preserve edges among copied nodes
        for original_node, copy_item in mapping.items():
            for neighbor in original_node.neighbors:
                if neighbor in mapping:
                    copy_item.neighbors.add(mapping[neighbor])
        # Set edges from the root
        if root_to_copy is not None:
            for root_neighbor in root_to_copy.neighbors:
                new_dag.root.neighbors.add(mapping[root_neighbor])

        # Recalculate descendant counts
        for copy_item in new_dag.nodes.values():
            copy_item.descendant_count = len(new_dag.get_descendants(copy_item))

        return new_dag

    def deepcopy(self):
        new_dag = OntoDAG()
        mapping = {}

        # Create new items
        for original_item in self.nodes.values():
            copy_item = Item(original_item.name, metadata=original_item.metadata)
            mapping[original_item] = copy_item
            new_dag.add_node(copy_item)

        # Connect neighbors
        for original_item, copy_item in mapping.items():
            for neighbor in original_item.neighbors:
                copy_item.neighbors.add(mapping[neighbor])

        # Update the root reference
        new_dag.root = mapping[self.root]

        # Recalculate descendant counts
        for node in new_dag.nodes.values():
            node.descendant_count = len(new_dag.get_descendants(node))

        return new_dag


class OntoDAGVisualizer:
    def __init__(self, format="png", layout="TB", default_color="seashell", root_color="seashell3"):
        self.format = format
        self.layout = layout
        self.default_color = default_color
        self.root_color = root_color

    def visualize(self, dag, filename="ontodag_vis", color_mapping=None):
        from graphviz import Digraph
        dag_type = dag.__class__.__name__
        graph = Digraph(comment=dag_type, format=self.format)
        graph.attr(rankdir=self.layout)

        for node in dag.nodes.values():
            self._render_node(graph, node, is_root=node.name == dag.root.name, color_mapping=color_mapping)

        # Render the graph to a file
        output_path = graph.render(filename)
        print(f"{dag_type} visualization saved as: {output_path}")

    def generate_dot_source(self, dag, color_mapping=None):
        from graphviz import Digraph
        dag_type = dag.__class__.__name__
        graph = Digraph(comment=dag_type, format="dot")
        graph.attr(rankdir=self.layout)

        for node in dag.nodes.values():
            self._render_node(graph, node, is_root=node.name == dag.root.name, color_mapping=color_mapping)

        # Return the DOT source string
        return graph.source

    def generate_image(self, dag, color_mapping=None):
        from graphviz import Digraph
        from io import BytesIO
        from PIL import Image

        dag_type = dag.__class__.__name__
        graph = Digraph(comment=dag_type, format=self.format)
        graph.attr(rankdir=self.layout)

        for node in dag.nodes.values():
            self._render_node(graph, node, is_root=node.name == dag.root.name, color_mapping=color_mapping)

        png_data = graph.pipe(format="png")
        return Image.open(BytesIO(png_data))

    def _render_node(self, graph, node, is_root=False, color_mapping=None):
        if color_mapping is None:
            color = self.root_color if is_root else self.default_color
        else:
            color = self.root_color if is_root else color_mapping.get(node, self.default_color)
        # Add nodes
        graph.node(node.name, f'{node.name}: {node.descendant_count}', style="filled", fillcolor=color)
        # Add edges for each super-category-to-subcategory relationship
        for subcategory in node.neighbors:
            graph.edge(node.name, subcategory.name)
