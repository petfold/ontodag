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
import collections
import errno
import os
import shlex
import socket
import sys

from ontodag.dag import OntoDAG, Item
from ontodag import surface as _surface
from ontodag.dimensions import REGISTRY_VERSION

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


def _default_store_path():
    """The zero-dependency default store: a native text file under the home
    dir. Named separately from `_resolve_store` because error messages offer
    it as the fallback when a configured Swarm store can't be opened."""
    return os.path.join(_home_dir(), "store.od")


# --------------------------------------------------------------------------- #
# Settings: one table, one precedence rule
# --------------------------------------------------------------------------- #
#
# Every setting is settable four ways and resolved the same way:
#
#     command-line flag  >  environment variable  >  config file  >  default
#
# The first two are per-invocation; the config file (written by `set`) is the
# durable one. `auto` is a real value, not a missing one: it means "decide from
# whether output is a terminal", which is what makes `odag get | odag put`
# round-trip while an interactive session stays readable.

_Setting = collections.namedtuple("_Setting", "env default flag doc")

_SETTINGS = {
    "store": _Setting(
        "ONTODAG_STORE", "", "-f PATH",
        "active store: a file path or a swarm:NAME URI"),
    "bee_api": _Setting(
        "BEE_API", "http://localhost:1633", "--bee-api URL",
        "Bee node API endpoint, for swarm: stores"),
    "bee_batch": _Setting(
        "BEE_BATCH", "", "--bee-batch ID",
        "postage batch to pay for Swarm writes"),
    "bee_signer": _Setting(
        "BEE_SIGNER", "", "--bee-signer KEY",
        "private key; when set, the latest root lives in a signed feed"),
    "render": _Setting(
        "ONTODAG_SURFACE", "auto", "--render / --raw",
        "readable output (auto = on at a terminal, off in a pipe)"),
    "limit": _Setting(
        "ONTODAG_LIMIT", "auto", "-n N",
        "max result lines (auto = 50 at a terminal, all in a pipe; 0 = all)"),
}

# Settings given as flags on this invocation. Global flags are recorded here by
# main(); per-command flags stay on `args` and outrank these (the closer the
# flag is to the command, the more specific the intent).
_OVERRIDES = {}


def _configured(key, flag=None):
    """The configured value of a setting, by the one precedence rule above.

    `flag` is a per-command flag value, or None if the command has none.
    Empty strings count as unset, so `BEE_BATCH=` does not shadow config."""
    if flag:
        return flag
    if _OVERRIDES.get(key):
        return _OVERRIDES[key]
    env = os.environ.get(_SETTINGS[key].env)
    if env:
        return env
    cfg = _read_config()
    if cfg.get(key):
        return cfg[key]
    return _SETTINGS[key].default


def _resolve_store(override=None):
    """The active store spec. `store`'s only peculiarity is that its default
    is computed (a path under the home dir) rather than a constant."""
    spec = _configured("store", override)
    return _normalize_spec(spec) if spec else _default_store_path()


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


_UNREACHABLE_ERRNOS = {
    errno.ECONNREFUSED, errno.EHOSTUNREACH, errno.ENETUNREACH,
    errno.ENETDOWN, errno.ETIMEDOUT,
}

# Connection failures reach us wrapped by whichever HTTP client ran: `requests`
# for the blob store, or aiohttp under swarmfs's postage-stamp selection. Both
# subclass OSError but neither subclasses the builtin ConnectionError, so match
# the cause chain (which does bottom out in a real ConnectionRefusedError) and
# fall back to type names for clients that break the chain.
_UNREACHABLE_NAMES = {
    "ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout",
    "ClientConnectorError", "ServerTimeoutError", "MaxRetryError",
    "NewConnectionError",
}


def _is_unreachable(exc):
    """True when `exc` means "no answer from the node", as opposed to the node
    answering with an error (no usable stamp, HTTP 4xx, bad reference)."""
    for _ in range(10):  # bounded: cause chains can be cyclic
        if exc is None:
            return False
        if isinstance(exc, (ConnectionError, socket.gaierror, TimeoutError)):
            return True
        if getattr(exc, "errno", None) in _UNREACHABLE_ERRNOS:
            return True
        if type(exc).__name__ in _UNREACHABLE_NAMES:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def _swarm_open_error(name, api, exc):
    """A ValueError whose message tells the user what to do next.

    Deliberately *not* a silent fallback to the local store: writing to a
    different store than the configured one would let a local file and the
    Swarm store diverge with no signal about which is authoritative. Offer
    the fallback, never take it unasked. Starting the node is likewise the
    user's call — a query command must not spawn a syncing daemon.
    """
    local = _default_store_path()
    if _is_unreachable(exc):
        head = (f"cannot reach the Bee node at {api}, needed by store "
                f"'swarm:{name}' ({exc})\n"
                f"  * start your Bee node, then run this again")
    else:
        head = (f"cannot open swarm store '{name}' via {api}: {exc}\n"
                f"  * check the node and its postage batch "
                f"(odag set shows bee_api / bee_batch)")
    return ValueError(
        f"{head}\n"
        f"  * or work locally for one command:  odag -f {local} ...\n"
        f"  * or switch back to local storage:  odag set store {local}\n"
        f"    (local is the default and needs no node: one text file, "
        f"nothing published)"
    )


class SwarmBackend:
    def __init__(self, name, store_factory=None, index_store_factory=None,
                 prov_store_factory=None):
        if not name:
            raise ValueError("swarm store needs a name, e.g. swarm:mydag")
        if os.sep in name or (os.altsep and os.altsep in name) or name == "..":
            raise ValueError(f"invalid swarm store name: {name!r}")
        self.name = name
        # Injection seam: tests pass a factory returning a RecordStore over an
        # in-memory bytes store, exercising the whole wiring without a node.
        self._store_factory = store_factory
        self._index_store_factory = index_store_factory
        self._prov_store_factory = prov_store_factory

    def provenance_record_store(self):
        """The per-writer provenance store (docs/PROVENANCE.md): signed
        speech acts about claims, in a SEPARATE record store under the
        sibling name NAME-prov — beside the knowledge store, never inside
        it, so identical knowledge keeps identical roots whoever asserted
        it. Same wiring as the data store (and as NAME-index)."""
        if self._prov_store_factory is not None:
            return self._prov_store_factory()
        return SwarmBackend(self.name + "-prov")._record_store()

    def index_record_store(self):
        """The SEPARATE record store for published cone summaries (the
        `odag index` command): same wiring as the data store under the
        sibling name NAME-index, so the derived index never touches the
        ontology's own root (docs/DIMENSIONS.md-era purity rule; see
        ontodag.cones)."""
        if self._index_store_factory is not None:
            return self._index_store_factory()
        return SwarmBackend(self.name + "-index")._record_store()

    def pointer_path(self):
        return os.path.join(_home_dir(), self.name + ".root")

    def _record_store(self):
        api = _configured("bee_api")
        # "auto" (ask the node for a usable batch) is this call site's default,
        # not the setting's: `set bee_batch` showing "auto" would misreport an
        # unconfigured batch as a configured one.
        batch = _configured("bee_batch") or "auto"
        signer = _configured("bee_signer")
        try:
            if self._store_factory is not None:
                return self._store_factory()
            # BeeBytesStore imports `requests` in its constructor, so a missing
            # optional dependency surfaces here rather than at module import.
            # It also resolves batch="auto" against the node, so this line is
            # the first one that needs Bee to be up.
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
                f"(that covers all three: `requests` for the Bee blob store, "
                f"`swarmfs` for resolving bee_batch=auto against the node, and "
                f"`swarm-bee` for publishing the latest root to a Swarm feed)"
            ) from exc
        except OSError as exc:
            raise _swarm_open_error(self.name, api, exc) from exc

    def load(self):
        from ontodag.eager import EagerOntoDAG
        store = self._record_store()
        try:
            # Hydration reads every record, so a node that dies between
            # opening the store and reading it lands here, not above.
            return EagerOntoDAG(store)
        except OSError as exc:
            raise _swarm_open_error(self.name, _configured("bee_api"),
                                    exc) from exc

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
        # Atomic: build and load first, assign only once nothing can fail. A
        # store that won't open (node down) must leave the session on the one
        # it already had, not half-switched to a backend whose load failed.
        backend = _make_backend(spec)
        dag = backend.load()
        self.spec, self.backend, self.dag = spec, backend, dag

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
# The two output settings that default to `auto` (SURFACE_LAYER.md §7, decided
# 2026-08-01, extended to `limit` 2026-08-02): a terminal gets output meant for
# a person — readable spellings, and only as many lines as are worth reading —
# while anything else gets the complete canonical answer, so `odag get | wc -l`
# counts right and `odag get | odag put` round-trips. Both are OUTPUT-only:
# input elaboration and the query itself never depend on where stdout goes,
# and the tty test is on the actual stream, so `-o FILE` gets canonical bytes.
# --------------------------------------------------------------------------- #

_TTY_LIMIT = 50   # generous enough that ordinary stores never notice it


def _isatty(out):
    try:
        return out.isatty()
    except (AttributeError, ValueError):
        return False


def _want_render(args, out):
    flag = getattr(args, "render_mode", None)
    if flag is not None:
        return flag
    value = _configured("render").strip().lower()
    if value in ("0", "off", "raw", "false", "no"):
        return False
    if value in ("1", "on", "render", "true", "yes"):
        return True
    return _isatty(out)


def _want_limit(args, out):
    """How many result lines to print; 0 means all of them.

    A cap exists so that an interactive query cannot flood the terminal —
    which is what makes the empty query (`odag get`, everything) a safe thing
    to type. It is a DISPLAY cap only: the query itself is always complete,
    the withheld count is always reported, and a pipe is never capped."""
    flag = getattr(args, "limit", None)
    value = _configured("limit", flag)
    if isinstance(value, str):
        value = value.strip().lower()
        if value in ("auto", ""):
            return _TTY_LIMIT if _isatty(out) else 0
        if value in ("all", "none", "off"):
            return 0
        try:
            value = int(value)
        except ValueError:
            raise ValueError(
                f"limit must be a number, `all` or `auto`, not {value!r}"
            ) from None
    return max(0, int(value))


def _namer(args, session, out):
    """The name formatter this command's output should use: identity for
    canonical output, the surface renderer for a terminal. Sorting always
    happens on canonical names (the identity); rendering is display-only."""
    if _want_render(args, out):
        return lambda name: _surface.render(name, session.dag)
    return lambda name: name


def _print_names(names, args, session, out):
    """Print result names one per line under the display cap.

    Sorting is on canonical names — the identity — so the prefix a cap keeps
    is the same whether or not output is being rendered. The withheld count
    goes to stderr: it is a message to the person, never part of the answer,
    so it cannot contaminate a pipe even when `-n` was asked for explicitly."""
    fmt = _namer(args, session, out)
    names = sorted(names)
    limit = _want_limit(args, out)
    shown = names[:limit] if limit else names
    for name in shown:
        print(fmt(name), file=out)
    withheld = len(names) - len(shown)
    if withheld:
        print(f"odag: {withheld} more not shown "
              f"(-n 0 for all, or `odag count` for the total)",
              file=sys.stderr)


# --------------------------------------------------------------------------- #
# Command handlers — (args, session, out); silent on success
# --------------------------------------------------------------------------- #

def _print_dag(dag, out, fmt=lambda name: name):
    for node in dag.topological_sort():
        children = sorted(n.name for n in node.neighbors)
        shown = [fmt(c) for c in children]
        if node.name == dag.root.name:
            print(f"{node.name} [root] -> {' '.join(shown)}".rstrip(), file=out)
        else:
            parents = sorted(
                p.name for p in node.parents if dag.nodes.get(p.name) is p
            )
            print(f"{fmt(node.name)} ({' '.join(fmt(p) for p in parents)}) "
                  f"-> {' '.join(shown)}".rstrip(), file=out)


def cmd_put(args, session, out):
    session.dag.put(args.item, args.parents, optimized=args.optimized)
    session.save()


def _query(categories, dag):
    """Run a command-line query and return the matching items.

    The literal argument `or` separates disjuncts:
        odag get Dog Pet or Cat     ->  (Dog AND Pet) OR Cat
    (`or` is therefore reserved as a category name on the command line;
    a plain AND query is the one-disjunct case.)

    No categories at all is the EMPTY query, which is everything — the
    intersection of no constraints (see `OntoDAG.get`). A *dangling* `or`
    still fails: at that point the empty disjunct is a typo, not a request
    for the universe, and taking it literally would silently turn a narrow
    query into a full dump."""
    queries, current = [], []
    for category in categories:
        if category == "or":
            queries.append(current)
            current = []
        else:
            current.append(category)
    queries.append(current)
    if len(queries) > 1 and any(not query for query in queries):
        raise ValueError("empty query around 'or'")
    if len(queries) == 1:
        return dag.get(queries[0])
    return dag.get_any(queries)


def cmd_get(args, session, out):
    result = _query(args.categories, session.dag)
    _print_names((item.name for item in result), args, session, out)


def cmd_count(args, session, out):
    # How many, and nothing else. Deliberately its own command rather than a
    # flag on `get`: it is the complete answer to "how big is this" — never
    # capped, never rendered — for exactly the cases where printing the answer
    # is what you are trying to avoid.
    print(len(_query(args.categories, session.dag)), file=out)


def cmd_below(args, session, out):
    # A Unix-style boolean, git merge-base --is-ancestor style: prints one
    # parseable word (the interactive prompt has no exit codes) AND exits
    # 0 for true / 1 for false, so `odag below A B && ...` just works.
    # Unknown names are false, not errors (fail-closed, like get).
    result = session.dag.is_below(args.sub, args.sup)
    print("true" if result else "false", file=out)
    return 0 if result else 1


def cmd_index(args, session, out):
    # Publish cone summaries next to the store (CONE_SUMMARIES_PLAN step E):
    # a derived index in a SEPARATE record store, so the data root is
    # untouched. Prints the manifest pair — hand both roots to lazy readers.
    backend = session.backend
    if not isinstance(backend, SwarmBackend):
        raise ValueError(
            "index needs a record-store backend (a swarm:NAME store); "
            "file stores are loaded whole and never benefit from one")
    from ontodag.cones import build_index

    data_root = session.dag.store.root
    if not data_root:
        raise ValueError("nothing committed yet — put something first")
    index_root = build_index(session.dag, backend.index_record_store(),
                             data_root, threshold=args.threshold)
    print(f"data  {data_root}", file=out)
    print(f"index {index_root}", file=out)


def cmd_remove(args, session, out):
    session.dag.remove(args.item)
    session.save()


def cmd_show(args, session, out):
    _print_dag(session.dag, out, fmt=_namer(args, session, out))


def cmd_list(args, session, out):
    # `list` is the empty query under a discoverable name — one code path, so
    # `odag list`, `odag get` and `odag get '*'` cannot drift apart.
    _print_names((item.name for item in session.dag.get([])),
                 args, session, out)


def cmd_prelude(args, session, out):
    # The declaration-ceremony answer (SURFACE_LAYER.md §9.2): adopt the
    # standard dimension declarations by an explicit, idempotent MERGE —
    # never as a silent default of a fresh store, so the root change is
    # a visible, versioned act of adoption.
    from ontodag.prelude import DECLARATIONS, PRELUDE_VERSION, prelude_dag
    if args.show:
        print(f"# ontodag prelude v{PRELUDE_VERSION}", file=out)
        for name, parents in DECLARATIONS:
            print(" ".join([name, *parents]), file=out)
        return
    session.dag.merge(prelude_dag())
    session.save()


def cmd_pack(args, session, out):
    # Unit packs (UNITS.md §7): graph-declared vocabulary adopted by an
    # explicit, idempotent merge — the prelude pattern, for units. The
    # vocabulary then travels inside the store itself.
    from ontodag.packs import PACKS, pack_dag
    if not args.name:
        for name in sorted(PACKS):
            version, declarations = PACKS[name]
            print(f"{name} v{version} ({len(declarations)} declarations)",
                  file=out)
        return
    if args.show:
        version, declarations = PACKS.get(args.name, (None, None))
        if declarations is None:
            raise ValueError(f"unknown pack {args.name!r} "
                             f"(available: {', '.join(sorted(PACKS))})")
        print(f"# ontodag pack {args.name} v{version}", file=out)
        for declaration in declarations:
            print(declaration, file=out)
        return
    session.dag.merge(pack_dag(args.name))
    session.save()


def cmd_canon(args, session, out):
    # The inspectable mapping (SURFACE_LAYER.md §7): what does this surface
    # term elaborate to? Output is always canonical — that is the command's
    # whole point — so it ignores the render mode. A malformed parameter of
    # a declared head raises the core's own teaching error (exit 1). With no
    # term it prints the surface and registry versions (§9.5: informational,
    # never stored).
    if not args.term:
        print(f"surface {_surface.SURFACE_VERSION}", file=out)
        print(f"registry {REGISTRY_VERSION}", file=out)
        return
    print(_surface.elaborate(args.term, session.dag), file=out)


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


def _effective_setting(session, key):
    """The value currently in effect, by the settings table's one rule.

    `store` is the exception worth having: what is in effect is the store this
    session actually opened, which is not the configured spec if a `set store`
    was saved but could not be switched to."""
    if key == "store":
        return session.describe()
    return _configured(key)


def cmd_set(args, session, out):
    # No key: show every setting. Key but no value: show that one. Both:
    # change it — writing to the config file, which is the durable layer;
    # a flag or an environment variable still outranks it for that run.
    # Displaying on a missing value never errors.
    if not args.key:
        for key in sorted(_SETTINGS):
            print(f"{key} = {_effective_setting(session, key)}", file=out)
        return
    if args.key not in _SETTINGS:
        raise ValueError(f"unknown setting: {args.key} "
                         f"(known: {', '.join(sorted(_SETTINGS))})")
    if args.value is None:
        print(f"{args.key} = {_effective_setting(session, args.key)}", file=out)
        return
    if args.key == "store":
        spec = _normalize_spec(args.value)
        cfg = _read_config()
        cfg["store"] = spec
        _write_config(cfg)
        try:
            session.switch(spec)
        except (ValueError, OSError) as exc:
            # The setting is saved regardless: configuring a store you can't
            # reach yet is legitimate (start the node afterwards). Say so, so
            # the failure doesn't read as "nothing happened".
            raise ValueError(
                f"{exc}\n  the `store` setting was still saved as {spec}; "
                f"this session keeps using {session.spec}"
            ) from exc
    else:
        # Validate now, not at the next command that reads it: a setting that
        # only fails later is a setting you debug in the wrong place.
        if args.key == "limit":
            _want_limit(argparse.Namespace(limit=args.value), out)
        cfg = _read_config()
        cfg[args.key] = args.value
        _write_config(cfg)


HELP_TEXT = """\
Usage: odag [-f STORE] <command> [args]

Commands:
  put SUB [PARENT...]   add SUB under the PARENT categories (or the root)
  get [CAT...]          print items below all of the CATs, one per line
                        (the literal word `or` separates alternatives:
                        `get Dog Pet or Cat` = (Dog AND Pet) OR Cat).
                        With no CAT at all the query is unconstrained, so
                        it prints everything — the same as `list`
  count [CAT...]        how many items that same query matches: one number,
                        complete, never capped
  below SUB SUP       does SUB fit within SUP? prints true/false and
                        exits 0/1 (grep-style), so `odag below A B && ...`
                        works; `?` is a synonym at the interactive prompt.
                        Works on typed values from the names alone:
                        below 'weight(3kg)' 'weight(..5kg)' -> true
  remove ITEM           remove ITEM from the store
  show                  print the DAG structure
  list                  print every item name (the empty query, named)
  merge FILE            merge FILE into the store
  import FILE           replace the store with the contents of FILE
  export FILE           write the store to FILE
  visualize [--out B]   render the DAG to an image
  index [--threshold N] publish cone summaries for a swarm: store into the
                        sibling NAME-index store (a derived index: the data
                        root is untouched); prints both roots for readers
  canon [TERM]          print TERM's canonical form — what would actually be
                        stored (`canon 'time(2026)'` shows the timestamp
                        range); with no TERM, the surface/registry versions
  prelude [--show]      adopt the standard dimension declarations (weight,
                        time, geo, size, ...) in one idempotent merge;
                        --show prints them instead
  pack [NAME] [--show]  list unit packs, or adopt one (crypto-majors,
                        stablecoins, fiat-iso4217) — vocabulary as graph
                        data, no new release needed; travels with the store
  set [KEY [VALUE]]     show settings, or set one durably (store, bee_api,
                        bee_batch, bee_signer, render, limit)
  help                  show this help

With no command odag reads commands from a pipe, or opens an interactive
prompt on a terminal. Files ending in .owl/.omn use OWL/Manchester syntax;
any other path is the native line format.

Typed values: run `odag prelude` once (or declare by hand: put dimension;
put linear-dimension dimension; put weight linear-dimension), then use
parametric terms anywhere a category goes — put parcel 'weight(3kg)',
get 'weight(..5kg)' (quote the parentheses in a shell). Values are
exact rationals of the SI anchor unit (500g is stored as 1/2kg; any
exact unit works, psi to shaku — see docs/UNITS.md); ranges
are lo..hi with either end open. For dates use calendar-dimension
instead of linear-dimension: then 'time(2026)' is the year,
'time(2026-08)' the month, 'time(2026-08-15)' the day, and each
contains the finer ones. See docs/DIMENSIONS.md.

Output for people vs output for programs: on a terminal, names print in
friendly spellings — weight(3kg), time(2026) — and long answers stop at 50
lines with a note on stderr saying how many were withheld. Pipes, files and
-o get the complete answer in exact canonical bytes, so `odag get ... | odag`
round-trips and `odag get ... | wc -l` counts right. Override with
--render / --raw and -n N (-n 0 for all). `canon TERM` shows the exact
stored form of any spelling. See docs/SURFACE_LAYER.md.

Settings: store, bee_api, bee_batch, bee_signer, render, limit. Each can be
given four ways, and the first that is present wins:

  flag  >  environment  >  config file (`set`)  >  default

so a flag is for one command, an environment variable for one shell, and
`odag set KEY VALUE` is the durable one (it writes ~/.ontodag/config).
`odag set` with no arguments prints what is currently in effect.

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

Options (before the command; they apply to every command in a batch):
  -f, --store PATH      use PATH (or swarm:NAME) as the store for this run
  -n, --limit N         show at most N results (0 for all)
  --render, --raw       force friendly or canonical names
  --bee-api URL         Bee node endpoint, for swarm: stores
  --bee-batch ID        postage batch to pay for Swarm writes
  --bee-signer KEY      publish the latest root to a signed Swarm feed

Per command:
  -o, --output FILE     write output to FILE instead of stdout (get/show/list)
  -n, --limit N         as above, for this command only (get/list)
  --render, --raw       as above, for this command only
"""


def cmd_help(args, session, out):
    print(HELP_TEXT, file=out, end="")


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

def _add_surface_flags(p):
    """--render/--raw on every command whose stdout carries names. The pair
    overrides $ONTODAG_SURFACE and the tty default (§7 precedence)."""
    group = p.add_mutually_exclusive_group()
    group.add_argument("--render", dest="render_mode", action="store_const",
                       const=True, help="friendly names even when piped")
    group.add_argument("--raw", dest="render_mode", action="store_const",
                       const=False, help="canonical names even on a terminal")
    p.set_defaults(render_mode=None)


def _add_limit_flag(p):
    """-n on every command that prints a list of names. Overrides
    $ONTODAG_LIMIT, the `limit` setting and the tty default; 0 means all."""
    p.add_argument("-n", "--limit", metavar="N",
                   help="show at most N results (0 for all)")


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
    p.add_argument("categories", nargs="*")
    p.add_argument("-o", "--output")
    _add_surface_flags(p)
    _add_limit_flag(p)
    p.set_defaults(func=cmd_get, stream_output=True)

    p = sub.add_parser("count", add_help=True,
                       help="how many items a query matches")
    p.add_argument("categories", nargs="*")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_count, stream_output=True)

    p = sub.add_parser("below", add_help=True,
                       help="test whether SUB fits within SUP (exit 0/1)")
    p.add_argument("sub")
    p.add_argument("sup")
    p.set_defaults(func=cmd_below, stream_output=True)

    p = sub.add_parser("index", add_help=True,
                       help="publish cone summaries for a swarm store")
    p.add_argument("--threshold", type=int, default=64,
                   help="summarize categories with at least this many "
                        "descendants (default 64)")
    p.set_defaults(func=cmd_index, stream_output=True)

    p = sub.add_parser("remove", add_help=True, help="remove an item")
    p.add_argument("item")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("show", add_help=True, help="print the DAG structure")
    p.add_argument("-o", "--output")
    _add_surface_flags(p)
    p.set_defaults(func=cmd_show, stream_output=True)

    p = sub.add_parser("list", add_help=True, help="print all item names")
    p.add_argument("-o", "--output")
    _add_surface_flags(p)
    _add_limit_flag(p)
    p.set_defaults(func=cmd_list, stream_output=True)

    p = sub.add_parser("pack", add_help=True,
                       help="list unit packs, or adopt one by merge "
                            "(--show to inspect)")
    p.add_argument("name", nargs="?")
    p.add_argument("--show", action="store_true",
                   help="print the pack instead of merging it")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_pack, stream_output=True)

    p = sub.add_parser("prelude", add_help=True,
                       help="adopt the standard dimension declarations "
                            "(an idempotent merge; --show to inspect)")
    p.add_argument("--show", action="store_true",
                   help="print the prelude instead of merging it")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_prelude, stream_output=True)

    p = sub.add_parser("canon", add_help=True,
                       help="print a term's canonical form "
                            "(no term: surface/registry versions)")
    p.add_argument("term", nargs="?")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_canon, stream_output=True)

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
    if argv and argv[0] == "?":
        # Interactive-prompt sugar for the subsumption test (`? Spaniel
        # Animal`); works from a shell too if you quote the glob character.
        argv = ["below"] + list(argv[1:])
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
        # A command may return an int to set the exit code (below's
        # true/false is 0/1, grep-style); None keeps the usual 0.
        code = args.func(args, session, out)
        return code or 0
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

    # Leading global options: they apply to every command this invocation
    # runs, including a whole stdin batch, and they are the flag layer of the
    # settings table — one option per setting, no exceptions.
    _OVERRIDES.clear()
    valued = {"-f": "store", "--store": "store", "--file": "store",
              "--bee-api": "bee_api", "--bee-batch": "bee_batch",
              "--bee-signer": "bee_signer", "-n": "limit", "--limit": "limit"}
    while argv and (argv[0] in valued or argv[0] in ("--raw", "--render")):
        if argv[0] in ("--raw", "--render"):
            _OVERRIDES["render"] = "on" if argv[0] == "--render" else "off"
            argv = argv[1:]
            continue
        if len(argv) < 2:
            print(f"odag: {argv[0]} requires a value", file=sys.stderr)
            sys.exit(2)
        _OVERRIDES[valued[argv[0]]] = argv[1]
        argv = argv[2:]

    if argv and argv[0] in ("-V", "--version"):
        print(__version__)
        sys.exit(0)
    if argv and argv[0] in ("-h", "--help"):
        sys.stdout.write(HELP_TEXT)
        sys.exit(0)

    # Opening the store is I/O like any command, and for a swarm: spec it is
    # network I/O — so it gets the same treatment dispatch() gives commands:
    # one line on stderr and a non-zero exit, never a traceback.
    try:
        session = Session(_resolve_store())
    except (ValueError, OSError) as exc:
        print(f"odag: {exc}", file=sys.stderr)
        sys.exit(1)

    if not argv:
        _run_stream(session, sys.stdin, interactive=sys.stdin.isatty())
        sys.exit(0)

    sys.exit(dispatch(argv, session))


if __name__ == "__main__":
    main()
