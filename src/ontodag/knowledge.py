"""A store's knowledge id: the Swarm reference of its canonical `.od` text.

Two hashes name a state, for two jobs. The **root** (`odag status`) names
how a store keeps it: recordstore's trie of one record per node, hashed by
the backend's addressing (sha256 for `rs:`, Swarm's BMT for `swarm:`). It is
what lazy reads and certificates walk, and it changes with the backend and
with the trie's format. The **knowledge id** names what the store knows: the
BMT reference of `native.dumps(dag)`, which is a function of the filings
alone under one registry version (G1; the registry version is written in the
text, G8). So equal knowledge has one knowledge id however and wherever it is
kept, and the id is also the address of that text on Swarm: `publish` the
text and the id that says what a pack is also fetches it (`knowledge:ID` in
`merge`, `merge --diff` and `import`).

It is computed on demand, never on commit: it hashes the whole text
(about 0.4 s for core's 680 KB). It needs the `swarm` extra, for Keccak.
"""
import os

from ontodag import native
from ontodag._extras import require
from ontodag.settings import configured

PREFIX = "knowledge:"


def _content_address():
    return require("swarmfs.splitter", "swarm", "a knowledge id").content_address


def text(dag) -> bytes:
    """The canonical text whose reference is the knowledge id."""
    return native.dumps(dag).encode("utf-8")


def knowledge_id(dag) -> str:
    """The BMT reference (64 hex) of `dag`'s canonical `.od` text."""
    return _content_address()(text(dag)).hex()


def _api(api_url=None):
    return api_url or configured("bee_api") or os.environ.get(
        "BEE_API_URL", "http://localhost:1633")


def _bytes_store(api_url=None, batch=None):
    api = _api(api_url)
    store = require("recordstore", "swarm", "publishing or fetching by knowledge id")
    return store.BeeBytesStore(api, postage_batch_id=batch or configured("bee_batch") or "auto",
                               deferred_upload=False)


def publish(dag, bytes_store=None):
    """Upload `dag`'s canonical text; returns its knowledge id. Refuses when
    the node's reference is not the one computed offline, which would make
    the id fetch something else."""
    data = text(dag)
    expected = _content_address()(data).hex()
    store = bytes_store if bytes_store is not None else _bytes_store()
    got = store.put(data)
    if got != expected:
        raise ValueError(f"the node stored the text under {got}, not its knowledge id "
                         f"{expected}: nothing to fetch it by")
    return expected


def retrievable(ref, api_url=None):
    """The node's claim (`GET /stewardship`) that `ref` can be fetched from
    the network: an upload's success says the node took the chunks, not
    that the network holds them."""
    swarmfs = require("swarmfs", "swarm", "checking that a publication is retrievable")
    with swarmfs.SyncSwarmClient(_api(api_url)) as client:
        return client.stewardship_get(ref)


def fetch(ref, bytes_store=None):
    """The store whose knowledge id is `ref`, from Swarm. The bytes are
    checked against `ref` before anything is read, so a node or gateway
    that serves other content is refused, not believed."""
    ref = ref[len(PREFIX):] if ref.startswith(PREFIX) else ref
    if len(ref) != 64 or any(c not in "0123456789abcdef" for c in ref.lower()):
        raise ValueError(f"a knowledge id is 64 hex digits, not {ref!r}")
    store = bytes_store if bytes_store is not None else _bytes_store()
    try:
        data = store.get(ref.lower())
    except KeyError:
        raise ValueError(f"no content under knowledge id {ref}") from None
    if _content_address()(data).hex() != ref.lower():
        raise ValueError(f"the content served for {ref} has another reference: "
                         "refused, nothing merged")
    return native.loads(data.decode("utf-8"), source=PREFIX + ref)
