class Item:
    def __init__(self, name, comparator=None):
        self.name = name
        self.neighbors = set()
        self.descendant_count = 0
        self.comparator = comparator

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return f"Item({self.name}, [{', '.join(neighbor.name for neighbor in self.neighbors)}])"

    def to_dict(self):
        return {
            "name": self.name,
            "neighbors": [neighbor.name for neighbor in self.neighbors],
            "descendant_count": self.descendant_count
        }


class DAG:
    def __init__(self, nodes=None):
        self.nodes = {}
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

        from_node.neighbors.add(to_node)

        self._update_descendant_counts(from_node)

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
        # Reset counts for affected nodes
        affected = set()
        self._get_affected_nodes(parent, affected)
        for node in affected:
            node.descendant_count = 0

        # Recalculate counts for affected nodes
        for node in affected:
            node.descendant_count = len(self.get_descendants(node))

    def _get_affected_nodes(self, node, affected):
        """Get node and all its ancestors that need count updates"""
        if node in affected:
            return
        affected.add(node)
        for potential_ancestor in self.nodes.values():
            if node in potential_ancestor.neighbors:
                self._get_affected_nodes(potential_ancestor, affected)

    def get_descendants(self, node, visited=None):
        if visited is None:
            visited = set()
        if node in visited:
            return set()
        visited.add(node)
        descendants = set()  # Descendants of the current node
        for neighbor in node.neighbors:
            descendants.add(neighbor)
            descendants.update(self.get_descendants(neighbor, visited))
        return descendants

    def get_ancestors(self, node, ignore=()):
        if node.name not in self.nodes:
            raise ValueError(f"Node {node.name} does not exist in the graph.")

        ancestors = set()

        def _get_ancestors_helper(current_node):
            # Check each node in the graph
            for potential_parent in self.nodes.values():
                # If this node has the current node as a neighbor
                if current_node in potential_parent.neighbors:
                    # Add it to ancestors if not already present
                    if potential_parent not in ancestors and potential_parent not in ignore:
                        ancestors.add(potential_parent)
                        # Recursively check this parent's ancestors
                        _get_ancestors_helper(potential_parent)

        # Start the recursive search
        _get_ancestors_helper(node)
        return ancestors

    def intersection_dag(self, other_dag):
        intersecting_dag = OntoDAG()

        # Add nodes that exist in both DAGs
        for node in self.nodes.values():
            if node.name is intersecting_dag.root.name:
                continue
            if node.name in other_dag.nodes:
                intersecting_dag.add_node(node)

        for root_subcategory in other_dag.root.neighbors:
            if root_subcategory.name in self.nodes:
                intersecting_dag.root.neighbors.add(root_subcategory)

        return intersecting_dag

    def topological_sort(self):
        visited = set()
        stack = []

        def visit(node):
            if node in visited:
                return
            visited.add(node)
            for neighbor in node.neighbors:
                visit(neighbor)
            stack.append(node)

        for node in self.nodes.values():
            visit(node)

        return stack  # Nodes in topological order


class OntoDAG(DAG):
    def __init__(self):
        super().__init__()
        self.root = Item("*")
        self.nodes[self.root.name] = self.root

    def get(self, super_categories):
        """Return all items that are subcategories of all specified super-categories."""
        descendant_sets = []
        for super_category in super_categories:
            if super_category.name in self.nodes:
                descendants = self.get_descendants(super_category)
                descendant_sets.append(descendants)
            else:
                # Item not found; return empty set
                return set()
        # Intersection of all descendant sets
        common_subcategories = set.intersection(*descendant_sets)
        return common_subcategories

    def get_by_dag(self, query_dag):
        """
        Returns a new DAG with a new root, with the nodes that are intersected with the query nodes,
        including their common descendants.
        """
        intersected_dag = self.intersection_dag(query_dag)
        intersected_dag_nodes = intersected_dag.nodes.values()

        copy_dag = self.copy_subdag(intersected_dag_nodes)
        copy_dag.prune_to_common_descendants(intersected_dag_nodes)
        return copy_dag

    def get_as_dag(self, super_categories):
        """
        Return a new OntoDAG containing the common descendants of the given super_categories.
        The super_categories themselves are added under the root, and their common descendants
        are added under the respective super_categories.
        """
        # Create a new OntoDAG
        new_dag = OntoDAG()

        # Ensure super_categories exist and add them to new DAG
        valid_super_cats = []
        for cat in super_categories:
            if cat.name not in self.nodes:
                # If a super_category doesn't exist in the original DAG, ignore it
                continue
            new_dag.put(Item(cat.name), [new_dag.root])
            valid_super_cats.append(cat)

        if not valid_super_cats:
            return new_dag

        # **Preserve any ancestry found between the valid super\-categories**
        # TODO: Simplify this logic
        for i in range(len(valid_super_cats)):
            for j in range(i + 1, len(valid_super_cats)):
                if valid_super_cats[j] in self.get_ancestors(self.nodes[valid_super_cats[i].name]):
                    new_dag.add_edge(new_dag.nodes[valid_super_cats[j].name],
                                     new_dag.nodes[valid_super_cats[i].name])
                if valid_super_cats[i] in self.get_ancestors(self.nodes[valid_super_cats[j].name]):
                    new_dag.add_edge(new_dag.nodes[valid_super_cats[i].name],
                                     new_dag.nodes[valid_super_cats[j].name])

        # Gather descendants for each valid super_category
        descendant_sets = []
        for cat in valid_super_cats:
            descendant_sets.append(self.get_descendants(self.nodes[cat.name]))

        # Intersection of all descendant sets
        common_descendants = set.intersection(*descendant_sets)

        for node in common_descendants:
            # Gather super_categories that are not ancestors of another super_category
            node_ancestors = self.get_ancestors(node)

            chosen_super_categories = []
            for cat in valid_super_cats:
                # Skip cat if it is an ancestor of any other super_category in valid_super_cats
                if any(cat in self.get_ancestors(self.nodes[other.name])
                       for other in valid_super_cats if other != cat):
                    continue
                # Only add cat if node is not already a descendant of another common descendant
                if not node_ancestors.intersection(common_descendants):
                    chosen_super_categories.append(new_dag.nodes[cat.name])

            # Add the descendant item with chosen super-categories as parents
            new_dag.put(node, chosen_super_categories)

        new_dag._remove_duplicate_root_edges()

        return new_dag

    def _remove_duplicate_root_edges(self):
        edges_to_remove = set()
        root = self.root
        for root_neighbor in root.neighbors:
            ancestors = self.get_ancestors(root_neighbor, ignore={root})
            if any(ancestor in root.neighbors for ancestor in ancestors):
                edges_to_remove.add(root_neighbor)

        for root_neighbor in edges_to_remove:
            self.remove_edge(root, root_neighbor)

    def put(self, subcategory, super_categories, optimized=False):
        if any(super_cat.name not in self.nodes for super_cat in super_categories):
            raise ValueError("One or more super-categories do not exist.")
        if subcategory.name == self.root.name and self.root.name in self.nodes:
            raise ValueError("Already exists as root.")

        if subcategory.name in self.nodes:
            subcategory = self.nodes[subcategory.name]
        else:
            self.add_node(subcategory)

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

        for super_cat in super_categories:
            self.add_edge(super_cat, subcategory)

    def remove(self, node_to_remove):
        if node_to_remove.name not in self.nodes:
            raise ValueError(f"Item {node_to_remove.name} does not exist.")
        if node_to_remove.name == self.root.name:
            raise ValueError("Cannot remove the root.")

        super_categories = {node for node in self.nodes.values() if node_to_remove in node.neighbors}
        subcategories = set(node_to_remove.neighbors)

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

        # Process all nodes from other DAG
        for node_name, other_node in other_dag.nodes.items():
            if node_name in self.nodes:
                # Update existing node's neighbors
                self.nodes[node_name].neighbors.update(other_node.neighbors)
            else:
                # Add new node
                new_node = Item(node_name)
                new_node.neighbors = other_node.neighbors.copy()
                self.add_node(new_node)

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
            if node.name is new_dag.root.name:
                root_to_copy = node
                continue
            original_node = self.nodes[node.name]
            all_nodes_to_copy.add(original_node)
            all_nodes_to_copy.update(self.get_descendants(original_node))

        mapping = {}

        # Create new items for all relevant nodes
        for node in all_nodes_to_copy:
            copy_item = Item(node.name)
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
            copy_item = Item(original_item.name)
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
    def __init__(self, format="png", layout="TB"):
        self.format = format
        self.layout = layout

    def visualize(self, dag, filename="ontodag_vis"):
        from graphviz import Digraph
        dag_type = dag.__class__.__name__
        graph = Digraph(comment=dag_type, format=self.format)
        graph.attr(rankdir=self.layout)

        for node in dag.nodes.values():
            # Add nodes
            graph.node(node.name, f'{node.name}: {node.descendant_count}')
            # Add edges for each super-category-to-subcategory relationship
            for subcategory in node.neighbors:
                graph.edge(node.name, subcategory.name)

        # Render the graph to a file
        output_path = graph.render(filename)
        print(f"{dag_type} visualization saved as: {output_path}")

    def generate_image(self, dag):
        from graphviz import Digraph
        from io import BytesIO
        from PIL import Image

        dag_type = dag.__class__.__name__
        graph = Digraph(comment=dag_type, format=self.format)
        graph.attr(rankdir=self.layout)

        for node in dag.nodes.values():
            # Add nodes
            graph.node(node.name, f'{node.name}: {node.descendant_count}')
            # Add edges for each super-category-to-subcategory relationship
            for subcategory in node.neighbors:
                graph.edge(node.name, subcategory.name)

        png_data = graph.pipe(format="png")
        return Image.open(BytesIO(png_data))
