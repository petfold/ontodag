"""Where odag's output and notes go.

Commands already take `out`; the *notes* (what a move left contested, how
many lines were withheld, a store that committed locally but has not synced)
went straight to `sys.stderr`, which is fine for a process and wrong for any
embedder — a web console has to capture both streams to show the teaching
errors that are half the value of the CLI. `dispatch(argv, session, out=,
err=)` binds these; everything else asks `_out()`/`_err()`.

ContextVars rather than module globals or `redirect_stdout`: both of those are
process-wide, so under a threaded server one request would swallow another's
output. A ContextVar is per-thread by default, so two concurrent `dispatch`
calls cannot see each other's streams.

Its own module (2026-10-09) because the store backends write notes too, and
they no longer live in the CLI module (`ontodag.stores`).
"""

import contextvars
import sys

_OUT = contextvars.ContextVar("ontodag_out", default=None)
_ERR = contextvars.ContextVar("ontodag_err", default=None)


def _out():
    stream = _OUT.get()
    return sys.stdout if stream is None else stream


def _err():
    stream = _ERR.get()
    return sys.stderr if stream is None else stream
