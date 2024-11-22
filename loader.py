import csv

from ontodag import OntoDAG


class OntologyLoader:
    def load(self, ontodag) -> OntoDAG:
        pass


class CSVLoader(OntologyLoader):
    def __init__(self, file_path, process_row, preprocessor=None):
        self.file_path = file_path
        self.process_row = process_row
        self.preprocessor = preprocessor

    def load(self, ontodag) -> OntoDAG:
        if self.preprocessor:
            with open(self.file_path, mode='r') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    self.preprocessor(row, ontodag)

        with open(self.file_path, mode='r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                self.process_row(row, ontodag)

        return ontodag
