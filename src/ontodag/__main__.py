"""odag — a Unix-style command line for OntoDAG.

(The command is `odag`, not `od`: `od` is the standard octal-dump utility.)

Design goals (see the module docstring history in CLAUDE.md):
  * silent on success, errors on stderr with a non-zero exit code;
  * a persistent default store in ~/.ontodag so `odag put cat` / `odag get cat`
    work with no file argument;
  * stdin / stdout / pipes: `odag` with no command reads commands from a pipe,
    or drops into an interactive prompt on a tty;
  * `-o FILE` redirects query output; `-f STORE` picks the store for one run;
  * `set store PATH` changes the persistent default.

The core (`ontodag.dag`) has no heavy dependencies, so the common native-store
path imports nothing else; OWL/Manchester support and the visualizer are
imported lazily only when a command actually needs them.
"""

import argparse
import os
import shlex
import sys

from ontodag.dag import OntoDAG, Item

try:
    from importlib.metadata import version, PackageNotFoundError
    try:
        __version__ = version("ontodag")
    except PackageNotFoundError:
        __version__ = "0.1.0"
except Exception:  # pragma: no cover - importlib.metadata always present on 3.8+
    __version__ = "0.1.0"


# --------------------------------------------------------------------------- #
# Home directory, config and store resolution
# --------------------------------------------------------------------------- #

def _home_dir():
    return os.environ.get("ONTODAG_HOME") or os.path.join(
        os.path.expanduser("~"), ".ontodag"
    )


def _config_path():
    return os.path.join(_home_dir(), "config")


def _read_config():
    cfg = {}
    path = _config_path()
    if not os.path.exists(path):
        return cfg
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            cfg[key.strip()] = value.strip()
    return cfg


def _write_config(cfg):
    os.makedirs(_home_dir(), exist_ok=True)
    with open(_config_path(), "w") as fh:
        for key in sorted(cfg):
            fh.write(f"{key} = {cfg[key]}\n")


def _abspath(path):
    return os.path.abspath(os.path.expanduser(path))


def _is_swarm(spec):
    return spec.startswith("swarm:")


def _normalize_spec(spec):
    """A store spec is either a `swarm:NAME` URI or a filesystem path.

    Swarm specs are kept verbatim; file paths are made absolute so a spec
    saved to config resolves the same from any working directory."""
    return spec if _is_swarm(spec) else _abspath(spec)


def _resolve_store(override):
    """Store precedence: -f flag > $ONTODAG_STORE > config > default."""
    if override:
        return _normalize_spec(override)
    env = os.environ.get("ONTODAG_STORE")
    if env:
        return _normalize_spec(env)
    cfg = _read_config()
    if cfg.get("store"):
        return _normalize_spec(cfg["store"])
    return os.path.join(_home_dir(), "store.od")


# --------------------------------------------------------------------------- #
# Serialization: native line format by default, OWL/Manchester by extension
# --------------------------------------------------------------------------- #

def _detect_format(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".omn":
        return "manchester"
    if ext == ".owl":
        return "owl"
    return "native"


def _load_native(path):
    """Read the native store: one line per node, `name parent1 parent2 ...`.

    A missing file is an empty DAG (the default store need not exist yet).
    The format is canonical (nodes and parents sorted on save) and the graph
    is rebuilt via add_edge, so even a hand-edited, non-reduced file loads as
    its unique transitive reduction.
    """
    dag = OntoDAG()
    if not os.path.exists(path):
        return dag
    edges = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tokens = shlex.split(line)
            name = tokens[0]
            if name not in dag.nodes:
                dag.add_node(Item(name))
            for parent in tokens[1:]:
                if parent not in dag.nodes:
                    dag.add_node(Item(parent))
                edges.append((parent, name))
    for parent, child in edges:
        dag.add_edge(dag.nodes[parent], dag.nodes[child])
    return dag


def _save_native(dag, path):
    lines = ["# ontodag store v1"]
    for name in sorted(dag.nodes):
        if name == dag.root.name:
            continue
        node = dag.nodes[name]
        parents = sorted(
            p.name for p in node.parents if dag.nodes.get(p.name) is p
        )
        lines.append(" ".join(shlex.quote(t) for t in [name] + parents))
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def _load(path):
    fmt = _detect_format(path)
    if fmt == "native":
        return _load_native(path)
    from ontodag.owl import OWLOntology
    if fmt == "manchester":
        return OWLOntology.import_dag_manchester(file_name=path)
    return OWLOntology(f"file://{_abspath(path)}").import_dag(file_name=path)


def _save(dag, path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fmt = _detect_format(path)
    if fmt == "native":
        _save_native(dag, path)
        return
    from ontodag.owl import OWLOntology
    if fmt == "manchester":
        OWLOntology.export_dag_manchester(dag, path)
    else:
        OWLOntology.export_dag(dag, path)


# --------------------------------------------------------------------------- #
# Storage backends
#
# A backend hides *where* the store lives behind load()/save(dag)/describe().
# The default is a local file (native/OWL/Manchester by extension). A
# `swarm:NAME` spec persists through EagerOntoDAG over a RecordStore, in one
# of two modes:
#
#   with a signer  -> recordstore.swarm_store(): blobs on a Bee node AND the
#                     mutable "latest root" in a Swarm feed, so the store has
#                     a stable address others can follow.
#   without one    -> blobs on Bee, latest root in a local FilePointer. No key
#                     needed, but nothing is publishable: readers would have
#                     to be handed a root hash by hand.
#
# recordstore and the adapter are imported lazily here, so `import ontodag`
# and the native path stay dependency-free (tests/test_boundaries.py B1).
# --------------------------------------------------------------------------- #

class FileBackend:
    def __init__(self, path):
        self.path = path

    def load(self):
        return _load(self.path)

    def save(self, dag):
        _save(dag, self.path)

    def describe(self):
        return self.path


class SwarmBackend:
    def __init__(self, name, store_factory=None):
        if not name:
            raise ValueError("swarm store needs a name, e.g. swarm:mydag")
        if os.sep in name or (os.altsep and os.altsep in name) or name == "..":
            raise ValueError(f"invalid swarm store name: {name!r}")
        self.name = name
        # Injection seam: tests pass a factory returning a RecordStore over an
        # in-memory bytes store, exercising the whole wiring without a node.
        self._store_factory = store_factory

    def pointer_path(self):
        return os.path.join(_home_dir(), self.name + ".root")

    def _record_store(self):
        if self._store_factory is not None:
            return self._store_factory()
        cfg = _read_config()
        api = os.environ.get("BEE_API") or cfg.get("bee_api") or "http://localhost:1633"
        batch = os.environ.get("BEE_BATCH") or cfg.get("bee_batch") or "auto"
        signer = os.environ.get("BEE_SIGNER") or cfg.get("bee_signer") or ""
        try:
            # BeeBytesStore imports `requests` in its constructor, so a missing
            # optional dependency surfaces here rather than at module import.
            if signer:
                from recordstore import swarm_store
                return swarm_store(self.name, api_url=api, stamp=batch,
                                   signer=signer)
            from recordstore import RecordStore, BeeBytesStore, FilePointer
            os.makedirs(_home_dir(), exist_ok=True)
            return RecordStore(BeeBytesStore(api, batch),
                               pointer=FilePointer(self.pointer_path()))
        except ImportError as exc:
            missing = exc.name or "requests"
            raise ValueError(
                f"the swarm backend needs an optional dependency that is not "
                f"installed ({missing!r}); install the swarm extra with:  "
                f"pip install -e \".[swarm]\"   "
                f"(that covers both: `requests` for the Bee blob store and "
                f"`swarm-bee` for publishing the latest root to a Swarm feed)"
            ) from exc

    def load(self):
        from ontodag.eager import EagerOntoDAG
        return EagerOntoDAG(self._record_store())

    def save(self, dag):
        dag.commit()

    def describe(self):
        return f"swarm:{self.name}"


def _make_backend(spec):
    if _is_swarm(spec):
        return SwarmBackend(spec[len("swarm:"):])
    return FileBackend(spec)


# --------------------------------------------------------------------------- #
# The in-memory session (the loaded store)
# --------------------------------------------------------------------------- #

class Session:
    def __init__(self, spec):
        self.switch(spec)

    def switch(self, spec):
        self.spec = spec
        self.backend = _make_backend(spec)
        self.dag = self.backend.load()

    def save(self):
        self.backend.save(self.dag)

    def describe(self):
        return self.backend.describe()

    def import_from(self, incoming):
        """Replace the store's contents with `incoming`, in place.

        Mutating the live DAG (rather than rebinding self.dag) keeps a
        EagerOntoDAG's identity, so its commit() still diffs against what it
        hydrated. Works for either backend via the public API alone: clearing
        to the root then merging reproduces `incoming` exactly (remove
        reconnects children upward, never deletes siblings)."""
        for name in list(self.dag.nodes):
            if name != self.dag.root.name and name in self.dag.nodes:
                self.dag.remove(name)
        self.dag.merge(incoming)
        self.save()


# --------------------------------------------------------------------------- #
# Command handlers — (args, session, out); silent on success
# --------------------------------------------------------------------------- #

def _print_dag(dag, out):
    for node in dag.topological_sort():
        children = sorted(n.name for n in node.neighbors)
        if node.name == dag.root.name:
            print(f"{node.name} [root] -> {' '.join(children)}".rstrip(), file=out)
        else:
            parents = sorted(
                p.name for p in node.parents if dag.nodes.get(p.name) is p
            )
            print(f"{node.name} ({' '.join(parents)}) -> {' '.join(children)}".rstrip(),
                  file=out)


def cmd_put(args, session, out):
    session.dag.put(args.item, args.parents, optimized=args.optimized)
    session.save()


def cmd_get(args, session, out):
    # The literal argument `or` separates disjuncts:
    #   odag get Dog Pet or Cat     ->  (Dog AND Pet) OR Cat
    # (`or` is therefore reserved as a category name on the command line;
    # a plain AND query is the one-disjunct case.)
    queries, current = [], []
    for category in args.categories:
        if category == "or":
            queries.append(current)
            current = []
        else:
            current.append(category)
    queries.append(current)
    if any(not query for query in queries):
        raise ValueError("empty query around 'or'")
    result = session.dag.get(queries[0]) if len(queries) == 1 \
        else session.dag.get_any(queries)
    for name in sorted(item.name for item in result):
        print(name, file=out)


def cmd_remove(args, session, out):
    session.dag.remove(args.item)
    session.save()


def cmd_show(args, session, out):
    _print_dag(session.dag, out)


def cmd_list(args, session, out):
    for name in sorted(n for n in session.dag.nodes if n != session.dag.root.name):
        print(name, file=out)


def cmd_merge(args, session, out):
    session.dag.merge(_load(args.file))
    session.save()


def cmd_import(args, session, out):
    session.import_from(_load(args.file))


def cmd_export(args, session, out):
    _save(session.dag, args.file)


def cmd_visualize(args, session, out):
    from ontodag.dag import OntoDAGVisualizer
    base = args.out or os.path.splitext(session.path)[0]
    OntoDAGVisualizer(format=args.format).visualize(session.dag, filename=base)


# Settings `set` can show and change. `store` is the active store spec;
# bee_api/bee_batch configure the Swarm backend's Bee node; bee_signer, when
# present, switches the swarm backend to a signed feed for the latest root
# (recordstore.swarm_store / SwarmFeedPointer) instead of a local file.
_SETTINGS = ("store", "bee_api", "bee_batch", "bee_signer")


def _effective_setting(session, key):
    """The value currently in effect, honoring env/config precedence."""
    if key == "store":
        return session.describe()
    cfg = _read_config()
    if key == "bee_api":
        return os.environ.get("BEE_API") or cfg.get("bee_api") or "http://localhost:1633"
    if key == "bee_batch":
        return os.environ.get("BEE_BATCH") or cfg.get("bee_batch") or ""
    if key == "bee_signer":
        return os.environ.get("BEE_SIGNER") or cfg.get("bee_signer") or ""
    return cfg.get(key, "")


def cmd_set(args, session, out):
    # No key: show every setting. Key but no value: show that one. Both:
    # change it. Displaying on a missing value never errors.
    if not args.key:
        for key in _SETTINGS:
            print(f"{key} = {_effective_setting(session, key)}", file=out)
        return
    if args.key not in _SETTINGS:
        raise ValueError(f"unknown setting: {args.key} "
                         f"(known: {', '.join(_SETTINGS)})")
    if args.value is None:
        print(f"{args.key} = {_effective_setting(session, args.key)}", file=out)
        return
    if args.key == "store":
        spec = _normalize_spec(args.value)
        cfg = _read_config()
        cfg["store"] = spec
        _write_config(cfg)
        session.switch(spec)
    else:
        cfg = _read_config()
        cfg[args.key] = args.value
        _write_config(cfg)


HELP_TEXT = """\
Usage: odag [-f STORE] <command> [args]

Commands:
  put SUB [PARENT...]   add SUB under the PARENT categories (or the root)
  get CAT [CAT...]      print items below all of the CATs, one per line
                        (the literal word `or` separates alternatives:
                        `get Dog Pet or Cat` = (Dog AND Pet) OR Cat)
  remove ITEM           remove ITEM from the store
  show                  print the DAG structure
  list                  print every item name
  merge FILE            merge FILE into the store
  import FILE           replace the store with the contents of FILE
  export FILE           write the store to FILE
  visualize [--out B]   render the DAG to an image
  set [KEY [VALUE]]     show settings, or set one (store, bee_api,
                        bee_batch, bee_signer)
  help                  show this help

With no command odag reads commands from a pipe, or opens an interactive
prompt on a terminal. Files ending in .owl/.omn use OWL/Manchester syntax;
any other path is the native line format.

Typed values: declare a dimension once (put dimension; put
linear-dimension dimension; put weight linear-dimension), then use
parametric terms anywhere a category goes — put parcel 'weight(3kg)',
get 'weight(..5kg)' (quote the parentheses in a shell). Values are
exact integers in tiny base units (3kg is stored as 3000000mg); ranges
are lo..hi with either end open. See docs/DIMENSIONS.md.

A store may also be `swarm:NAME`, persisted on Ethereum Swarm (content on a
Bee node, latest root in ~/.ontodag/NAME.root). `set store swarm:NAME` makes
it the default, so every later command uses Swarm. Needs the swarm extra
(`pip install -e ".[swarm]"`). Configure the node with $BEE_API / $BEE_BATCH
(and $BEE_SIGNER to publish the latest root to a followable Swarm feed
instead of keeping it in a local file)
or `bee_api` / `bee_batch` in ~/.ontodag/config.

The store can also be browsed as a filesystem (paths as category queries,
FUSE-mountable) with `odag-fs`, which shares these settings — see
https://github.com/petfold/ontodag-fs.

Options:
  -f, --store PATH      use PATH (or swarm:NAME) as the store for this run
  -o, --output FILE     write output to FILE instead of stdout (get/show/list)
"""


def cmd_help(args, session, out):
    print(HELP_TEXT, file=out, end="")


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

def build_parser():
    parser = argparse.ArgumentParser(prog="odag", add_help=False,
                                     description="Manipulate an OntoDAG store.")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    p = sub.add_parser("put", add_help=True, help="add an item")
    p.add_argument("item")
    p.add_argument("parents", nargs="*")
    p.add_argument("--optimized", action="store_true",
                   help="infer most-specific parents")
    p.set_defaults(func=cmd_put)

    p = sub.add_parser("get", add_help=True, help="query common subcategories")
    p.add_argument("categories", nargs="+")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_get, stream_output=True)

    p = sub.add_parser("remove", add_help=True, help="remove an item")
    p.add_argument("item")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("show", add_help=True, help="print the DAG structure")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_show, stream_output=True)

    p = sub.add_parser("list", add_help=True, help="print all item names")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_list, stream_output=True)

    p = sub.add_parser("merge", add_help=True, help="merge a file into the store")
    p.add_argument("file")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("import", add_help=True, help="replace the store with a file")
    p.add_argument("file")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("export", add_help=True, help="write the store to a file")
    p.add_argument("file")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("visualize", add_help=True, help="render an image")
    p.add_argument("--out", help="output filename without extension")
    p.add_argument("--format", default="png", choices=["png", "svg", "pdf"])
    p.set_defaults(func=cmd_visualize)

    p = sub.add_parser("set", add_help=True,
                       help="show settings, or change one")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("help", add_help=True, help="show help")
    p.set_defaults(func=cmd_help)

    return parser


PARSER = build_parser()


def dispatch(argv, session):
    """Parse one command line and run it. Returns a process-style exit code."""
    try:
        args = PARSER.parse_args(argv)
    except SystemExit as exc:  # argparse handled --help or a usage error
        return exc.code or 0

    out = sys.stdout
    handle = None
    outpath = getattr(args, "output", None)
    try:
        if outpath and getattr(args, "stream_output", False):
            handle = open(outpath, "w")
            out = handle
        args.func(args, session, out)
        return 0
    except (ValueError, OSError) as exc:
        print(f"odag: {exc}", file=sys.stderr)
        return 1
    finally:
        if handle is not None:
            handle.close()


# --------------------------------------------------------------------------- #
# Interactive and batch (stdin) modes
# --------------------------------------------------------------------------- #

def _run_stream(session, stream, interactive):
    if interactive:
        print(f"Ontodag {__version__} - type help for help")
    while True:
        if interactive:
            try:
                line = input("> ")
            except EOFError:
                print()
                break
        else:
            line = stream.readline()
            if not line:
                break
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            print(f"odag: {exc}", file=sys.stderr)
            continue
        if tokens[0] in ("quit", "exit"):
            break
        dispatch(tokens, session)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    store_override = None
    while argv and argv[0] in ("-f", "--store", "--file"):
        if len(argv) < 2:
            print("odag: option requires a path", file=sys.stderr)
            sys.exit(2)
        store_override = argv[1]
        argv = argv[2:]

    if argv and argv[0] in ("-V", "--version"):
        print(__version__)
        sys.exit(0)
    if argv and argv[0] in ("-h", "--help"):
        sys.stdout.write(HELP_TEXT)
        sys.exit(0)

    session = Session(_resolve_store(store_override))

    if not argv:
        _run_stream(session, sys.stdin, interactive=sys.stdin.isatty())
        sys.exit(0)

    sys.exit(dispatch(argv, session))


if __name__ == "__main__":
    main()
