class Item:
    def __init__(self, name):
        self.name = name
        self.neighbors = []  # Subcategories

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
        parent.neighbors.append(child)

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

    def get_common_subcategories(self, item_names):
        descendant_sets = []
        for name in item_names:
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


# Example usage
dag = DAG()
dag.add_edge('A', 'B')
dag.add_edge('A', 'C')
dag.add_edge('B', 'D')
dag.add_edge('C', 'D')
dag.add_edge('C', 'E')

# Query items
query_items = ['B']
common_subcategories = dag.get_common_subcategories(query_items)

# Output the names of the common subcategories
print("Common subcategories:", [item.name for item in common_subcategories])
