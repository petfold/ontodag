from graphviz import Digraph

class Item:
    def __init__(self, name):
        self.name = name
        self.subcategories = set()
    
    def add_subcategory(self, subcategory):
        self.subcategories.add(subcategory)

    def __repr__(self):
        return f"Item({self.name})"


class CDAG:
    def __init__(self):
        self.items = {}

    def put(self, name, supercategories):
        for supercat_name in supercategories:
            if supercat_name not in self.items:
                raise ValueError(f"Supercategory '{supercat_name}' does not exist.")
        
        if name not in self.items:
            self.items[name] = Item(name)
        
        for supercat_name in supercategories:
            supercat_item = self.items[supercat_name]
            supercat_item.add_subcategory(self.items[name])

    def _get_descendants(self, item):
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
        if not query_names:
            return set()
        
        descendant_sets = []
        for name in query_names:
            if name not in self.items:
                raise ValueError(f"Item '{name}' does not exist in CDAG.")
            descendant_sets.append(self._get_descendants(self.items[name]))

        result = set.intersection(*descendant_sets) if descendant_sets else set()
        return {item.name for item in result}

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

