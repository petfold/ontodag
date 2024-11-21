class Node:
    def __init__(self, name):
        self.name = name
        self.parents = set()   # Set of parent Node objects (supercategories)
        self.children = set()  # Set of child Node objects (subcategories)

class OntoDAG:
    def __init__(self):
        self.nodes = {}  # Dictionary to store node name to Node object

    def add_node(self, name):
        if name in self.nodes:
            # Node already exists
            return self.nodes[name]
        else:
            node = Node(name)
            self.nodes[name] = node
            return node

    def add_edge(self, child_name, parent_name):
        # Ensure both nodes exist
        if child_name not in self.nodes:
            raise ValueError(f"Node '{child_name}' does not exist.")
        if parent_name not in self.nodes:
            raise ValueError(f"Node '{parent_name}' does not exist.")

        child_node = self.nodes[child_name]
        parent_node = self.nodes[parent_name]

        # Add the edge from child to parent
        child_node.parents.add(parent_node)
        parent_node.children.add(child_node)
