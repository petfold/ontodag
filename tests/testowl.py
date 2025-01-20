import os
import unittest

from dag import OntoDAG, Item
from owl import OWLOntology


class TestOWLOntology(unittest.TestCase):
    def setUp(self):
        self.owl = OWLOntology("tests/ontology.owl")

        self.dag = OntoDAG()
        self.dag.put(Item('A'), [])
        self.dag.put(Item('B'), [])
        self.dag.put(Item('C'), [])
        self.dag.put(Item('D'), [])
        self.dag.put(Item('F'), [])
        self.dag.put(Item('G'), [])
        self.dag.put(Item('AF'), [Item('A'), Item('F')])
        self.dag.put(Item('AB'), [Item('A'), Item('B')])
        self.dag.put(Item('BC'), [Item('B'), Item('C')])
        self.dag.put(Item('ABC'), [Item('AB'), Item('BC')])
        self.dag.put(Item('ABF'), [Item('AB'), Item('AF')])
        self.dag.put(Item('CD'), [Item('C'), Item('D')])

    def test_export_dag(self):
        test_filename = "test_ontology.owl"
        self.owl.export_dag(self.dag, test_filename)

        self.assertTrue(os.path.isfile(test_filename))
        os.remove(test_filename)

    def test_import_dag(self):
        test_filename = "test_ontology.owl"
        self.owl.export_dag(self.dag, test_filename)
        imported_dag = self.owl.import_dag(test_filename)

        self.assertIsNotNone(imported_dag)
        os.remove(test_filename)


if __name__ == '__main__':
    unittest.main()
