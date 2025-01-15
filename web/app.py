from io import BytesIO

from flask import Flask, request, jsonify, render_template, send_file
from dag import OntoDAG, Item, OntoDAGVisualizer

app = Flask(__name__)
my_dag = OntoDAG()


@app.route("/dag", methods=["GET"])
def get_dag():
    # Return a simple serialized representation
    # nodes = [str(node) for node in my_dag.nodes]
    nodes = [node.to_dict() for node in reversed(my_dag.topological_sort())]
    return jsonify({"nodes": nodes})


@app.route("/dag/image", methods=["GET"])
def get_dag_image():
    visualizer = OntoDAGVisualizer()
    img = visualizer.generate_image(my_dag)  # Returns e.g. a PIL Image
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/dag", methods=["POST"])
def add_dag_item():
    data = request.json
    subcategory = Item(data.get("subcategory"))
    super_categories = [Item(name) for name in data.get("super_categories", [])]
    my_dag.put(subcategory, super_categories)
    return jsonify({"message": "Item inserted."}), 201


@app.route("/dag", methods=["DELETE"])
def remove_dag_item():
    data = request.json
    subcategory = Item(data.get("subcategory"))
    my_dag.remove(subcategory)
    return jsonify({"message": "Item removed."}), 200


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
