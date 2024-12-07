class Item:
    def __init__(self, name):
        self.name = name
        self.neighbors = []  # Subcategories (children)
        self.descendant_count = 0  # Number of descendants

    def __repr__(self):
        return f"Item({self.name})"


class DAG:
    def __init__(self):
        self.nodes = {}

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

    def put(self, name, super_categories):
        if any(supercat_name not in self.nodes for supercat_name in super_categories):
            raise ValueError("One or more super-categories do not exist.")

        if not super_categories:
            super_categories = [self.root.name]

        for supercat_name in super_categories:
            self.add_edge(supercat_name, name)


# Example usage
dag = OntoDAG()
dag.put('A', [])
dag.put('B', 'A')
dag.put('C', 'A')
dag.put('D', ['B', 'C'])
dag.put('E', 'C')

# Query items
query_items = ['B', 'C']  # Expected result: ['D']
common_subcategories = dag.get(query_items)

# Output the names of the common subcategories
print("Common subcategories:", [item.name for item in common_subcategories])
print("Ancestors of D:", dag.get_ancestors(dag.nodes['D'], dag.root.name))

# Display descendant counts
for node_name in dag.nodes:
    node = dag.nodes[node_name]
    print(f"Item {node.name} has {node.descendant_count} descendants")

print("Topological sort:", [node.name for node in dag.topological_sort()])
