import os
import unittest

from dag import OntoDAG, Item
from owl import OWLOntology


class TestOWLOntology(unittest.TestCase):
    def setUp(self):
        self.owl = OWLOntology("tests/ontology.owl")

        self.a = Item('A')
        self.b = Item('B')
        self.c = Item('C')
        self.d = Item('D')
        self.e = Item('E')
        self.f = Item('F')
        self.g = Item('G')
        self.ab = Item('AB')
        self.af = Item('AF')
        self.bc = Item('BC')
        self.cd = Item('CD')
        self.abc = Item('ABC')
        self.abf = Item('ABF')

        self.dag = OntoDAG()
        self.dag.put(self.a, [])
        self.dag.put(self.b, [])
        self.dag.put(self.c, [])
        self.dag.put(self.d, [])
        self.dag.put(self.f, [])
        self.dag.put(self.g, [])
        self.dag.put(self.af, [self.a, self.f])
        self.dag.put(self.ab, [self.a, self.b])
        self.dag.put(self.bc, [self.b, self.c])
        self.dag.put(self.abc, [self.ab, self.bc])
        self.dag.put(self.abf, [self.ab, self.af])
        self.dag.put(self.cd, [self.c, self.d])

    def test_export_dag(self):
        test_filename = "test_ontology.owl"
        self.owl.export_dag(self.dag, test_filename)

        self.assertTrue(os.path.isfile(test_filename))
        os.remove(test_filename)

    def test_import_dag(self):
        test_filename = "test_ontology.owl"
        self.owl.export_dag(self.dag, test_filename)

        self.assertTrue(os.path.isfile(test_filename))
        imported_dag = self.owl.import_dag(file_name=test_filename)

        self.assertIsNotNone(imported_dag)
        os.remove(test_filename)

    def test_export_dag_manchester(self):
        test_filename = "test_ontology.omn"
        OWLOntology.export_dag_manchester(self.dag, test_filename)

        self.assertTrue(os.path.isfile(test_filename))
        with open(test_filename, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('Prefix: : <', content)
        self.assertIn('Prefix: owl: <http://www.w3.org/2002/07/owl#>', content)
        self.assertIn('Ontology:', content)
        self.assertIn('Class: :*', content)
        self.assertIn('SubClassOf: owl:Thing', content)
        self.assertIn('Class: :A', content)
        self.assertIn('Class: :AB', content)
        self.assertIn('SubClassOf: :A', content)
        os.remove(test_filename)

    def test_import_dag_manchester(self):
        test_filename = "test_ontology.omn"
        OWLOntology.export_dag_manchester(self.dag, test_filename)

        self.assertTrue(os.path.isfile(test_filename))
        imported_dag = OWLOntology.import_dag_manchester(file_name=test_filename)

        self.assertIsNotNone(imported_dag)
        # All non-root nodes should be present
        expected_names = {'A', 'B', 'C', 'D', 'F', 'G', 'AB', 'AF', 'BC', 'CD', 'ABC', 'ABF'}
        imported_names = set(imported_dag.nodes.keys()) - {imported_dag.root.name}
        self.assertEqual(imported_names, expected_names)
        os.remove(test_filename)

    def test_manchester_roundtrip_structure(self):
        """Verify that SubClassOf relationships survive a Manchester export/import roundtrip."""
        test_filename = "test_ontology.omn"
        OWLOntology.export_dag_manchester(self.dag, test_filename)
        imported_dag = OWLOntology.import_dag_manchester(file_name=test_filename)

        # AB should have A and B as parents (neighbors of A and B point to AB)
        ab_node = imported_dag.nodes.get('AB')
        self.assertIsNotNone(ab_node)
        a_node = imported_dag.nodes.get('A')
        b_node = imported_dag.nodes.get('B')
        self.assertIn(ab_node, a_node.neighbors)
        self.assertIn(ab_node, b_node.neighbors)
        os.remove(test_filename)

    def test_generate_manchester_content(self):
        content = OWLOntology.generate_manchester_content(self.dag)
        self.assertIn('Ontology:', content)
        # Root "*" should not appear
        self.assertNotIn('Class: *', content)
        # Top-level nodes have no SubClassOf
        lines = content.splitlines()
        class_lines = [l for l in lines if l.startswith('Class:')]
        self.assertTrue(len(class_lines) > 0)

    def test_import_dag_manchester_from_bytes(self):
        content = OWLOntology.generate_manchester_content(self.dag)
        imported_dag = OWLOntology.import_dag_manchester(file_content=content.encode('utf-8'))
        self.assertIsNotNone(imported_dag)
        expected_names = {'A', 'B', 'C', 'D', 'F', 'G', 'AB', 'AF', 'BC', 'CD', 'ABC', 'ABF'}
        imported_names = set(imported_dag.nodes.keys()) - {imported_dag.root.name}
        self.assertEqual(imported_names, expected_names)


if __name__ == '__main__':
    unittest.main()
