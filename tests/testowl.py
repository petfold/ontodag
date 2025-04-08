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


if __name__ == '__main__':
    unittest.main()
