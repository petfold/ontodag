"""A page's stable address: a Swarm feed whose newest update names the page's
current upload, and the feed manifest that a name (`ontodag.gwei`) or a
bookmark points at once. Publishing a new version advances the feed; the
name needs no new transaction.

    python3 demo/freedom/page_feed.py ontodag --set REF --batch ID   # point the feed at REF
    python3 demo/freedom/page_feed.py ontodag                         # print the manifest

The publisher key is made on first use and kept in ~/.ontodag/page-feeds/NAME.key
(mode 600, never printed, never committed): whoever holds it can repoint the
page, and losing it means pointing the name at a new feed once.
"""

import argparse
import json
import os
import secrets
import sys
import urllib.request

KEYS = os.path.expanduser("~/.ontodag/page-feeds")
TOPICS = {"ontodag": "ontodag/freedom-page", "loopmarket": "loopmarket/browser-page"}


def key_for(name):
    os.makedirs(KEYS, mode=0o700, exist_ok=True)
    path = os.path.join(KEYS, f"{name}.key")
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    return open(path).read().strip()



def topic_hex(topic):
    from swarmfs.bmt import keccak256
    return keccak256(topic.encode("utf-8")).hex()


def manifest(api, owner, topic, batch):
    """The feed manifest (Bee's POST /feeds): a collection that resolves to the
    feed's newest update, so bzz://MANIFEST/ always opens the current page."""
    req = urllib.request.Request(
        f"{api}/feeds/{owner.removeprefix('0x').lower()}/{topic_hex(topic)}?type=sequence",
        method="POST", headers={"Swarm-Postage-Batch-Id": batch})
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.load(res)["reference"]


def point(api, name, ref, batch):
    """Advance NAME's feed to the upload REF; return (owner, manifest)."""
    from recordstore import SwarmFeedPointer
    key = key_for(name)
    pointer = SwarmFeedPointer(api, TOPICS[name], signer=key, postage_batch_id=batch)
    pointer.set(ref)
    owner = pointer._owner.hex() if isinstance(pointer._owner, bytes) else str(pointer._owner)
    return owner, manifest(api, owner, TOPICS[name], batch)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", choices=sorted(TOPICS))
    ap.add_argument("--set", metavar="REF", help="point the feed at this upload")
    ap.add_argument("--api", default=os.environ.get("BEE_API", "http://localhost:1633"))
    ap.add_argument("--batch", default=os.environ.get("BEE_BATCH"))
    args = ap.parse_args()
    if not args.batch:
        sys.exit("a feed update needs a postage batch: --batch ID or BEE_BATCH")
    api = args.api.rstrip("/")
    if args.set:
        owner, ref = point(api, args.name, args.set, args.batch)
    else:
        from recordstore import SwarmFeedPointer
        pointer = SwarmFeedPointer(api, TOPICS[args.name], signer=key_for(args.name))
        owner = pointer._owner.hex() if isinstance(pointer._owner, bytes) else str(pointer._owner)
        ref = manifest(api, owner, TOPICS[args.name], args.batch)
    print(f"{args.name}: feed owner 0x{owner.removeprefix('0x')}, topic {TOPICS[args.name]}")
    print(f"manifest: bzz://{ref}/  ({api}/bzz/{ref}/)")


if __name__ == "__main__":
    main()
