"""A feed update made by swarmfs (libsecp256k1 through coincurve), for
test_publish.mjs: publish.js must produce the same identifier, signature and
address, so a feed the page writes reads as one odag wrote, and the other
way round. The key is a published test key, not anyone's.

    python3 demo/freedom/test/make_feed_vector.py > demo/freedom/test/feed_vector.json
"""

import json

from swarmfs.bmt import cac_data, chunk_address, keccak256
from swarmfs.feeds import FeedSigner, feed_identifier, soc_address

KEY = "11" * 32                       # a test key (it signs nothing real)
NAME = "my-store"
INDEX = 5
TIMESTAMP = 1791806400                # 2026-10-12 12:00 UTC
ROOT = "720d44c649379c4508549200a344771a8fa29c64880744dc2372d9f57863ceb8"

signer = FeedSigner(KEY)
topic = keccak256(NAME.encode("utf-8"))
payload = TIMESTAMP.to_bytes(8, "big") + bytes.fromhex(ROOT)
data = cac_data(payload)
identifier = feed_identifier(topic, INDEX)
signature = signer.sign_digest(keccak256(identifier + chunk_address(data)))
json.dump({
    "key": KEY, "name": NAME, "index": INDEX, "timestamp": TIMESTAMP, "root": ROOT,
    "owner": signer.owner_hex, "topic": topic.hex(), "identifier": identifier.hex(),
    "signature": signature.hex(), "data": data.hex(),
    "address": soc_address(identifier, signer.owner).hex(),
}, __import__("sys").stdout, indent=1)
print()
