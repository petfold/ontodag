from graphviz import Digraph


class Item:
    def __init__(self, name):
        self.name = name
        self.counter = 0
        self.subcategories = set()

    def add_subcategory(self, subcategory):
        self.subcategories.add(subcategory)

    def increase_counter(self):
        self.counter += 1

    def decrease_counter(self):
        if self.counter > 0:
            self.counter -= 1

    def __repr__(self):
        return f"Item({self.name})"


class Root(Item):
    def __init__(self):
        super().__init__("*")


class OntoDAG:
    def __init__(self, root_item=None):
        if root_item is None:
            root_item = Root()
        self.items = {root_item.name: root_item}
        self.root = root_item

    def put(self, name, supercategories):
        if not supercategories:
            supercategories = [self.root.name]

        if any(supercat_name not in self.items for supercat_name in supercategories):
            raise ValueError("One or more supercategories do not exist.")

        if name not in self.items:
            self.items[name] = Item(name)

        done = set()

        def mark_done(item):
            if item.name not in done:
                done.add(item.name)
                for parent_item in self.items.values():
                    if item in parent_item.subcategories and parent_item.name not in done:
                        parent_item.increase_counter()
                        mark_done(parent_item)

        for supercat_name in supercategories:
            mark_done(self.items[supercat_name])
            supercat_item = self.items[supercat_name]
            if name not in done:
                supercat_item.add_subcategory(self.items[name])
                supercat_item.increase_counter()

    def remove(self, name):
        if name not in self.items:
            raise ValueError(f"Item '{name}' does not exist in OntoDAG.")

        item_to_remove = self.items[name]

        def decrease_ancestors(item):
            for parent_item in self.items.values():
                if item in parent_item.subcategories:
                    parent_item.decrease_counter()
                    decrease_ancestors(parent_item)

        decrease_ancestors(item_to_remove)

        for parent_item in self.items.values():
            parent_item.subcategories.discard(item_to_remove)

        del self.items[name]

    @staticmethod
    def _get_descendants(item):
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
        descendant_sets = [
            self._get_descendants(self.items[name])
            for name in query_names
            if name in self.items
        ]

        if len(descendant_sets) != len(query_names):
            raise ValueError("One or more items in the query do not exist in OntoDAG.")

        # Find the intersection of all descendant sets
        result = set.intersection(*descendant_sets) if descendant_sets else set()
        return {item.name for item in result}

    def get_root(self):
        return self.root

    def __repr__(self):
        return f"OntoDAG({self.items})"


class VisualizerOntoDAG(OntoDAG):

    def visualize(self, filename="ontodag_visualization"):
        """Visualize the OntoDAG as a directed acyclic graph with top-to-bottom layout."""
        dot = Digraph(comment="OntoDAG", format="png")
        dot.attr(rankdir="TB")  # Top-to-bottom layout

        # Add nodes
        for item_name, item in self.items.items():
            dot.node(item_name, f'{item_name}: {item.counter}')

        # Add edges for each supercategory-to-subcategory relationship
        for item_name, item in self.items.items():
            for subcategory in item.subcategories:
                dot.edge(item_name, subcategory.name)

        # Render the graph to a file
        output_path = dot.render(filename)
        print(f"OntoDAG visualization saved as: {output_path}")
