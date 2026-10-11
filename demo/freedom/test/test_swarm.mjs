// node demo/freedom/test/test_swarm.mjs vectors.json
// Checks swarm.js against chunk trees made by swarmfs's splitter.
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { keccak_256 } from "../vendor/noble-hashes/sha3.js";
import { hex, unhex, spanValue, chunkAddress, ChunkReader, Forged, Unreachable, topicOf } from "../swarm.js";

let failures = 0;
const check = (ok, what) => { console.log(`${ok ? "ok  " : "FAIL"} ${what}`); if (!ok) failures++; };

check(hex(keccak_256(new Uint8Array())) === "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470", "keccak256 of nothing");

// A source serving one tree's chunks, the way a client would.
class FakeSource {
  constructor(chunks, { tamper = null, drop = null } = {}) { this.chunks = chunks; this.tamper = tamper; this.drop = drop; this.reads = 0; }
  async readChunk(ref) {
    this.reads++;
    if (ref === this.drop || !(ref in this.chunks)) return null;
    const wire = unhex(this.chunks[ref]);
    const payload = wire.slice(8);
    if (ref === this.tamper) payload[0] ^= 1;
    return { span: spanValue(wire.subarray(0, 8)), payload };
  }
}

const cases = JSON.parse(readFileSync(process.argv[2], "utf8"));
for (const c of cases) {
  for (const [address, wire] of Object.entries(c.chunks)) {
    const w = unhex(wire);
    if (chunkAddress(spanValue(w.subarray(0, 8)), w.subarray(8)) !== address) {
      check(false, `chunk address in the ${c.size}-byte tree`);
    }
  }
  const reader = new ChunkReader(new FakeSource(c.chunks));
  const data = await reader.bytes(c.root);
  const sha = createHash("sha256").update(data).digest("hex");
  check(sha === c.sha256 && data.length === c.size, `join ${c.size} bytes (${Object.keys(c.chunks).length} chunks, ${reader.stats.reads} read)`);
}

// A tampered chunk anywhere in the tree is refused, and so is a missing one.
const big = cases.find((c) => c.size === 600_000);
const leaf = Object.keys(big.chunks).find((a) => a !== big.root);
try { await new ChunkReader(new FakeSource(big.chunks, { tamper: leaf })).bytes(big.root); check(false, "tampered leaf refused"); }
catch (e) { check(e instanceof Forged, "tampered leaf refused"); }
try { await new ChunkReader(new FakeSource(big.chunks, { drop: leaf })).bytes(big.root); check(false, "missing leaf refused"); }
catch (e) { check(e instanceof Unreachable, "missing leaf is unreachable, not empty"); }

// One read per chunk, even when the same chunk is asked for twice at once.
const src = new FakeSource(big.chunks);
const reader = new ChunkReader(src);
await Promise.all([reader.bytes(big.root), reader.bytes(big.root)]);
check(src.reads === Object.keys(big.chunks).length, `each chunk read once (${src.reads} reads for ${Object.keys(big.chunks).length} chunks)`);

check(topicOf("pack-core") === hex(keccak_256(new TextEncoder().encode("pack-core"))), "topic of a name");
process.exit(failures ? 1 : 0);
