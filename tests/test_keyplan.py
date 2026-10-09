"""The key plan (ontodag.keyplan, docs/plans/SHARING_ON_SWARM.md §4).

What must hold:
- **A reader derives exactly its reach**: everything below
  `shared-with(reader)` (ROLES.md §8 item 20), what is shared with its
  groups and computed hops included, and sees exactly the edges inside it.
  Parents stay closed, and members don't see each other.
- **Lazy revocation.** A reader that kept every key it ever held can never
  open a record whose key was minted after it last had that node in reach:
  checked on hand-made removals and on random stores and edits, re-filed
  names included. Nothing is rotated until something new would be wrapped
  under a lost node.
- **Two keys.** Rotating a node never re-encrypts its content.
- **Keyed ids.** Node ids can't be computed from guessed names.
- **Stable publishing.** Republishing an unchanged store writes nothing, the
  private state round-trips through JSON, and a failed publish changes no
  state.

Gated on the `act` extra (coincurve + pycryptodome); skips otherwise.
"""

import hashlib
import importlib
import json
import random
import unittest

try:
    importlib.import_module("coincurve")
    importlib.import_module("Crypto.Cipher.AES")
    HAVE_ACT = True
except ImportError:
    HAVE_ACT = False

from recordstore import MemoryBytesStore, RecordStore

from ontodag import prelude, sharing
from ontodag.dag import OntoDAG

if HAVE_ACT:
    from ontodag import act, keyplan
    from ontodag.act import public_key


def _rng(seed):
    r = random.Random(seed)
    return lambda n: bytes(r.getrandbits(8) for _ in range(n))


def _priv(seed):
    return (seed + 1).to_bytes(32, "big")


def sw(name):
    return f"shared-with({name})"


AUTHOR = (99).to_bytes(32, "big")


def _declare(d):
    prelude.apply(d)
    d.put("reversed-dimension", ["dimension"])
    d.put("shared-with", ["reversed-dimension"])
    d.put("posted", ["time"])
    return d


def _acme():
    """A small store: a group of friends, a private parent, a direct share,
    a share of all 2026 posts, a public post."""
    d = _declare(OntoDAG())
    for name, parents in [
            ("person", []), ("friend", ["person"]),
            ("bob@x", ["friend"]), ("carol@x", ["friend"]), ("everyone", []),
            ("merger-plans", []),
            ("employee-info", ["merger-plans", sw("friend")]),
            ("trip", [sw("friend")]),
            ("note-to-bob", [sw("bob@x")]),
            ("posted(2026)", [sw("bob@x")]),
            ("hello", ["posted(2026-09-20T08:30:00Z)", sw("everyone")])]:
        d.put(name, parents)
    return d


READERS = {"bob@x": _priv(1), "carol@x": _priv(2)}


def _principals(readers=READERS):
    out = {p: public_key(k) for p, k in readers.items()}
    out["everyone"] = public_key(keyplan.everyone_key())
    return out


def _allowed(d, p):
    """What a reader must see: its reach and its own audience term, or
    nothing when nothing is shared with it."""
    term, starts = sharing.tops(d, p)
    return set(sharing.reach(d, [p])) | {term} if starts else set()


def _view(pub, key):
    return keyplan.Reader(RecordStore.at(pub.store.root, pub.store.blobs),
                          key, public_key(AUTHOR)).receive()


def _held(pub, key, held):
    """Walk as the reader and add every key it derives to `held`
    ({id: set of keys}): a reader that forgets nothing."""
    _top, keys, _ = keyplan.Reader(pub.store, key, public_key(AUTHOR)).walk()
    for i, k in keys.items():
        held.setdefault(i, set()).add(k)


def _derivable(store, held):
    """Everything `held` derives over the current tokens, trying every key
    held for each node: an attacker with old keys."""
    known = {i: set(ks) for i, ks in held.items()}
    out = {}
    for u, v, token in keyplan.tokens(store):
        out.setdefault(u, []).append((v, token))
    changed = True
    while changed:
        changed = False
        for u, ks in list(known.items()):
            for v, token in out.get(u, ()):
                for key in list(ks):
                    try:
                        cand = act.unwrap(key, v, token)
                    except ValueError:
                        continue        # format 2: a wrong key fails closed
                    if cand not in known.setdefault(v, set()):
                        known[v].add(cand)
                        changed = True
    return known


def _opens(store, node_id, keys):
    """Whether any of `keys` opens the node's current record."""
    try:
        record = store.get(keyplan.record_key(node_id))
    except KeyError:
        return False
    for k in keys:
        try:
            keyplan.unseal(k, f"{node_id}|{record['epoch']}", record["box"])
            return True
        except ValueError:
            pass
    return False


@unittest.skipUnless(HAVE_ACT, "needs the act extra")
class TestWhatReadersSee(unittest.TestCase):

    def setUp(self):
        self.dag = _acme()
        self.pub = keyplan.Publisher(RecordStore(MemoryBytesStore()), AUTHOR, rng=_rng(1))
        self.pub.publish(self.dag, _principals(), content={"trip": b"photos", "hello": b"hi"})

    def test_each_reader_derives_exactly_its_reach(self):
        for p, key in READERS.items():
            got = _view(self.pub, key)
            self.assertEqual(got.principal, p)
            self.assertEqual(got.names, _allowed(self.dag, p))

    def test_a_grantee_entry_is_an_act_entry(self):
        # Bee's ACT entry bit for bit: lookup -> Enc(wrap, K) under the
        # ECDH keys of author and reader, K opening the reader's term
        for p, key in READERS.items():
            lookup, wrap_key = act.act_keys(key, act.public_key(AUTHOR))
            entry = self.pub.store.get(keyplan.GRANT_PREFIX + lookup.hex())
            self.assertEqual(entry["node"], self.pub.node_id(sw(p)))
            self.assertEqual(act.stream_transform(wrap_key, bytes.fromhex(entry["key"])),
                             self.pub._keys[sw(p)])

    def test_a_group_share_reaches_every_member(self):
        for key in READERS.values():
            got = _view(self.pub, key)
            self.assertIn("trip", got)
            self.assertIn(sw("friend"), got)

    def test_edges_are_the_combined_order_inside_reach(self):
        for p, key in READERS.items():
            self.assertEqual(_view(self.pub, key).edges,
                             set(keyplan.plan(self.dag, [p])))

    def test_computed_hops_carry_a_share_of_all_2026_posts(self):
        bob = _view(self.pub, READERS["bob@x"])
        self.assertIn("hello", bob)
        self.assertIn("posted(2026-09-20T08:30:00Z)", bob)
        self.assertNotIn("hello", _view(self.pub, READERS["carol@x"]))

    def test_parents_stay_closed_and_members_do_not_see_each_other(self):
        bob = _view(self.pub, READERS["bob@x"])
        self.assertIn("employee-info", bob)
        self.assertNotIn("merger-plans", bob)
        self.assertNotIn("carol@x", bob)
        self.assertNotIn("note-to-bob", _view(self.pub, READERS["carol@x"]))
        self.assertEqual(bob.parents("employee-info"), [sw("friend")])

    def test_content_and_everyone(self):
        self.assertEqual(_view(self.pub, READERS["carol@x"]).content("trip"), b"photos")
        public = keyplan.Reader.public(self.pub.store, public_key(AUTHOR)).receive()
        self.assertEqual(public.names, {sw("everyone"), "hello"})
        self.assertEqual(public.principal, "everyone")
        self.assertEqual(public.content("hello"), b"hi")

    def test_records_name_no_parents(self):
        bob = _view(self.pub, READERS["bob@x"])
        self.assertFalse(hasattr(bob, "timeline"))
        self.assertFalse(hasattr(bob, "values"))

    def test_strangers_get_nothing(self):
        got = keyplan.Reader(self.pub.store, _priv(7), public_key(AUTHOR)).receive()
        self.assertEqual(len(got), 0)

    def test_republishing_an_unchanged_store_writes_nothing(self):
        root = self.pub.store.root
        again = self.pub.publish(self.dag, _principals(),
                                 content={"trip": b"photos", "hello": b"hi"})
        self.assertEqual((again.written, again.deleted, again.rotated), (0, 0, []))
        self.assertEqual(again.root, root)

    def test_state_round_trips_through_json(self):
        state = json.loads(json.dumps(self.pub.state))
        resumed = keyplan.Publisher(self.pub.store, AUTHOR, state=state)
        again = resumed.publish(self.dag, _principals(),
                                content={"trip": b"photos", "hello": b"hi"})
        self.assertEqual((again.written, again.deleted), (0, 0))

    def test_ids_are_keyed(self):
        ids = {k[len(keyplan.NODE_PREFIX):]
               for k in self.pub.store.keys(keyplan.NODE_PREFIX) if "/t/" not in k}
        self.assertEqual(len(ids), self.pub.publish(self.dag, _principals()).shared)
        # an unkeyed hash of the name, which anyone could compute from a guess
        guessed = hashlib.sha256(sw("bob@x").encode()).hexdigest()
        self.assertNotIn(guessed, ids)
        self.assertNotIn(guessed[:32], ids)
        other = keyplan.Publisher(RecordStore(MemoryBytesStore()), AUTHOR, rng=_rng(2))
        self.assertNotEqual(other.node_id("bob@x"), self.pub.node_id("bob@x"))

    def test_readers_use_one_worker_under_pyodide(self):
        import sys
        from unittest import mock
        with mock.patch.object(sys, "platform", "emscripten"):
            reader = keyplan.Reader(self.pub.store, READERS["bob@x"], public_key(AUTHOR))
        self.assertEqual(reader._workers, 1)
        self.assertEqual(keyplan.Reader(self.pub.store, READERS["bob@x"],
                                        public_key(AUTHOR))._workers, 16)


@unittest.skipUnless(HAVE_ACT, "needs the act extra")
class TestLazyRevocation(unittest.TestCase):

    def setUp(self):
        self.dag = _acme()
        self.pub = keyplan.Publisher(RecordStore(MemoryBytesStore()), AUTHOR, rng=_rng(3))
        self.content = {"trip": b"photos"}
        self.pub.publish(self.dag, _principals(), content=self.content)
        self.carol = {}
        _held(self.pub, READERS["carol@x"], self.carol)

    def _carol_opens(self, name):
        return _opens(self.pub.store, self.pub.node_id(name),
                      _derivable(self.pub.store, self.carol).get(self.pub.node_id(name), ()))

    def _carol_leaves(self):
        self.dag.reclassify(["carol@x"], to=["person"], from_=["friend"])

    def test_leaving_a_group_rotates_nothing_until_something_new(self):
        self._carol_leaves()
        out = self.pub.publish(self.dag, _principals(), content=self.content)
        self.assertEqual(out.rotated, [])
        self.assertEqual(self.pub.stale, {sw("friend"), "trip", "employee-info"})
        self.assertEqual(len(_view(self.pub, READERS["carol@x"])), 0)

        self.dag.put("new-post", [sw("friend")])
        out = self.pub.publish(self.dag, _principals(), content=self.content)
        self.assertEqual(out.rotated, [sw("friend")])
        self.assertIn("new-post", _view(self.pub, READERS["bob@x"]))
        self.assertFalse(self._carol_opens("new-post"))
        self.assertFalse(self._carol_opens(sw("friend")))
        # what she had, she keeps: forward-only
        self.assertTrue(self._carol_opens("trip"))

    def test_new_content_under_a_lost_node_rotates_it_first(self):
        self._carol_leaves()
        self.pub.publish(self.dag, _principals(), content=self.content)
        out = self.pub.publish(self.dag, _principals(), content={"trip": b"new photos"})
        # trip's new key is wrapped under the friends' term, which Carol lost
        # too: the fixpoint rotates both
        self.assertEqual(out.rotated, [sw("friend"), "trip"])
        self.assertFalse(self._carol_opens("trip"))
        self.assertEqual(_view(self.pub, READERS["bob@x"]).content("trip"), b"new photos")

    def test_rotation_never_reencrypts_content(self):
        before = {k: self.pub.store.get(k) for k in self.pub.store.keys(keyplan.CONTENT_PREFIX)}
        self._carol_leaves()
        out = self.pub.publish(self.dag, _principals(), content=self.content, eager=True)
        self.assertIn("trip", out.rotated)
        after = {k: self.pub.store.get(k) for k in self.pub.store.keys(keyplan.CONTENT_PREFIX)}
        self.assertEqual(before, after)
        self.assertEqual(_view(self.pub, READERS["bob@x"]).content("trip"), b"photos")
        self.assertFalse(self._carol_opens("trip"))

    def test_a_removed_principal_loses_its_entry_and_everything_it_reached(self):
        readers = {"bob@x": READERS["bob@x"]}
        out = self.pub.publish(self.dag, _principals(readers), content=self.content)
        self.assertEqual(out.rotated, [])
        self.assertEqual(len(_view(self.pub, READERS["carol@x"])), 0)
        self.assertTrue({sw("friend"), "trip"} <= self.pub.stale)

    def test_a_changed_key_is_a_loss_for_the_old_one(self):
        bob_old = {}
        _held(self.pub, READERS["bob@x"], bob_old)
        readers = dict(READERS, **{"bob@x": _priv(11)})
        self.pub.publish(self.dag, _principals(readers), content=self.content)
        self.assertEqual(len(_view(self.pub, READERS["bob@x"])), 0)
        self.assertIn("note-to-bob", _view(self.pub, _priv(11)))
        self.dag.put("second-note", [sw("bob@x")])
        out = self.pub.publish(self.dag, _principals(readers), content=self.content)
        self.assertIn(sw("bob@x"), out.rotated)
        derivable = _derivable(self.pub.store, bob_old)
        self.assertFalse(_opens(self.pub.store, self.pub.node_id("second-note"),
                                derivable.get(self.pub.node_id("second-note"), ())))

    def test_a_refiled_name_gets_a_fresh_key(self):
        """Removed while Carol had lost it, then filed again: under its old
        key she could read it again. (Review fix: a name that left the
        store kept its key.)"""
        self._carol_leaves()
        self.pub.publish(self.dag, _principals(), content=self.content)
        self.dag.remove("trip")
        self.pub.publish(self.dag, _principals(), content={})
        self.dag.put("trip", [sw("friend")])
        self.pub.publish(self.dag, _principals(), content={"trip": b"later photos"})
        self.assertIn("trip", _view(self.pub, READERS["bob@x"]))
        self.assertFalse(self._carol_opens("trip"))

    def test_rotated_tokens_share_no_keystream_across_roots(self):
        """An attacker holding the store before and after a rotation XORs the
        two tokens of one edge. Format 2 binds each keystream to the key it
        wraps, so the XOR of the bodies is not the XOR of the keys."""
        before = dict(((u, v), t) for u, v, t in keyplan.tokens(self.pub.store))
        keys_before = dict(self.pub._keys)
        self._carol_leaves()
        self.pub.publish(self.dag, _principals(), content=self.content, eager=True)
        after = dict(((u, v), t) for u, v, t in keyplan.tokens(self.pub.store))
        ids = {self.pub.node_id(n): n for n in self.pub._keys}
        checked = 0
        for edge, old in before.items():
            new = after.get(edge)
            v = ids.get(edge[1])
            if new is None or new == old or v not in keys_before:
                continue
            body_xor = bytes(a ^ b for a, b in zip(old[act.KEY_LEN:], new[act.KEY_LEN:]))
            key_xor = bytes(a ^ b for a, b in zip(keys_before[v], self.pub._keys[v]))
            self.assertNotEqual(body_xor, key_xor)
            checked += 1
        self.assertGreater(checked, 0)


class _FailingStore:
    """A record store whose commit fails, like a node gone away."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def commit(self, message=None):
        raise OSError("node unreachable")


@unittest.skipUnless(HAVE_ACT, "needs the act extra")
class TestAFailedPublishChangesNothing(unittest.TestCase):
    """Review fix: publish mutated its state before the commit, so a failed
    commit recorded a revocation the store never got."""

    def test_state_is_restored_and_a_retry_completes(self):
        dag = _acme()
        inner = RecordStore(MemoryBytesStore())
        pub = keyplan.Publisher(inner, AUTHOR, rng=_rng(5))
        pub.publish(dag, _principals())
        carol = {}
        _held(pub, READERS["carol@x"], carol)
        saved = json.dumps(pub.state, sort_keys=True)

        dag.reclassify(["carol@x"], to=["person"], from_=["friend"])
        dag.put("new-post", [sw("friend")])
        pub.store = _FailingStore(inner)
        with self.assertRaises(OSError):
            pub.publish(dag, _principals())
        self.assertEqual(json.dumps(pub.state, sort_keys=True), saved)

        pub.store = inner
        out = pub.publish(dag, _principals())
        self.assertEqual(out.rotated, [sw("friend")])
        derivable = _derivable(inner, carol)
        self.assertFalse(_opens(inner, pub.node_id("new-post"),
                                derivable.get(pub.node_id("new-post"), ())))


def _random_store(rnd):
    d = _declare(OntoDAG())
    principals = ["a@x", "b@x", "c@x"]
    groups = ["g1", "g2"]
    d.put("person", [])
    for g in groups:
        d.put(g, ["person"])
    if rnd.random() < 0.5:
        d.put("g1", ["g2"])
    for p in principals:
        d.put(p, rnd.sample(groups, rnd.randint(0, 2)) or ["person"])
    items = [f"n{i}" for i in range(12)]
    audiences = [sw(x) for x in principals + groups]
    for i, it in enumerate(items):
        pool = items[:i] + audiences
        d.put(it, rnd.sample(pool, min(len(pool), rnd.randint(0, 2))))
    if rnd.random() < 0.6:
        d.put("posted(2026)", [rnd.choice(audiences)])
        for it in rnd.sample(items, 3):
            d.put(it, [f"posted(2026-09-{rnd.randint(1, 28):02d}T10:00:00Z)"])
    return d, principals, groups, items


def _random_edit(rnd, d, principals, groups, items):
    names = [n for n in items if n in d.nodes]
    audiences = [sw(x) for x in principals + groups]
    kind = rnd.random()
    try:
        if kind < 0.3 and names:
            x = rnd.choice(names)
            d.put(x, [rnd.choice([n for n in names + audiences if n != x])])
        elif kind < 0.45:
            # membership moves: a person joins or leaves a group
            p = rnd.choice(principals)
            d.reclassify([p], to=[rnd.choice(groups + ["person"])])
        elif kind < 0.75:
            cands = sorted((x, p.name) for x in names for p in d.nodes[x].parents
                           if d.nodes.get(p.name) is p and p.name != d.root.name)
            if cands:
                x, y = rnd.choice(cands)
                d.reclassify([x], to=(), from_=[y])
        elif kind < 0.9 and names:
            d.remove(rnd.choice(names))
        else:
            # a removed name filed again: it must not come back under its old key
            gone = [n for n in items if n not in d.nodes]
            if gone:
                d.put(rnd.choice(gone), [rnd.choice(audiences)])
    except ValueError:
        pass


@unittest.skipUnless(HAVE_ACT, "needs the act extra")
class TestRandomStores(unittest.TestCase):
    """The spike's properties, on the real Publisher and Reader, with content
    that changes now and then. The revocation check is stronger than the
    spike's: a reader may open only record versions (epoch and content) it
    was once entitled to."""

    def test_reach_is_exact_and_no_new_key_is_ever_exposed(self):
        edits = rotations = 0
        for seed in range(12):
            rnd = random.Random(seed)
            d, principals, groups, items = _random_store(rnd)
            readers = {p: _priv(100 + i) for i, p in enumerate(principals)}
            pub = keyplan.Publisher(RecordStore(MemoryBytesStore()), AUTHOR,
                                    rng=_rng(1000 + seed))
            held = {p: {} for p in principals}
            seen = {p: {} for p in principals}   # name -> record versions it held
            for step in range(16):
                if step:
                    _random_edit(rnd, d, principals, groups, items)
                    edits += 1
                present = [n for n in items if n in d.nodes]
                content = {n: f"{n} v{rnd.randint(0, 2)}".encode()
                           for n in present[:4]}
                out = pub.publish(d, {p: public_key(k) for p, k in readers.items()},
                                  content=content)
                rotations += len(out.rotated)
                for p, key in readers.items():
                    allowed = _allowed(d, p)
                    view = _view(pub, key)
                    self.assertEqual(view.names, allowed, (seed, step, p))
                    for n in allowed:
                        seen[p].setdefault(n, set()).add(
                            (pub._epoch[n], pub._records[n]))
                    _held(pub, key, held[p])
                    derivable = _derivable(pub.store, held[p])
                    for n in (set(d.nodes) | set(pub._records)) - allowed:
                        i = pub.node_id(n)
                        if n not in pub._epoch or not _opens(pub.store, i, derivable.get(i, ())):
                            continue
                        self.assertIn((pub._epoch[n], pub._records.get(n)),
                                      seen[p].get(n, set()),
                                      f"{p} opens a version of {n} it never had "
                                      f"(seed {seed}, step {step})")
        self.assertGreater(edits, 150)
        self.assertLess(rotations, edits)


if __name__ == "__main__":
    unittest.main()
