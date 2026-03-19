import os
import tempfile
import types
import uuid

from dag import OntoDAG, Item
from io import BytesIO
try:
    from ontopy import get_ontology
except ImportError:
    from owlready2 import get_ontology
from owlready2 import Thing


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

        ontology.save(filename=file_name, format="rdfxml")

    @staticmethod
    def generate_manchester_content(dag, unique_id=None) -> str:
        """Generate Manchester OWL syntax content string from a DAG.

        The root node ("*") is omitted; top-level nodes appear as classes with no
        SubClassOf declaration (implicitly subclasses of owl:Thing).
        """
        if unique_id is None:
            unique_id = str(uuid.uuid4())
        urn_iri = f'urn:ontodag_{unique_id}'

        topological_nodes = dag.topological_sort()

        # Build parent map: child_name -> [parent_name, ...] (excluding the root)
        parent_map = {node.name: [] for node in topological_nodes}
        for node in topological_nodes:
            if node.name == dag.root.name:
                continue
            for child in node.neighbors:
                parent_map[child.name].append(node.name)

        lines = [f'Ontology: <{urn_iri}>', '']

        for node in topological_nodes:
            if node.name == dag.root.name:
                continue
            lines.append(f'Class: {node.name}')
            parents = parent_map[node.name]
            if parents:
                lines.append(f'    SubClassOf: {", ".join(parents)}')
            lines.append('')

        return '\n'.join(lines)

    @staticmethod
    def export_dag_manchester(dag, file_name="new_ontology.omn", unique_id=None):
        """Export a DAG to Manchester OWL syntax (.omn) format."""
        content = OWLOntology.generate_manchester_content(dag, unique_id)
        with open(file_name, 'w', encoding='utf-8') as f:
            f.write(content)

    def import_dag(self, file_name=None, file_content=None) -> OntoDAG:
        if not file_name and not file_content:
            raise ValueError("file_name or file_content must be provided")
        if file_content:
            # ontopy's load() does not support fileobj; write to a temp file
            raw = file_content.read() if hasattr(file_content, 'read') else file_content
            with tempfile.NamedTemporaryFile(suffix='.owl', delete=False) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            try:
                self.ontology = get_ontology(f"file://{tmp_path}").load()
            finally:
                os.unlink(tmp_path)
        else:
            self.ontology = get_ontology(f"file://{os.path.abspath(file_name)}").load()
        return self._process_dag()

    @staticmethod
    def import_dag_manchester(file_name=None, file_content=None) -> OntoDAG:
        """Import a DAG from Manchester OWL syntax (.omn) format.

        Accepts a file path, a BytesIO object, or raw bytes/str content.
        Classes with no SubClassOf become direct children of the DAG root.
        """
        if file_name is None and file_content is None:
            raise ValueError("file_name or file_content must be provided")

        if file_name:
            with open(file_name, 'r', encoding='utf-8') as f:
                content = f.read()
        else:
            if isinstance(file_content, (bytes, bytearray)):
                content = file_content.decode('utf-8')
            elif hasattr(file_content, 'read'):
                raw = file_content.read()
                content = raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else raw
            else:
                content = file_content

        # Parse Class declarations and SubClassOf relationships
        classes = {}  # name -> [parent_name, ...]
        current_class = None

        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith('Class:'):
                current_class = stripped[len('Class:'):].strip()
                classes[current_class] = []
            elif stripped.startswith('SubClassOf:') and current_class is not None:
                parents_str = stripped[len('SubClassOf:'):].strip()
                parents = [p.strip() for p in parents_str.split(',') if p.strip()]
                classes[current_class].extend(parents)

        dag = OntoDAG()
        for name in classes:
            dag.add_node(Item(name))

        for name, parents in classes.items():
            child = dag.nodes[name]
            if parents:
                for parent_name in parents:
                    if parent_name in dag.nodes:
                        dag.add_edge(dag.nodes[parent_name], child)
            else:
                dag.add_edge(dag.root, child)

        return dag

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
