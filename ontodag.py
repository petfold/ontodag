class Item:
    def __init__(self, name):
        self.name = name
        self.subcategories = set()
    
    def add_subcategory(self, subcategory):
        self.subcategories.add(subcategory)

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
        

if __name__ == "__main__":
    ontodag = OntoDAG()
    ontodag.put("Animal", [])
    ontodag.put("Mammal", ["Animal"])
    ontodag.put("Bird", ["Animal"])
    ontodag.put("Dog", ["Mammal"])
    ontodag.put("Cat", ["Mammal"])
    ontodag.put("Parrot", ["Bird"])
    ontodag.put("Has-colour", [])
    ontodag.put("Black", ["Has-colour"])
    ontodag.put("White", ["Has-colour"])
    ontodag.put("Green", ["Has-colour"])
    ontodag.put("Black Dog", ["Dog", "Black"])
    ontodag.put("Black Cat", ["Cat", "Black"])
    ontodag.put("Green Parrot", ["Parrot", "Green"])

    # Query all items that are subcategories of both "Mammal" and "Black"
    print(ontodag.get({"Mammal", "Black"}))  # Expected output: {"Black Dog", "Black Cat"}

