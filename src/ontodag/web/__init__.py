"""The browser interface: a Flask app and the REST API under it.

Inside the package rather than beside it, because `pip install
"ontodag[web]"` promised a web app and delivered only its dependencies —
Flask, dot2tex, graphviz, owlready2 and Pillow installed with nothing to
run. Now `odag web` (or `odag-web`) starts it.

Importing this module must stay free of Flask: `ontodag.web.serve` is
reached from the CLI's command table, which the core imports, and B1 says
the core carries no optional dependency. The app itself lives one import
deeper, in `ontodag.web.app`.
"""


def serve(host="127.0.0.1", port=5000, debug=False):
    """Run the development server. Blocks until interrupted.

    `debug` defaults to **off**, unlike a bare `python app.py`: the Werkzeug
    debugger executes arbitrary code from the browser, which is a reasonable
    trade for one developer on a laptop and a catastrophe on anything
    reachable. Nothing in the CLI turns it on.
    """
    from ontodag._extras import require

    require("flask", "web", "the web interface")
    from ontodag.web.app import app

    app.run(host=host, port=port, debug=debug)


def main(argv=None):
    """The `odag-web` script — the same thing `odag web` runs."""
    import sys

    from ontodag.__main__ import Session, _resolve_store, dispatch

    argv = list(sys.argv[1:] if argv is None else argv)
    sys.exit(dispatch(["web"] + argv, Session(_resolve_store())))
