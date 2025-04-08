import types
import uuid

from dag import OntoDAG, Item
from io import BytesIO
from owlready2 import get_ontology, Thing


class OWLOntology:
    def __init__(self, ontology):
        self.ontology = get_ontology(ontology)

    @staticmethod
    def export_dag(dag, file_name="new_ontology.owl", unique_id=None):
        if unique_id is None:
            unique_id = str(uuid.uuid4())
        urn_iri = f'urn:ontodag_{unique_id}'
        ontology = get_ontology(urn_iri)
        with ontology:
            classes = {}
            topological_nodes = dag.topological_sort()
            # Create classes for each DAG node
            for node in topological_nodes:
                cls = types.new_class(node.name, (Thing,))
                cls.namespace = ontology
                classes[node.name] = cls

            # Define is_a relationships (subclasses) for each node's neighbors (subcategories)
            for node in topological_nodes:
                super_cls = classes[node.name]
                for neighbor in node.neighbors:
                    sub_cls = classes[neighbor.name]
                    if super_cls not in sub_cls.is_a:
                        sub_cls.is_a.append(super_cls)
                    # Only the root node has to be a subclass of Thing
                    if Thing in sub_cls.is_a:
                        sub_cls.is_a.remove(Thing)

        ontology.save(file=file_name)

    def import_dag(self, file_name=None, file_content=None) -> OntoDAG:
        if not file_name and not file_content:
            raise ValueError("file_name or file_content must be provided")
        if file_name:
            with open(file_name, 'rb') as file:
                file_content = BytesIO(file.read())
        self.ontology.load(fileobj=file_content)
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
