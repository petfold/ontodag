// node demo/freedom/test/test_swarm.mjs vectors.json
// Checks swarm.js against chunk trees made by swarmfs's splitter.
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { keccak_256 } from "../vendor/noble-hashes/sha3.js";
import { hex, unhex, spanValue, chunkAddress, ChunkReader, Forged, Unreachable, topicOf, HttpSwarm } from "../swarm.js";

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

// A node or a gateway also hands over a whole blob (GET /bytes/<ref>): it is
// read in one request and checked by recomputing its address, and a blob of
// one chunk is then held as that chunk. One that does not check out (a tree
// the node erasure-coded, or bytes that are not what was asked for) is read
// chunk by chunk instead, every chunk checked.
class WholeSource extends FakeSource {
  constructor(chunks, blobs, { wrong = false } = {}) { super(chunks); this.blobs = blobs; this.wrong = wrong; this.blobReads = 0; }
  async readBytes(ref) {
    this.blobReads++;
    const blob = this.blobs[ref];
    if (blob === undefined) return null;
    if (!this.wrong) return blob;
    if (blob.length === 0) return Uint8Array.of(1);   // nothing to flip in an empty blob
    const bad = blob.slice();
    bad[0] ^= 1;
    return bad;
  }
}
for (const c of cases) {
  const data = await new ChunkReader(new FakeSource(c.chunks)).bytes(c.root);
  const whole = new WholeSource(c.chunks, { [c.root]: data });
  const got = await new ChunkReader(whole).bytes(c.root);
  check(whole.blobReads === 1 && whole.reads === 0 && createHash("sha256").update(got).digest("hex") === c.sha256,
        `a ${c.size}-byte blob read whole: ${whole.blobReads} blob read, ${whole.reads} chunk reads`);
  const liar = new WholeSource(c.chunks, { [c.root]: data }, { wrong: true });
  const safe = await new ChunkReader(liar).bytes(c.root);
  check(createHash("sha256").update(safe).digest("hex") === c.sha256 && liar.reads > 0,
        `a ${c.size}-byte blob that does not check out is read chunk by chunk (${liar.reads} chunk reads)`);
}
{
  const small = cases.find((c) => c.size > 0 && c.size <= 4096);
  const data = await new ChunkReader(new FakeSource(small.chunks)).bytes(small.root);
  const whole = new WholeSource(small.chunks, { [small.root]: data });
  const r = new ChunkReader(whole);
  await r.bytes(small.root);
  await r.bytes(small.root);
  const held = await r.chunk(small.root);
  check(whole.blobReads === 1 && whole.reads === 0 && held.payload.length === small.size,
        "a blob of one chunk read whole is held as its chunk: read once, then reused");
  let missing;
  try { await new ChunkReader(new WholeSource(small.chunks, {})).bytes(small.root); } catch (e) { missing = e; }
  check(missing instanceof Unreachable, "a blob the source does not have is unreachable, not empty");
}

// Live, optional: trees a Bee node erasure-coded itself (test/make_coded.py),
// read from that node and joined here.
if (process.argv[3]) {
  const { base, cases: coded } = JSON.parse(readFileSync(process.argv[3], "utf8"));
  for (const c of coded) {
    // A plain tree (level 0) checks out whole; a coded one does not, and is
    // read chunk by chunk.
    const reader = new ChunkReader(new HttpSwarm(base));
    const data = await reader.bytes(c.ref);
    const sha = createHash("sha256").update(data).digest("hex");
    const path = reader.stats.unchecked ? "chunk by chunk" : "whole";
    check(sha === c.sha256 && path === (c.level ? "chunk by chunk" : "whole"),
          `${c.size} bytes coded at level ${c.level} by the node, read ${path}`);
  }
}
process.exit(failures ? 1 : 0);
