from io import BytesIO

from flask import Flask, request, jsonify, render_template, send_file
from dag import DAG, OntoDAG, Item, OntoDAGVisualizer

app = Flask(__name__)
my_dag = OntoDAG()
visualizer = OntoDAGVisualizer()


@app.route("/dag", methods=["GET"])
def get_dag():
    nodes = [node.to_dict() for node in reversed(my_dag.topological_sort())]
    return jsonify({"nodes": nodes})


@app.route("/dag/image", methods=["GET"])
def get_dag_image():
    img = visualizer.generate_image(my_dag)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/dag/node", methods=["POST"])
def add_dag_item():
    data = request.json
    subcategory = Item(data.get("subcategory"))
    super_categories = [Item(name) for name in data.get("super_categories", [])]
    my_dag.put(subcategory, super_categories)
    return jsonify({"message": "Item inserted."}), 201


@app.route("/dag/node", methods=["DELETE"])
def remove_dag_item():
    data = request.json
    subcategory = Item(data.get("subcategory"))
    my_dag.remove(subcategory)
    return jsonify({"message": "Item removed."}), 200


@app.route("/dag/query", methods=["GET"])
def get_query():
    categories = request.args.get("cat")
    if not categories:
        return jsonify({"error": "No categories provided"}), 400
    query = categories.split(",")
    super_categories = [Item(name) for name in query]

    result_nodes = my_dag.get(super_categories)

    return jsonify({"nodes": list([node.to_dict() for node in result_nodes])})


@app.route("/dag/query/image", methods=["GET"])
def get_query_dag_image():
    categories = request.args.get("cat")
    if not categories:
        return jsonify({"error": "No categories provided"}), 400
    query = categories.split(",")
    super_categories = [Item(name) for name in query]

    result_nodes = my_dag.get(super_categories)

    img = visualizer.generate_image(DAG(result_nodes))
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
