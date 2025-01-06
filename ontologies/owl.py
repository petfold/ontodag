from owlready2 import get_ontology, ObjectProperty, Thing

from dag import OntoDAG


class OWLOntology:
    def __init__(self, ontology):
        self.ontology = get_ontology(ontology)

    def export_dag(self, dag, file_name="new_ontology.owl"):
        with self.ontology:
            class super_category_of(ObjectProperty):
                domain = [Thing]
                range = [Thing]

            for node in dag.nodes.values():
                if node.name != dag.root.name:
                    owl_node = Thing(node.name)
                    subcategories = [Thing(neighbor.name) for neighbor in node.neighbors]
                    owl_node.super_category_of = subcategories

        self.ontology.save(file=file_name)

    def import_dag(self, file_name) -> OntoDAG:
        if not file_name:
            raise ValueError("file_name must not be empty")
        self.ontology.load(file_name)

        dag = OntoDAG()
        things = list(self.ontology.individuals())
        for thing in things:
            dag.add_node(thing.name)
        for thing in things:
            for subcategory in [neighbor.name for neighbor in thing.super_category_of]:
                dag.add_edge(thing.name, subcategory)

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
owl.export_dag(dag, "new_ontology.owl")
