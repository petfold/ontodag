import os
import tempfile
import types
import uuid

from ontodag.dag import OntoDAG, Item

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
        """Generate Manchester OWL syntax content string from a DAG."""
        if unique_id is None:
            unique_id = str(uuid.uuid4())
        urn_iri = f'urn:ontodag_{unique_id}'

        topological_nodes = dag.topological_sort()

        # Build parent map: child_name -> [parent_name, ...] including root
        parent_map = {node.name: [] for node in topological_nodes}
        for node in topological_nodes:
            for child in node.neighbors:
                parent_map[child.name].append(node.name)

        lines = [
            f'Prefix: : <{urn_iri}#>',
            'Prefix: owl: <http://www.w3.org/2002/07/owl#>',
            '',
            f'Ontology: <{urn_iri}>',
            '',
        ]

        for node in topological_nodes:
            lines.append(f'Class: :{node.name}')
            parents = parent_map[node.name]
            if node.name == dag.root.name:
                lines.append('    SubClassOf: owl:Thing')
            elif parents:
                lines.append(f'    SubClassOf: {", ".join(":" + p for p in parents)}')
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
    def merge_manchester_into(target_dag: OntoDAG, content: str) -> None:
        """Merge a Manchester syntax string into an existing OntoDAG.

        Unlike import_dag_manchester() followed by merge(), parent references
        in the content are resolved against target_dag — so a node may declare
        a supercategory that exists only in the target DAG (not in the input
        string) and the edge will still be created.
        """
        def _strip_prefix(name):
            return name[1:] if name.startswith(':') else name

        classes: dict[str, list[str]] = {}
        current_class = None
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith('Class:'):
                current_class = _strip_prefix(stripped[len('Class:'):].strip())
                classes[current_class] = []
            elif stripped.startswith('SubClassOf:') and current_class is not None:
                parents_str = stripped[len('SubClassOf:'):].strip()
                for p in parents_str.split(','):
                    p = p.strip()
                    if p and p != 'owl:Thing':
                        classes[current_class].append(_strip_prefix(p))

        root_name = target_dag.root.name

        # Pass 1: add new nodes
        for name in classes:
            if name != root_name and name not in target_dag.nodes:
                target_dag.add_node(Item(name))

        # Pass 2: add edges, resolving all parents against target_dag
        for name, parents in classes.items():
            if name == root_name:
                continue
            child = target_dag.nodes[name]
            resolved = [p for p in parents if p != root_name and p in target_dag.nodes]
            if resolved:
                for parent_name in resolved:
                    target_dag.add_edge(target_dag.nodes[parent_name], child)
            else:
                target_dag.add_edge(target_dag.root, child)

        target_dag._remove_duplicate_root_edges()
        for node in target_dag.nodes.values():
            target_dag._update_descendant_counts(node)

    @staticmethod
    def import_dag_manchester(file_name=None, file_content=None) -> OntoDAG:
        """Import a DAG from Manchester OWL syntax (.omn) format.

        Accepts a file path, or raw bytes/str content.
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

        def _strip_prefix(name):
            """Strip the local ':' prefix from a class name."""
            return name[1:] if name.startswith(':') else name

        # Parse Class declarations and SubClassOf relationships
        classes = {}  # name -> [parent_name, ...]
        current_class = None

        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith('Class:'):
                current_class = _strip_prefix(stripped[len('Class:'):].strip())
                classes[current_class] = []
            elif stripped.startswith('SubClassOf:') and current_class is not None:
                parents_str = stripped[len('SubClassOf:'):].strip()
                parents = [
                    _strip_prefix(p.strip())
                    for p in parents_str.split(',')
                    if p.strip() and p.strip() != 'owl:Thing'
                ]
                classes[current_class].extend(parents)

        dag = OntoDAG()

        # If the exported root class ('*') is present, wire it up as the DAG root
        root_name = dag.root.name
        for name in classes:
            if name == root_name:
                continue  # root node already exists in dag
            dag.add_node(Item(name))

        for name, parents in classes.items():
            if name == root_name:
                continue  # root needs no incoming edges
            child = dag.nodes[name]
            non_root_parents = [p for p in parents if p != root_name and p in dag.nodes]
            if non_root_parents:
                for parent_name in non_root_parents:
                    dag.add_edge(dag.nodes[parent_name], child)
            elif not parents or all(p == root_name for p in parents):
                # parent is root (explicit or implicit)
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
