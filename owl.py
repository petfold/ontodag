import types

from dag import OntoDAG, Item
from owlready2 import get_ontology, Thing, AnnotationProperty


class OWLOntology:
    def __init__(self, ontology):
        self.ontology = get_ontology(ontology)

    def export_dag(self, dag, file_name="new_ontology.owl"):
        with self.ontology:
            classes = {}
            # Create classes for each DAG node
            for node in dag.nodes.values():
                classes[node.name] = types.new_class(node.name, (Thing,))

            # Define is_a relationships (subclasses) for each node's neighbors (subcategories)
            for node in dag.nodes.values():
                super_cls = classes[node.name]
                for neighbor in node.neighbors:
                    sub_cls = classes[neighbor.name]
                    sub_cls.is_a.append(super_cls)
                    # Only the root node has to be a subclass of Thing
                    if Thing in sub_cls.is_a:
                        sub_cls.is_a.remove(Thing)

        self.ontology.save(file=file_name)

    def import_dag(self, file_name=None, file_content=None) -> OntoDAG:
        if not file_name and not file_content:
            raise ValueError("file_name or file_content must be provided")
        self.ontology.load(file_name, fileobj=file_content)
        return self._process_dag()

    def _process_dag(self) -> OntoDAG:
        dag = OntoDAG()
        classes = list(self.ontology.classes())
        for cls in classes:
            dag.add_node(Item(cls.name))
            # Ensure that the default root is replaced with the actual
            if cls.name is dag.root.name:
                dag.root = dag.nodes[dag.root.name]
        for cls in classes:
            for super_cls in cls.is_a:
                # Prevent default parent Thing from appearing in the DAG
                if super_cls is not Thing:
                    super_category = dag.nodes[super_cls.name]
                    subcategory = dag.nodes[cls.name]
                    dag.add_edge(super_category, subcategory)

        return dag
