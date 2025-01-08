import types

from dag import OntoDAG, OntoDAGVisualizer
from owlready2 import get_ontology, Thing, AnnotationProperty


class OWLOntology:
    def __init__(self, ontology):
        self.ontology = get_ontology(ontology)

    def export_dag(self, dag, file_name="new_ontology.owl"):
        with self.ontology:
            class super_category_of(AnnotationProperty):
                domain = [Thing]
                range = [Thing]

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
                    # Annotate with super-category relationship
                    super_cls.super_category_of.append(sub_cls)

        self.ontology.save(file=file_name)

    def import_dag(self, file_name) -> OntoDAG:
        if not file_name:
            raise ValueError("file_name must not be empty")
        self.ontology.load(file_name)

        dag = OntoDAG()
        classes = list(self.ontology.classes())
        for cls in classes:
            dag.add_node(cls.name)
        for cls in classes:
            for super_cls in cls.is_a:
                # Prevent default parent 'Thing' from appearing in the DAG
                if super_cls is not Thing:
                    dag.add_edge(super_cls.name, cls.name)

        return dag


# Example usage
dag = OntoDAG()
dag.put('A', [])
dag.put('B', [])
dag.put('C', [])
dag.put('D', [])
dag.put('F', [])
dag.put('G', [])
dag.put('AF', ['A', 'F'])
dag.put('AB', ['A', 'B'])
dag.put('BC', ['B', 'C'])
dag.put('ABC', ['AB', 'BC'])
dag.put('ABF', ['AB', 'AF'])
dag.put('CD', ['C', 'D'])
element_set_query = ['AB', 'CD']
dag.put('E', element_set_query, optimized=True)

owl = OWLOntology("http://example.org/new_ontology.owl")
owl.export_dag(dag, "new_ontology_classes.owl")

imported_dag = owl.import_dag("new_ontology_classes.owl")
visualizer = OntoDAGVisualizer()
visualizer.visualize(imported_dag, "owl_test_vis_classes")
