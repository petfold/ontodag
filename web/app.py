import os
import sys
import uuid
import random
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ontodag.dag import OntoDAG, Item
from ontodag.viz import OntoDAGVisualizer, query_picture
from datetime import datetime, timedelta
from dot2tex import dot2tex
from flask import Flask, request, jsonify, render_template, send_file, session, send_from_directory
from flask.sessions import SessionInterface, SessionMixin
from io import BytesIO
from ontodag.owl import OWLOntology


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


def current_dag():
    """The session's DAG, created on demand.

    Session state used to be initialized only by the two page routes, so an
    API-only client — curl, a script, anything that never loads `/` — got a
    bare KeyError traceback from its first call. The REST API is a surface in
    its own right (User Guide §1.1), so it initializes its own state."""
    if "my_dag" not in session:
        session["my_dag"] = OntoDAG()
    return session["my_dag"]


def current_visualizer():
    """The session's visualizer, created on demand — same reason."""
    if "visualizer" not in session:
        init_session_visualizer()
    return session["visualizer"]


def _png(img):
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


def init_session_visualizer():
    session["vis_color_root"] = "seashell3"
    session["vis_color_default"] = "seashell"
    session["vis_color_query"] = "seashell"
    session["vis_color_query_result"] = "transparent"

    session["visualizer"] = OntoDAGVisualizer(default_color=session["vis_color_default"],
                                              root_color=session["vis_color_root"])


@app.route("/dag", methods=["POST"])
def create_dag():
    my_dag = OntoDAG()
    session["my_dag"] = my_dag
    return jsonify({"message": "New OntoDAG created."}), 201


@app.route("/dag", methods=["GET"])
def get_dag():
    my_dag = current_dag()
    nodes = [node.to_dict() for node in my_dag.topological_sort()]
    return jsonify({"nodes": nodes})


@app.route("/dag/image", methods=["GET"])
def get_dag_image():
    my_dag = current_dag()

    visualizer = current_visualizer()
    img = visualizer.generate_image(my_dag)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/dag/node", methods=["POST"])
def add_dag_items():
    data = request.json
    my_dag = current_dag()
    try:
        subcategories = [Item(name) for name in data.get("subcategories", [])]
        # Pass names through: put resolves them itself, which is what lets
        # parametric terms (weight(3kg), weight(..5kg)) materialize with
        # their anchors and sugar resolve to canonical names.
        super_categories = data.get("super_categories") or [my_dag.root.name]

        for subcategory in subcategories:
            my_dag.put(subcategory, super_categories)
        return jsonify({"message": "Item(s) inserted."}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except KeyError:
        return jsonify({"error": "Super-categories do not exist."}), 400


@app.route("/dag/node", methods=["DELETE"])
def remove_dag_items():
    data = request.json or {}
    my_dag = current_dag()
    names = data.get("subcategories", [])
    cone = (request.args.get("cone", "").lower() in ("1", "true", "yes")
            or bool(data.get("cone")))
    try:
        if cone:
            # The deleting removal: the categories and whatever only existed
            # under them. A cone member that also hangs elsewhere survives —
            # see GET /dag/removal to look before leaping.
            plan_cone, _ = my_dag.cone_removal_plan(names)
            deleted = my_dag.remove_cone(names)
            return jsonify({"message": "Item(s) deleted.",
                            "deleted": sorted(deleted),
                            "kept": sorted(plan_cone - deleted)}), 200
        # remove() accepts names and canonicalizes parametric sugar itself.
        for name in names:
            my_dag.remove(name)
        return jsonify({"message": "Item(s) removed."}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except KeyError:
        return jsonify({"error": "An item to remove does not exist."}), 400


def query_terms(remember=True):
    """The DNF this request asks about, as `get_any` takes it.

    `|` separates disjuncts, `,` conjoins within one:
      cat=Dog,Pet|Cat  ->  (Dog AND Pet) OR Cat
    An absent or empty `cat` is the empty query — no constraints, so every item
    — matching `odag get` with no terms and the MCP query tool.

    The terms are remembered in the session so that a follow-up export can be
    asked for without repeating them, which is how the page links work. The
    *terms* are remembered, never a result DAG: keeping the answer around is
    what let a query export serve a picture (see the export routes).
    """
    categories = request.args.get("cat")
    if categories is None and not remember:
        return session.get("query_terms", [[]])
    queries = [part.split(",") for part in categories.split("|")] \
        if categories else [[]]
    if remember:
        session["query_terms"] = queries
    return queries


@app.route("/dag/node", methods=["PATCH"])
def move_dag_items():
    """Reclassify: file items under new categories, retract the old ones.

    The missing third verb beside POST (which only ever *adds* a category) and
    DELETE (which removes the item). Without it a client could not move
    anything: remove-then-post loses whatever was filed underneath, since the
    children reattach to the old category and stay there.

        {"subcategories": ["ProjectA"], "to": ["archive"], "from": ["active"]}

    `from` omitted retracts every current classification (so `to` alone means
    "under this and nothing else"); `to` omitted is a pure unfiling, and the
    item becomes top-level rather than orphaned.

    The answer carries the **contested set**: items now under both an old and a
    new category. That happens when a shared item also hangs under something
    still in the old state, it is true rather than broken (subsumption inherits;
    exclusive status cannot), and no rule here can resolve it — so it is
    reported, exactly as `odag move` reports it.
    """
    data = request.json or {}
    items = data.get("subcategories") or data.get("items") or []
    to = data.get("to") or []
    from_ = data.get("from") or None
    if not items:
        return jsonify({"error": "no items to move"}), 400
    if not to and not from_:
        return jsonify({"error": "give `to`, `from`, or both"}), 400

    my_dag = current_dag()
    olds = list(from_) if from_ else sorted(
        {name for item in items
         if item in my_dag.nodes
         for name in my_dag._live_parent_names(item)
         if name != my_dag.root.name})
    try:
        retracted = my_dag.reclassify(items, to=to, from_=from_)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    contested = sorted({name for old in olds for new in to
                        if new != old and new in my_dag.nodes
                        for name in my_dag.contested(old, new)})
    return jsonify({
        "message": "Item(s) moved.",
        "retracted": sorted([parent, item] for parent, item in retracted),
        "contested": contested,
    }), 200


@app.route("/dag/removal", methods=["GET"])
def preview_removal():
    """What a `?cone=1` DELETE would take, without taking it.

    A cone removal deletes what only existed under the named categories, so the
    honest thing is to let a client look first — the same answer `odag remove
    --cone --dry-run` prints. Members of the cone that hang elsewhere too are
    reported as kept, because that is the part people do not expect."""
    names = request.args.getlist("name")
    if not names:
        return jsonify({"error": "need at least one name"}), 400
    my_dag = current_dag()
    if request.args.get("cone", "").lower() not in ("1", "true", "yes"):
        # Contraction removes exactly what you name and nothing else.
        missing = [name for name in names if name not in my_dag.nodes]
        if missing:
            return jsonify({"error": f"no such item(s): {', '.join(missing)}"}), 400
        return jsonify({"deleted": sorted(names), "kept": [], "cone": []})
    try:
        cone, deleted = my_dag.cone_removal_plan(names)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"cone": sorted(cone), "deleted": sorted(deleted),
                    "kept": sorted(cone - deleted)})


@app.route("/dag/query", methods=["GET"])
def get_query():
    queries = query_terms()

    my_dag = current_dag()
    # The query log SEMANTIC_CODES.md §9 waits on: one counter per queried
    # category-set (per disjunct, names as queried), across all sessions —
    # the empirical input for workload-driven index decisions. In-memory
    # and process-local, deliberately trivial.
    for query in queries:
        QUERY_LOG[",".join(sorted(query))] += 1
    try:
        # get()/get_any() resolve names themselves: unknown terms fail
        # closed (empty result / empty disjunct), parametric terms may be
        # virtual (weight(..5kg) needs no node), malformed parameters are
        # a client error.
        if len(queries) == 1:
            result_nodes = my_dag.get(queries[0])
        else:
            result_nodes = my_dag.get_any(queries)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"nodes": list([node.to_dict() for node in result_nodes])})


QUERY_LOG = Counter()  # category-set -> times queried (see /dag/stats/queries)


@app.route("/dag/stats/queries", methods=["GET"])
def get_query_stats():
    """The query workload, most-asked first — what SEMANTIC_CODES.md §9's
    adaptive index-admission policy will eventually read."""
    return jsonify({"queries": [
        {"cat": cat, "count": count}
        for cat, count in QUERY_LOG.most_common()
    ]})


@app.route("/dag/below", methods=["GET"])
def get_below():
    sub = request.args.get("sub")
    sup = request.args.get("sup")
    if not sub or not sup:
        return jsonify({"error": "need both sub and sup"}), 400
    my_dag = current_dag()
    try:
        # Unknown names fail closed to false; malformed parametric terms
        # are a client error, as in /dag/query.
        return jsonify({"below": my_dag.is_below(sub, sup)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# The picture is shaped in the package (ontodag.viz.query_picture), not
# here: the CLI's `visualize CAT...` draws the same view, and two copies
# of this would drift.
_query_picture = query_picture


@app.route("/dag/query/image", methods=["GET"])
def get_query_dag_image():
    categories = request.args.get("cat")
    my_dag = current_dag()
    if not categories:
        # The empty query is everything (see /dag/query), and everything
        # already has a picture — draw that rather than the empty query
        # DAG, whose result is just the root. The UI reaches this whenever
        # the query box is submitted blank.
        return _png(current_visualizer().generate_image(my_dag))
    # Same DNF spelling as /dag/query — `|` between disjuncts, `,` within
    # one. The picture used to split on `,` alone, so a union drew a single
    # node named "Japan|Hotel" and matched nothing.
    query = query_terms()

    query_result_dag = _query_picture(my_dag, query)
    session["query_result_dag"] = query_result_dag

    # Before reading the vis_color_* settings: they are set by the same
    # lazy initializer that builds the visualizer.
    visualizer = current_visualizer()
    # Shade the query terms differently from what they matched. `query` is
    # now a list of disjuncts, so the membership test flattens it.
    asked = {term for terms in query for term in terms}
    color_mapping = {
        node: session["vis_color_query"] if node.name in asked
        else session["vis_color_query_result"]
        for node in query_result_dag.nodes.values()
    }
    return _png(visualizer.generate_image(query_result_dag, color_mapping))


@app.route("/dag/query/dag/image", methods=["GET"])
def get_query_as_dag_dag_image():
    query_result_dag = session["query_result_dag"]
    query = session["query_dag"]

    visualizer = current_visualizer()
    # Make query nodes appear with a different color
    color_mapping = {}
    for node in query_result_dag.nodes.values():
        if node in query.nodes.values():
            color_mapping[node] = session["vis_color_query"]
        else:
            color_mapping[node] = session["vis_color_query_result"]

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
    my_dag = current_dag()
    try:
        if file.filename.endswith('.omn'):
            imported_dag = OWLOntology.import_dag_manchester(file_content=file_content)
        else:
            owl = OWLOntology(file.filename)
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
    my_dag = current_dag()
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
    my_dag = current_dag()
    filename = "ontodag_export.owl"
    owl = OWLOntology(filename)
    owl.export_dag(my_dag, filename)
    return send_file(filename, as_attachment=True)


@app.route("/dag/export/omn", methods=["GET"])
def export_dag_manchester():
    my_dag = current_dag()
    content = OWLOntology.generate_manchester_content(my_dag)
    buf = BytesIO(content.encode('utf-8'))
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name='ontodag_export.omn',
                     mimetype='text/plain')


@app.route("/dag/export/dot", methods=["GET"])
def export_dag_dot():
    my_dag = current_dag()
    visualizer = current_visualizer()
    dot_source = visualizer.generate_dot_source(my_dag)

    tex_file = BytesIO(dot_source.encode('utf-8'))
    tex_file.seek(0)
    return send_file(tex_file, as_attachment=True,
                     download_name='ontodag_export.dot',
                     mimetype='application/x-dot')


@app.route("/dag/export/tex", methods=["GET"])
def export_dag_tex():
    my_dag = current_dag()
    visualizer = current_visualizer()
    dot_source = visualizer.generate_dot_source(my_dag)
    tex_content = dot2tex(dot_source)

    tex_file = BytesIO(tex_content.encode('utf-8'))
    tex_file.seek(0)
    return send_file(tex_file, as_attachment=True,
                     download_name='ontodag_export.tex',
                     mimetype='application/x-tex')


def query_excerpt():
    """The EXCERPT of the current query — what a download must contain.

    Not the picture. These routes used to serve `session["query_result_dag"]`,
    which `/dag/query/image` sets to the drawn view — query terms invented as
    nodes so the constraint is visible. Downloading that and importing it filed
    the question as knowledge, and which file you got depended on which endpoint
    you had hit last. The rule is the same one the CLI follows (`odag excerpt`
    vs `odag visualize CAT...`): a picture may invent a node because it is
    discarded, a file may not because it is imported.

    `?cat=` names the query (same DNF as /dag/query); omitted, the session's
    last query is used, which is how the page's download links work. `?context=1`
    also includes the categories the answers hang from, so the file merges into
    a store that shares them — `odag excerpt --context`.
    """
    context = request.args.get("context", "").lower() in ("1", "true", "yes")
    return current_dag().excerpt(query_terms(remember=False), context=context)


@app.route("/dag/query/export", methods=["GET"])
def export_query_dag():
    unique_id = str(uuid.uuid4())
    filename = f'ontodag_query_export_{unique_id}.owl'
    owl = OWLOntology(filename)
    owl.export_dag(query_excerpt(), filename, unique_id)
    return send_file(filename, as_attachment=True)


@app.route("/dag/query/export/omn", methods=["GET"])
def export_query_dag_manchester():
    unique_id = str(uuid.uuid4())
    content = OWLOntology.generate_manchester_content(query_excerpt(), unique_id)
    buf = BytesIO(content.encode('utf-8'))
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name=f'ontodag_query_export_{unique_id}.omn',
                     mimetype='text/plain')


@app.route("/dag/query/export/dot", methods=["GET"])
def export_query_dag_dot():
    dot_source = current_visualizer().generate_dot_source(query_excerpt())
    buf = BytesIO(dot_source.encode('utf-8'))
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name='ontodag_query_export.dot',
                     mimetype='application/x-dot')


@app.route("/dag/query/export/tex", methods=["GET"])
def export_query_dag_tex():
    dot_source = current_visualizer().generate_dot_source(query_excerpt())
    buf = BytesIO(dot2tex(dot_source).encode('utf-8'))
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name='ontodag_query_export.tex',
                     mimetype='application/x-tex')


@app.route("/")
def index():
    if "my_dag" not in session:
        session["my_dag"] = OntoDAG()

    if "visualizer" not in session:
        init_session_visualizer()

    return render_template("index.html")


@app.route("/market")
def index_cars():
    # The demo shares the `my_dag` session key with the main page, so a
    # session that already has an ordinary DAG in it — which, since every
    # endpoint now creates one on demand, means almost any session that
    # touched `/` first — used to skip this load and then die on
    # `nodes['ActiveOffer']`. Load whenever the DAG present isn't a car one.
    if "my_dag" not in session or "ActiveOffer" not in session["my_dag"].nodes:
        owl = OWLOntology('http://127.0.0.1:5000/market/dag')
        owl.ontology.load()
        dag = owl._process_dag()
        session['my_dag'] = dag

    if "car_categories_dag" not in session:
        owl = OWLOntology('http://127.0.0.1:5000/market/dag/categories')
        owl.ontology.load()
        dag = owl._process_dag()
        session['car_categories_dag'] = dag

    if "visualizer" not in session:
        init_session_visualizer()

    if "cars" not in session:
        dag = session['my_dag']
        super_categories = [dag.nodes['ActiveOffer']]
        results = dag.get(super_categories)

        cars = []
        for result in results:
            usd_price = float(round(random.randint(10000, 70000), -3))
            eth_usd = 4000.0
            vehicle = {
                'id': result.name,
                'mileage': random.randint(2000, 40000),
                'price': [{"value": usd_price, "currency": "USD"}, {"value": usd_price / eth_usd, "currency": "ETH"}],
                'year': random.randint(2015, 2025),
            }
            cars.append(vehicle)
        session["cars"] = cars

    return render_template("cars.html")


@app.route('/market/dag')
def get_car_market_dag():
    return send_from_directory('cars', 'car_market.owl')


@app.route('/market/dag/categories')
def get_car_market_categories():
    return send_from_directory('cars', 'car_market_props.owl')


@app.route('/cars', methods=['GET'])
def get_cars():
    return jsonify(session["cars"])


@app.route('/cars/query', methods=['GET'])
def query_cars():
    categories = request.args.get("q")
    if not categories:
        return jsonify({"error": "No categories provided"}), 400
    query = categories.split(",")

    dag = session['my_dag']
    super_categories = [dag.nodes[name.strip()] for name in query]
    super_categories.append(dag.nodes['Offer'])
    results = dag.get(super_categories)

    car_results = []
    for result in results:
        for car in session["cars"]:
            if car['id'] == result.name:
                car_results.append(car)
    return jsonify(car_results)


@app.route("/dag/categories/buyer", methods=["GET"])
def get_categories_for_buyer():
    categories_dag = session["car_categories_dag"]
    categories_for_buyer = categories_dag.nodes.get("QueryableProperty")
    if not categories_for_buyer:
        return jsonify({"error": "QueryableProperty category not found"}), 404

    def _create_category(node):
        return {
            "name": node.name,
            "neighbors": [{"name": n.name} for n in node.neighbors]
        }

    categories = []
    for neighbor in categories_for_buyer.neighbors:
        category = _create_category(neighbor)
        categories.append(category)
        for sub_neighbor in neighbor.neighbors:
            sub_category = _create_category(sub_neighbor)
            if sub_category["neighbors"]:
                categories.append(sub_category)

    return jsonify(categories)


@app.route('/cars/<string:car_id>', methods=['GET'])
def get_car(car_id):
    def _find_car(car_id):
        """Finds a car by ID.  Returns the car (dict) or None if not found."""
        for car in session["cars"]:
            if car['id'] == car_id:
                return car
        return None

    car = _find_car(car_id)
    if car:
        return jsonify(car)
    return jsonify({'message': 'Car not found'}), 404


@app.route('/images/<filename>')
def get_image(filename):
    return send_from_directory('cars/images', filename)


if __name__ == "__main__":
    app.run(debug=True)
