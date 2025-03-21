import os
import uuid

from dag import OntoDAG, Item, OntoDAGVisualizer
from datetime import datetime, timedelta
from dot2tex import dot2tex
from flask import Flask, request, jsonify, render_template, send_file, session
from flask.sessions import SessionInterface, SessionMixin
from io import BytesIO
from owl import OWLOntology


class InMemorySession(dict, SessionMixin):
    def __init__(self, session_id=None):
        super().__init__()
        self.session_id = session_id
        self.modified = False

    def __setitem__(self, key, value):
        self.modified = True
        super().__setitem__(key, value)


class InMemorySessionInterface(SessionInterface):
    session_class = InMemorySession
    container = {}  # In-memory storage for sessions

    def generate_sid(self):
        return str(uuid.uuid4())

    def open_session(self, app, request):
        sid = request.cookies.get(app.config.get("SESSION_COOKIE_NAME", "session"))
        lifetime = app.config.get("PERMANENT_SESSION_LIFETIME")
        now = datetime.now()

        if not sid or sid not in self.container:
            sid = self.generate_sid()
            session = self.session_class(session_id=sid)
            self.container[sid] = session
            return session

        session = self.container.get(sid)
        expiry = session.get('expiry')

        # Check if the session has expired
        if expiry and now > expiry:
            # Clean up expired session
            del self.container[sid]
            # Create a new session
            sid = self.generate_sid()
            session = self.session_class(session_id=sid)
            session['expiry'] = now + lifetime
            self.container[sid] = session

        return session

    def save_session(self, app, session, response):
        if not session:
            return  # Do not save empty sessions

        session_cookie_name = app.config.get("SESSION_COOKIE_NAME", "session")  # ✅ Corrected
        domain = self.get_cookie_domain(app)
        expiry = session.get('expiry')

        # Set the cookie with the expiry time
        response.set_cookie(session_cookie_name, session.session_id, httponly=True, domain=domain, expires=expiry)


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_APP_SECRET_KEY")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=float(os.getenv("FLASK_SESSION_LIFETIME", 60)))
app.session_interface = InMemorySessionInterface()


@app.route("/dag", methods=["POST"])
def create_dag():
    my_dag = OntoDAG()
    my_dag.root.neighbors = set()
    my_dag.root.descendant_count = 0
    session["my_dag"] = my_dag
    return jsonify({"message": "New OntoDAG created."}), 201


@app.route("/dag", methods=["GET"])
def get_dag():
    my_dag = session["my_dag"]
    nodes = [node.to_dict() for node in my_dag.topological_sort()]
    return jsonify({"nodes": nodes})


@app.route("/dag/image", methods=["GET"])
def get_dag_image():
    my_dag = session["my_dag"]

    visualizer = session["visualizer"]
    img = visualizer.generate_image(my_dag)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/dag/node", methods=["POST"])
def add_dag_items():
    data = request.json
    my_dag = session["my_dag"]
    try:
        subcategories = [Item(name) for name in data.get("subcategories", [])]
        super_categories = [my_dag.nodes[name] for name in (data.get("super_categories") or [my_dag.root.name])]

        for subcategory in subcategories:
            my_dag.put(subcategory, super_categories)
        return jsonify({"message": "Item(s) inserted."}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except KeyError:
        return jsonify({"error": "Super-categories do not exist."}), 400


@app.route("/dag/node", methods=["DELETE"])
def remove_dag_items():
    data = request.json
    my_dag = session["my_dag"]
    try:
        subcategories = [my_dag.nodes[name] for name in data.get("subcategories", [])]
        for subcategory in subcategories:
            my_dag.remove(subcategory)
        return jsonify({"message": "Item(s) removed."}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except KeyError:
        return jsonify({"error": "An item to remove does not exist."}), 400


@app.route("/dag/query", methods=["GET"])
def get_query():
    categories = request.args.get("cat")
    if not categories:
        return jsonify({"error": "No categories provided"}), 400
    query = categories.split(",")

    my_dag = session["my_dag"]
    super_categories = [my_dag.nodes[name] for name in query]

    result_nodes = my_dag.get(super_categories)

    return jsonify({"nodes": list([node.to_dict() for node in result_nodes])})


@app.route("/dag/query/image", methods=["GET"])
def get_query_dag_image():
    categories = request.args.get("cat")
    if not categories:
        return jsonify({"error": "No categories provided"}), 400
    query = categories.split(",")

    my_dag = session["my_dag"]
    query_dag = OntoDAG()
    for super_category in query:
        query_dag.put(Item(super_category), [query_dag.root])

    query_result_dag = my_dag.get_by_dag(query_dag)
    session["query_result_dag"] = query_result_dag

    visualizer = session["visualizer"]
    # Make query nodes appear with a different color
    color_mapping = {}
    for node in query_result_dag.nodes.values():
        if node.name in query:
            color_mapping[node] = session["viz_color_query"]

    img = visualizer.generate_image(query_result_dag, color_mapping)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/dag/query/dag/image", methods=["GET"])
def get_query_as_dag_dag_image():
    query_result_dag = session["query_result_dag"]
    query = session["query_dag"]

    visualizer = session["visualizer"]
    # Make query nodes appear with a different color
    color_mapping = {}
    for node in query_result_dag.nodes.values():
        if node in query.nodes.values():
            color_mapping[node] = session["viz_color_query"]

    img = visualizer.generate_image(query_result_dag, color_mapping)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/dag/import", methods=["POST"])
def import_dag():
    if 'file' not in request.files:
        return jsonify({"error": "No file part."}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file."}), 400

    file_content = BytesIO(file.read())

    owl = OWLOntology(file.filename)
    my_dag = session["my_dag"]
    try:
        imported_dag = owl.import_dag(file_content=file_content)
        my_dag.merge(imported_dag)
        return jsonify({"message": "File imported and DAG created."}), 201
    except Exception as e:
        return jsonify({"error": "Error importing file. Reason: " + str(e)}), 400


@app.route("/dag/query/import", methods=["POST"])
def import_query_dag():
    if 'file' not in request.files:
        return jsonify({"error": "No file part."}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file."}), 400

    file_content = BytesIO(file.read())

    owl = OWLOntology(file.filename)
    my_dag = session["my_dag"]
    try:
        imported_query_dag = owl.import_dag(file_content=file_content)
        session["query_dag"] = imported_query_dag

        query_result_dag = my_dag.get_by_dag(imported_query_dag)
        session["query_result_dag"] = query_result_dag

        return jsonify({"nodes": list([node.to_dict() for node in query_result_dag.nodes.values()])})
    except Exception as e:
        return jsonify({"error": "Error importing file. Reason: " + str(e)}), 400


@app.route("/dag/export", methods=["GET"])
def export_dag():
    my_dag = session["my_dag"]
    filename = "ontodag_export.owl"
    owl = OWLOntology(filename)
    owl.export_dag(my_dag, filename)
    return send_file(filename, as_attachment=True)


@app.route("/dag/export/tex", methods=["GET"])
def export_dag_tex():
    my_dag = session["my_dag"]
    visualizer = session["visualizer"]
    dot_source = visualizer.generate_dot_source(my_dag)
    tex_content = dot2tex(dot_source)

    tex_file = BytesIO(tex_content.encode('utf-8'))
    tex_file.seek(0)
    return send_file(tex_file, as_attachment=True,
                     download_name='ontodag_export.tex',
                     mimetype='application/x-tex')


@app.route("/dag/query/export", methods=["GET"])
def export_query_dag():
    query_result_dag = session["query_result_dag"]
    unique_id = str(uuid.uuid4())
    filename = f'ontodag_query_export_{unique_id}.owl'
    owl = OWLOntology(filename)
    owl.export_dag(query_result_dag, filename, unique_id)
    return send_file(filename, as_attachment=True)


@app.route("/dag/query/export/tex", methods=["GET"])
def export_query_dag_tex():
    query_result_dag = session["query_result_dag"]
    visualizer = session["visualizer"]
    dot_source = visualizer.generate_dot_source(query_result_dag)
    tex_content = dot2tex(dot_source)

    tex_file = BytesIO(tex_content.encode('utf-8'))
    tex_file.seek(0)
    return send_file(tex_file, as_attachment=True,
                     download_name='ontodag_query_export.tex',
                     mimetype='application/x-tex')


@app.route("/")
def index():
    if "my_dag" not in session:
        session["my_dag"] = OntoDAG()

    session["viz_color_default"] = "seashell"
    session["viz_color_root"] = "seashell3"
    session["viz_color_query"] = "transparent"

    if "visualizer" not in session:
        session["visualizer"] = OntoDAGVisualizer(default_color=session["viz_color_default"],
                                                  root_color=session["viz_color_root"])

    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
