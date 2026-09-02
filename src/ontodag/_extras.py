"""Turn a missing optional dependency into an instruction.

The base install has no third-party dependencies (see `pyproject.toml`), so
every optional feature reaches its dependency lazily and can fail. What it
must not do is fail with a bare ``ModuleNotFoundError``: that names a
*package*, when what the reader needs is the pip command — and, for some of
them, the fact that a system binary is also involved.

One helper rather than a message per call site, so the wording stays
consistent and adding a feature does not mean inventing a new phrasing.
"""

import importlib


class MissingExtra(ImportError):
    """An optional dependency is not installed — a thing to *do*, not a bug.

    Its own class so the CLI can turn it into a one-line message and a
    non-zero exit, the way it treats every other user-facing failure, while
    a genuine ImportError (a broken install, a typo in our own imports)
    still gets the traceback it deserves.
    """


# What each extra is for, in the words someone reading an error would want.
EXTRAS = {
    "viz": "rendering",
    "owl": "OWL and Manchester import/export",
    "store": "persisted, content-addressed stores",
    "crypto": "encrypted stores",
    "act": "category-based access control",
    "swarm": "storing a DAG on Ethereum Swarm",
    "web": "the web app and REST API",
}


def require(package, extra, what, hint=None):
    """Import `package`, or raise an ImportError naming the extra to install.

    `what` is the feature in the caller's terms ("certificates", "the agent
    surface"), because the reader is trying to do a thing, not to satisfy a
    dependency graph. `hint` adds anything the pip command alone won't fix.
    """
    try:
        return importlib.import_module(package)
    except ImportError as exc:
        message = f'{what} needs the `{extra}` extra: pip install "ontodag[{extra}]"'
        if hint:
            message = f"{message}\n{hint}"
        raise MissingExtra(message) from exc
