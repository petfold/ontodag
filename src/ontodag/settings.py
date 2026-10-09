"""Settings: one table, one precedence rule — what `odag set` shows and changes.

Every tool that shares odag's stores reads its settings here: `odag` itself,
`odag-mcp`, the web app, and the sister projects that open odag's stores
(loopmarket's `loop`, ontodag-fs's `odag-fs`). Until 2026-10-09 they reached
into the CLI module's private names for this; those names are kept as
aliases of the ones below (`ontodag.__main__._configured` and the rest) for
the projects still using them.

Every setting is settable four ways and resolved the same way:

    command-line flag  >  environment variable  >  config file  >  default

The first two are per-invocation; the config file (written by `odag set`, or
by `write_config`) is the durable one. `auto` is a real value, not a missing
one: it means "decide from whether output is a terminal", which is what makes
`odag get | odag put` round-trip while an interactive session stays readable.

The flag layer is `OVERRIDES`: a tool that takes one of these settings as its
own command-line flag puts the value there, so every store it opens sees it
(loopmarket's `--bee-api` reaches the Bee node odag's backends talk to).

Standard library only, like the core.
"""

import collections
import os

__all__ = [
    "Setting", "SETTINGS", "OVERRIDES", "configured",
    "home_dir", "config_path", "read_config", "write_config",
    "normalize_spec", "default_store_path", "resolve_store", "overlay_specs",
]


# --------------------------------------------------------------------------- #
# Home directory and the config file
# --------------------------------------------------------------------------- #

def home_dir():
    """odag's home: `$ONTODAG_HOME`, else `~/.ontodag`."""
    return os.environ.get("ONTODAG_HOME") or os.path.join(
        os.path.expanduser("~"), ".ontodag"
    )


def config_path():
    """The config file `odag set` writes: `config` in the home directory."""
    return os.path.join(home_dir(), "config")


def read_config(path=None):
    """The config file as a dict (`key = value` lines; `#` comments and
    malformed lines skipped). Empty when there is no file. `path` reads
    another file in the same format instead: a sister tool keeping its own
    config beside odag's (loopmarket's `~/.loopmarket/config`) reads and
    writes it here rather than copying the format."""
    cfg = {}
    path = path or config_path()
    if not os.path.exists(path):
        return cfg
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            cfg[key.strip()] = value.strip()
    return cfg


def write_config(cfg, path=None):
    """Write the config file (or `path`, another file in its format, see
    `read_config`), readable only by its owner.

    It can hold `bee_signer` — a private key that can publish to your feed —
    and was previously written with default permissions, which under a typical
    umask left a key group- and world-readable. O_CREAT's mode covers a file
    this call creates; the explicit chmod also repairs one written before this
    (or by an older version), which is the case that actually matters since
    the leak is already on disk by then.

    On Windows neither call means anything — `chmod` there toggles the
    read-only attribute and there are no permission bits to set — so the
    file's privacy is whatever the profile directory's ACL gives it. Stated
    in USER_GUIDE §2 rather than papered over: the honest advice on that
    platform is to keep the key in `$BEE_SIGNER`."""
    path = path or config_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), mode=0o700,
                exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for key in sorted(cfg):
            fh.write(f"{key} = {cfg[key]}\n")
    os.chmod(path, 0o600)


# --------------------------------------------------------------------------- #
# Store specs
# --------------------------------------------------------------------------- #

def _abspath(path):
    return os.path.abspath(os.path.expanduser(path))


def _is_swarm(spec):
    return spec.startswith("swarm:")


def _is_record_store(spec):
    """`rs:PATH` — a content-addressed record store on local disk."""
    return spec.startswith("rs:")


def normalize_spec(spec):
    """A store spec is a `swarm:NAME` URI, an `rs:PATH` record store, or a
    filesystem path.

    Swarm specs are kept verbatim; file paths are made absolute so a spec
    saved to config resolves the same from any working directory, and an
    `rs:` path is absolutised inside its prefix for the same reason."""
    if _is_swarm(spec):
        return spec
    if _is_record_store(spec):
        return "rs:" + _abspath(spec[len("rs:"):])
    return _abspath(spec)


def default_store_path():
    """The zero-dependency default store: a native text file under the home
    dir. Named separately from `resolve_store` because error messages offer
    it as the fallback when a configured Swarm store can't be opened."""
    return os.path.join(home_dir(), "store.od")


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #

# `secret` marks a value that must not be printed back: `odag set` is the
# routine "what is configured?" command, so anything it echoes lands in
# scrollback, screen shares and captured terminal output.
Setting = collections.namedtuple("Setting", "env default flag doc secret")
Setting.__new__.__defaults__ = (False,)

SETTINGS = {
    "store": Setting(
        "ONTODAG_STORE", "", "-f PATH",
        "active store: a file path or a swarm:NAME URI"),
    "bee_api": Setting(
        "BEE_API", "http://localhost:1633", "--bee-api URL",
        "Bee node API endpoint, for swarm: stores"),
    "bee_batch": Setting(
        "BEE_BATCH", "", "--bee-batch ID",
        "postage batch to pay for Swarm writes"),
    "bee_signer": Setting(
        "BEE_SIGNER", "", "--bee-signer KEY",
        "private key; when set, the latest root lives in a signed feed",
        secret=True),
    "store_key": Setting(
        "ONTODAG_STORE_KEY", "", "--store-key SECRET",
        "encryption secret for rs: stores (any string; a NEW store is "
        "created encrypted iff this is set — existing stores keep "
        "whatever they are)",
        secret=True),
    "overlays": Setting(
        "ONTODAG_OVERLAYS", "", "--overlay SPECS",
        "read-only stores merged into every answer (comma-separated store "
        "specs); writes, exports and excerpts never include them"),
    "render": Setting(
        "ONTODAG_SURFACE", "auto", "--render / --raw",
        "readable output (auto = on at a terminal, off in a pipe)"),
    "limit": Setting(
        "ONTODAG_LIMIT", "auto", "-n N",
        "max result lines (auto = 50 at a terminal, all in a pipe; 0 = all)"),
}

# Settings given as flags on this invocation. odag's main() records its
# global flags here (and two per-invocation values that are not settings:
# `message`, the label for what this run commits, and `as_of`, the version
# it reads); per-command flags stay on the command's arguments and outrank
# these — the closer the flag is to the command, the more specific the
# intent. One dict for the whole process, mutated in place, never rebound.
OVERRIDES = {}


def configured(key, flag=None):
    """The value in effect for setting `key`, by the one precedence rule.

    `flag` is a per-command flag value, or None if the command has none.
    Empty strings count as unset, so `BEE_BATCH=` does not shadow config.
    An unknown key raises KeyError."""
    if flag:
        return flag
    if OVERRIDES.get(key):
        return OVERRIDES[key]
    env = os.environ.get(SETTINGS[key].env)
    if env:
        return env
    cfg = read_config()
    if cfg.get(key):
        return cfg[key]
    return SETTINGS[key].default


def resolve_store(spec=None):
    """The active store spec, normalized: `spec` when given, else the
    configured `store` by the precedence rule, else the default store.
    `store`'s only peculiarity is that its default is computed (a path
    under the home dir) rather than a constant."""
    spec = configured("store", spec)
    return normalize_spec(spec) if spec else default_store_path()


def overlay_specs():
    """The configured overlay store specs, in order. Comma-separated because
    the settings table holds one string per setting; a comma cannot start a
    store spec in any backend's grammar, so the join is unambiguous."""
    value = configured("overlays")
    if not value:
        return []
    return [normalize_spec(spec.strip())
            for spec in value.split(",") if spec.strip()]
