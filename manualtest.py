from ontodag import VisualizerOntoDAG

if __name__ == "__main__":
    ontodag = VisualizerOntoDAG()
    ontodag.put("Animal", [])
    ontodag.put("Mammal", ["Animal"])
    ontodag.put("Bird", ["Animal"])
    ontodag.put("Dog", ["Mammal"])
    ontodag.put("Cat", ["Mammal"])
    ontodag.put("Parrot", ["Bird"])
    ontodag.put("Has-colour", [])
    ontodag.put("Black", ["Has-colour"])
    ontodag.put("White", ["Has-colour"])
    ontodag.put("Green", ["Has-colour"])
    ontodag.put("Black Dog", ["Dog", "Black"])
    ontodag.put("Black Cat", ["Cat", "Black"])
    ontodag.put("Green Parrot", ["Parrot", "Green"])

    # Query all items that are subcategories of both "Mammal" and "Black"
    print(ontodag.get({"Mammal", "Black"}))  # Expected output: {"Black Dog", "Black Cat"}

    ontodag.visualize("cdag_visualization")