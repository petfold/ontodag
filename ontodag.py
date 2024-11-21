from graphviz import Digraph


class Item:
    def __init__(self, name):
        self.name = name
        self.counter = 1
        self.subcategories = set()

    def add_subcategory(self, subcategory):
        self.subcategories.add(subcategory)

    def increase_counter(self):
        self.counter += 1

    def decrease_counter(self):
        self.counter -= 1

    def __repr__(self):
        return f"Item({self.name})"


class OntoDAG:
    def __init__(self):
        self.items = {}

    def put(self, name, supercategories):
        # Check that all supercategories exist
        for supercat_name in supercategories:
            if supercat_name not in self.items:
                raise ValueError(f"Supercategory '{supercat_name}' does not exist.")

        # Ensure the item exists
        if name not in self.items:
            self.items[name] = Item(name)

        # Add subcategory relationships
        for supercat_name in supercategories:
            supercat_item = self.items[supercat_name]
            supercat_item.add_subcategory(self.items[name])

    def _get_descendants(self, item):
        """Retrieve all descendants of a given item using DFS."""
        descendants = set()
        stack = [item]
        while stack:
            current = stack.pop()
            for sub in current.subcategories:
                if sub not in descendants:
                    descendants.add(sub)
                    stack.append(sub)
        return descendants

    def get(self, query_names):
        """Return all items that are subcategories of all items in the query set."""
        if not query_names:
            return set()

        # Retrieve descendants for each item in query
        descendant_sets = []
        for name in query_names:
            if name not in self.items:
                raise ValueError(f"Item '{name}' does not exist in OntoDAG.")
            descendant_sets.append(self._get_descendants(self.items[name]))

        # Find the intersection of all descendant sets
        result = set.intersection(*descendant_sets) if descendant_sets else set()
        return {item.name for item in result}

    def __repr__(self):
        return f"OntoDAG({self.items})"


class VisualizerOntoDAG(OntoDAG):

    def visualize(self, filename="cdag_visualization"):
        """Visualize the CDAG as a directed acyclic graph with top-to-bottom layout."""
        dot = Digraph(comment="CDAG", format="png")
        dot.attr(rankdir="TB")  # Top-to-bottom layout

        # Add nodes
        for item_name, item in self.items.items():
            dot.node(item_name, item_name)

        # Add edges for each supercategory-to-subcategory relationship
        for item_name, item in self.items.items():
            for subcategory in item.subcategories:
                dot.edge(item_name, subcategory.name)

        # Render the graph to a file
        output_path = dot.render(filename)
        print(f"CDAG visualization saved as: {output_path}")
