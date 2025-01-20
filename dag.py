class Item:
    _instances = {}  # Class-level cache of instances

    def __new__(cls, name):
        # Return existing instance if name already exists
        if name in cls._instances:
            return cls._instances[name]
        # Create new instance if name doesn't exist
        instance = super().__new__(cls)
        cls._instances[name] = instance
        return instance

    def __init__(self, name):
        # Only initialize if this is a new instance
        if not hasattr(self, 'name'):
            self.name = name
            self.neighbors = set()
            self.descendant_count = 0

    def __eq__(self, other):
        if not isinstance(other, Item):
            return False
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
        if nodes is None:
            self.nodes = set()
        else:
            self.nodes = nodes

    def add_node(self, node):
        """Add a node (Item) to the graph."""
        self.nodes.add(node)

    def add_edge(self, from_node, to_node):
        """Add a directed edge between two nodes."""
        if from_node not in self.nodes or to_node not in self.nodes:
            raise ValueError("Both nodes must exist in the graph")

        if from_node == to_node:
            return
        if to_node in from_node.neighbors:
            return

        from_node.neighbors.add(to_node)

        self._update_descendant_counts(from_node)

    def remove_edge(self, from_node, to_node):
        # Verify nodes exist
        if from_node not in self.nodes or to_node not in self.nodes:
            raise ValueError("Both nodes must exist in the graph")

        # Remove child from parent's neighbors
        if to_node not in from_node.neighbors:
            raise ValueError("Edge does not exist")
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
        for potential_ancestor in self.nodes:
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
        if node not in self.nodes:
            raise ValueError(f"Node {node.name} does not exist in the graph")

        ancestors = set()

        def _get_ancestors_helper(current_node):
            # Check each node in the graph
            for potential_parent in self.nodes:
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

        for node in self.nodes:
            visit(node)

        return stack  # Nodes in topological order


class OntoDAG(DAG):
    def __init__(self):
        super().__init__()
        self.root = Item("*")
        self.nodes.add(self.root)

    def get(self, super_categories):
        """Return all items that are subcategories of all specified super-categories."""
        descendant_sets = []
        for super_category in super_categories:
            if super_category in self.nodes:
                descendants = self.get_descendants(super_category)
                descendant_sets.append(descendants)
            else:
                # Item not found; return empty set
                return set()
        # Intersection of all descendant sets
        common_subcategories = set.intersection(*descendant_sets)
        return common_subcategories

    def put(self, subcategory, super_categories, optimized=False):
        if any(super_cat not in self.nodes for super_cat in super_categories):
            raise ValueError("One or more super-categories do not exist.")

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
        if node_to_remove not in self.nodes:
            raise ValueError(f"Item {node_to_remove.name} does not exist")

        super_categories = {node for node in self.nodes if node_to_remove in node.neighbors}
        subcategories = set(node_to_remove.neighbors)

        # Remove edges pointing from the removed node
        for subcategory in subcategories:
            self.remove_edge(node_to_remove, subcategory)

        # Remove edges pointing to the removed node
        for super_category in super_categories:
            self.remove_edge(super_category, node_to_remove)

        self.nodes.remove(node_to_remove)
        del node_to_remove

        # Add edges from all super-categories of the removed node to all its subcategories
        for super_category in super_categories:
            # If the node has any super-category other than the root, an edge from the root is not needed
            if super_category is self.root and any(super_cat != self.root for super_cat in super_categories):
                continue
            for subcategory in subcategories:
                self.add_edge(super_category, subcategory)
            self._update_descendant_counts(super_category)


class OntoDAGVisualizer:
    def __init__(self, format="png", layout="TB"):
        self.format = format
        self.layout = layout

    def visualize(self, dag, filename="ontodag_vis"):
        from graphviz import Digraph
        dag_type = dag.__class__.__name__
        graph = Digraph(comment=dag_type, format=self.format)
        graph.attr(rankdir=self.layout)

        for node in dag.nodes:
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

        for node in dag.nodes:
            # Add nodes
            graph.node(node.name, f'{node.name}: {node.descendant_count}')
            # Add edges for each super-category-to-subcategory relationship
            for subcategory in node.neighbors:
                graph.edge(node.name, subcategory.name)

        png_data = graph.pipe(format="png")
        return Image.open(BytesIO(png_data))