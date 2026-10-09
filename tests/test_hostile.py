"""Hostile input at ontodag's untrusted boundaries (review 2026-10-09 §7,
suggestion 3; built 2026-10-10).

A boundary that takes input from someone else must answer every input with
a result or a refusal it means: a `ValueError` naming what is wrong, a tool
error, an HTTP 4xx. Anything else is a bug the input found: a `TypeError`
or `KeyError` out of the native reader, an "internal error" answer from
odag-mcp, an HTTP 500 from the web API. Seeded random mutations, so a
failure reproduces from its seed:

- native files: a real store's text, mutated character and line;
- odag-mcp: every tool, called with arguments of every JSON shape;
- the web API: every route that reads a query string or a body, given
  random parameters.

`ONTODAG_SLOW_TESTS=1` runs five times as many cases.
"""

import io
import json
import os
import random
import tempfile
import unittest
from contextlib import redirect_stdout

from ontodag import OntoDAG, native, prelude

SLOW = bool(os.environ.get("ONTODAG_SLOW_TESTS"))
CASES = 1000 if SLOW else 200

HOSTILE = ["", " ", "'", '"', "(", ")", "((", "))", "\\", "#", "#:meta", "#:canonical",
           "\n", "\t", "*", "..", "..5kg", "mass(", "mass()", "mass(5kg", "mass(..)",
           "mass(5kg..1kg)", "mass(1e999999kg)", "mass(1/0kg)", "geo()", "geo(london)",
           "in(in(in(x)))", "in(" * 40 + "x" + ")" * 40, "time(2026-13)", "about()",
           "shared-with( )", "é", "😀", "\x00", "a" * 5000, "-1", "0", "1e309",
           "None", "null", "[]", "{}", "from(u2e)", "from(geo(u2e))", "transport(a b)"]


def store_text():
    d = OntoDAG()
    prelude.apply(d)
    for name, parents in [
        ("document", []), ("ticket", ["document"]), ("place", []), ("paris", ["place"]),
        ("louvre", ["place"]), ("louvre", ["in(paris)"]), ("guide", ["document", "about(louvre)"]),
        ("crate", ["mass(3kg)"]), ("trip", ["time(2026-08-15)"]), ("from", ["geo"]),
        ("parcel", ["from(u2ed4)"]), ("graph-dimension", ["dimension"]),
        ("transport", ["graph-dimension"]), ("courier", ["transport(ticket)"]),
    ]:
        d.put(name, parents)
    d.nodes["crate"].metadata["label"] = "Crate 7"
    return native.dumps(d)


def mutate(text, rng):
    lines = text.splitlines()
    for _ in range(rng.randint(1, 4)):
        if not lines:
            lines = [""]
        i = rng.randrange(len(lines))
        line = lines[i]
        roll = rng.random()
        if roll < 0.3 and line:
            j = rng.randrange(len(line) + 1)
            lines[i] = line[:j] + rng.choice(HOSTILE) + line[j:]
        elif roll < 0.45 and line:
            j = rng.randrange(len(line))
            lines[i] = line[:j] + line[j + 1:]
        elif roll < 0.55:
            lines.insert(i, rng.choice(lines))
        elif roll < 0.65:
            j = rng.randrange(len(lines))
            lines[i], lines[j] = lines[j], lines[i]
        elif roll < 0.75:
            lines[i] = " ".join(rng.choice(HOSTILE) for _ in range(rng.randint(1, 4)))
        elif roll < 0.85:
            lines.insert(i, rng.choice(["#:meta ", "#:canonical ", "#:meta x "])
                         + rng.choice(HOSTILE))
        else:
            del lines[i:]
    return "\n".join(lines) + rng.choice(["", "\n", "\n\n"])


class TestNativeFiles(unittest.TestCase):
    def test_every_mutation_loads_or_is_a_value_error(self):
        base = store_text()
        rng = random.Random(20261010)
        loaded = refused = 0
        for case in range(CASES):
            text = mutate(base, rng)
            try:
                native.loads(text)
                loaded += 1
            except ValueError:
                refused += 1
            except Exception as exc:     # noqa: BLE001 - what the test is for
                self.fail(f"case {case}: {type(exc).__name__}: {exc!r:.200}\n{text[:600]}")
        self.assertGreater(loaded, 0)
        self.assertGreater(refused, 0)


def random_value(rng, depth=0):
    roll = rng.random()
    if roll < 0.45:
        return rng.choice(HOSTILE + ["document", "louvre", "crate", "mass(..5kg)",
                                     "in(paris)", "about(louvre)", "time(2026)"])
    if roll < 0.55:
        return rng.choice([0, -1, 1, 2 ** 70, 3.5])
    if roll < 0.62:
        return rng.choice([True, False, None])
    if depth < 2 and roll < 0.85:
        return [random_value(rng, depth + 1) for _ in range(rng.randint(0, 3))]
    if depth < 2:
        return {rng.choice(["terms", "any_of", "a", "b", "x"]): random_value(rng, depth + 1)
                for _ in range(rng.randint(0, 3))}
    return "x"


class TestMcpArguments(unittest.TestCase):
    def test_every_tool_answers_or_refuses(self):
        from ontodag.__main__ import Session, dispatch
        from ontodag.mcp import AgentSurface, MCPServer
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "store.od")
            session = Session(path)
            with redirect_stdout(io.StringIO()):
                for line in (["prelude"], ["put", "document"], ["put", "ticket", "document"],
                             ["put", "crate", "mass(3kg)"], ["put", "trip", "time(2026-08-15)"]):
                    assert dispatch(line, session) == 0, line
            server = MCPServer(AgentSurface(path))
            tools = [spec["name"] for spec in server.surface.tool_specs()]
            props = {spec["name"]: sorted((spec.get("inputSchema") or {}).get("properties", {}))
                     for spec in server.surface.tool_specs()}
            rng = random.Random(1010)
            bugs = []
            for case in range(CASES):
                tool = rng.choice(tools + ["no-such-tool"])
                if rng.random() < 0.15:
                    arguments = random_value(rng)          # not an object at all
                else:
                    keys = props.get(tool, []) + ["junk"]
                    arguments = {rng.choice(keys): random_value(rng)
                                 for _ in range(rng.randint(0, 3))}
                params = {"name": tool, "arguments": arguments}
                if rng.random() < 0.05:
                    params = random_value(rng)             # not even params
                response = server.handle({"jsonrpc": "2.0", "id": case,
                                          "method": "tools/call", "params": params})
                json.dumps(response)                      # always serializable
                result = response.get("result") or {}
                text = (result.get("content") or [{}])[0].get("text", "")
                if "error" not in response and text.startswith("internal error"):
                    bugs.append((case, tool, arguments, text[:160]))
            kinds = sorted({(b[1], b[3][:60]) for b in bugs})
            self.assertEqual(bugs[:5], [], f"{len(bugs)} internal errors: {kinds}")


ROUTES = [  # (method, path, query or body keys)
    ("GET", "/dag/query", ["cat", "items_only"]),
    ("GET", "/dag/below", ["sub", "sup"]),
    ("GET", "/dag/overlaps", ["a", "b"]),
    ("GET", "/dag/meet", ["a", "b"]),
    ("GET", "/dag/canon", ["term"]),
    ("GET", "/dag/overlapping", ["term"]),
    ("GET", "/dag/removal", ["name", "cone", "with_terms"]),
    ("GET", "/dag/names", ["prefix"]),
    ("GET", "/dag/picture", ["focus", "depth", "cat"]),
    ("GET", "/dag/query/image", ["cat"]),
    ("GET", "/dag/browse", ["focus", "cat"]),
    ("POST", "/dag/node", ["name", "categories", "category", "parents"]),
    ("PATCH", "/dag/node", ["name", "to", "from", "categories"]),
    ("DELETE", "/dag/node", ["name", "cone", "with_terms"]),
    ("POST", "/dag/console", ["line", "command"]),
]


class TestWebRoutes(unittest.TestCase):
    def test_no_input_makes_a_500(self):
        try:
            from ontodag.web.app import app
        except ImportError as exc:                       # the web extra
            self.skipTest(f"web extra not installed: {exc}")
        app.config["TESTING"] = True
        rng = random.Random(4242)
        bugs = []
        with app.test_client() as client:
            client.post("/dag/example")
            for case in range(CASES):
                method, path, keys = rng.choice(ROUTES)
                fields = {rng.choice(keys): random_value(rng)
                          for _ in range(rng.randint(0, len(keys)))}
                try:
                    if method == "GET":
                        query = {k: (v if isinstance(v, str) else json.dumps(v))
                                 for k, v in fields.items()}
                        response = client.get(path, query_string=query)
                    else:
                        body = fields if rng.random() < 0.8 else random_value(rng)
                        response = client.open(path, method=method, json=body)
                except Exception as exc:   # noqa: BLE001 - TESTING re-raises what a 500 hides
                    bugs.append((case, method, path, fields, type(exc).__name__, str(exc)[:160]))
                    continue
                if response.status_code >= 500 and response.status_code != 501:
                    bugs.append((case, method, path, fields,
                                 response.status_code, response.get_data(as_text=True)[:160]))
        kinds = sorted({(b[1], b[2], b[4]) for b in bugs})
        self.assertEqual(bugs[:5], [], f"{len(bugs)} server errors: {kinds}")


if __name__ == "__main__":
    unittest.main()
