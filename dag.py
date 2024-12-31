from graphviz import Digraph


class Item:
    def __init__(self, name):
        self.name = name
        self.neighbors = []  # Subcategories (children)
        self.descendant_count = 0  # Number of descendants

    def __repr__(self):
        return f"Item({self.name})"


class DAG:
    def __init__(self, nodes=None):
        if nodes is None:
            self.nodes = {}
        else:
            self.nodes = {node.name: node for node in nodes}

    def add_node(self, name):
        if name not in self.nodes:
            self.nodes[name] = Item(name)
        return self.nodes[name]

    def add_edge(self, parent_name, child_name):
        parent = self.add_node(parent_name)
        child = self.add_node(child_name)

        if child in parent.neighbors:
            return  # Edge already exists

        parent.neighbors.append(child)

        self._update_descendant_counts(parent)

    def remove_edge(self, parent_name, child_name):
        # Verify nodes exist
        if parent_name not in self.nodes or child_name not in self.nodes:
            raise ValueError("One or both nodes do not exist in the graph")

        parent = self.nodes[parent_name]
        child = self.nodes[child_name]

        # Remove child from parent's neighbors
        if child not in parent.neighbors:
            raise ValueError("Edge does not exist")
        parent.neighbors.remove(child)

        self._update_descendant_counts(parent)

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
        if node.name in visited:
            return set()
        visited.add(node.name)
        descendants = set()  # Descendants of the current node
        for neighbor in node.neighbors:
            descendants.add(neighbor)
            descendants.update(self.get_descendants(neighbor, visited))
        return descendants

    def get_ancestors(self, node, ignore=()):
        if node.name not in self.nodes:
            raise ValueError(f"Node {node_name} does not exist in the graph")

        ancestors = set()

        def _get_ancestors_helper(current_node):
            # Check each node in the graph
            for potential_parent in self.nodes.values():
                # If this node has the current node as a neighbor
                if self.nodes[current_node.name] in potential_parent.neighbors:
                    # Add it to ancestors if not already present
                    if potential_parent not in ancestors and potential_parent.name not in ignore:
                        ancestors.add(potential_parent)
                        # Recursively check this parent's ancestors
                        _get_ancestors_helper(potential_parent)

        # Start the recursive search
        _get_ancestors_helper(node)
        return ancestors

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
        for name in super_categories:
            if name in self.nodes:
                node = self.nodes[name]
                descendants = self.get_descendants(node)
                descendant_sets.append(descendants)
            else:
                # Item not found; return empty set
                return set()
        # Intersection of all descendant sets
        common_subcategories = set.intersection(*descendant_sets)
        return common_subcategories

    def put(self, name, super_categories, optimized=False):
        if any(supercat_name not in self.nodes for supercat_name in super_categories):
            raise ValueError("One or more super-categories do not exist.")

        if not super_categories:
            super_categories = [self.root.name]

        if optimized:
            def element_set(dag, items):
                elements = set()
                for node_name in items:
                    ancestors = dag.get_ancestors(dag.nodes[node_name], dag.root.name)
                    elements.update(ancestors)
                return elements

            def extended_set(dag, nodes):
                extended_set = nodes.copy()
                for node in nodes:
                    down_set = dag.get_descendants(node)
                    for descendant in down_set:
                        if all(ancestor in extended_set for ancestor in dag.get_ancestors(descendant, dag.root.name)):
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
            super_categories = [node.name for node in bottom]

        for supercat_name in super_categories:
            self.add_edge(supercat_name, name)

    def remove(self, name):
        if name not in self.nodes:
            raise ValueError(f"Item {name} does not exist")

        node_to_remove = self.nodes[name]
        super_categories = {node for node in self.nodes.values() if node_to_remove in node.neighbors}
        subcategories = set(node_to_remove.neighbors)

        # Remove edges pointing from the removed node
        for subcategory in subcategories:
            self.remove_edge(name, subcategory.name)

        # Remove edges pointing to the removed node
        for super_category in super_categories:
            self.remove_edge(super_category.name, name)

        del self.nodes[name]

        # Add edges from all super-categories of the removed node to all its subcategories
        for super_category in super_categories:
            for subcategory in subcategories:
                self.add_edge(super_category.name, subcategory.name)
            self._update_descendant_counts(super_category)


class OntoDAGVisualizer:
    def __init__(self, format="png", layout="TB"):
        self.format = format
        self.layout = layout

    def visualize(self, dag, filename="ontodag_vis"):
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


# Example usage
dag = OntoDAG()
dag.put('A', [])
dag.put('B', [])
dag.put('C', [])
dag.put('D', [])
dag.put('F', [])
dag.put('G', [])
dag.put('AF', ['A', 'F'])
dag.put('AB', ['A', 'B'])
dag.put('BC', ['B', 'C'])
dag.put('ABC', ['AB', 'BC'])
dag.put('ABF', ['AB', 'AF'])
dag.put('CD', ['C', 'D'])

# Query items
query_items = ['B', 'C']
common_subcategories = dag.get(query_items)

# Output the names of the common subcategories
print("Common subcategories:", [item.name for item in common_subcategories])
print("Ancestors of AF:", dag.get_ancestors(dag.nodes['AF'], dag.root.name))

element_set_query = ['AB', 'CD']
dag.put('E', element_set_query, optimized=True)

# Display descendant counts
for node_name in dag.nodes:
    node = dag.nodes[node_name]
    print(f"Item {node.name} has {node.descendant_count} descendants")

print("Topological sort:", [node.name for node in dag.topological_sort()])

dag.remove('ABC')
print("Topological sort (after removing 'ABC'):", [node.name for node in dag.topological_sort()])
