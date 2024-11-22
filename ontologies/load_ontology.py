from loader import CSVLoader
from ontodag import VisualizerOntoDAG

if __name__ == "__main__":
    ontodag = VisualizerOntoDAG()
    ontodag.put("Earth", [])

    preprocessor = lambda row, ontodag: ontodag.put(row['Type'], [])
    process_row = lambda row, ontodag: ontodag.put(row['Name'], [row['Larger Region'], row['Type']])

    loader = CSVLoader('onto-geo-01.csv', process_row, preprocessor)
    loader.load(ontodag)

    ontodag.visualize("geo_ontology_visualization")
