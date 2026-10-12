// Swarm for a page, through whichever in-browser client is present
// (docs/plans/BROWSER.md §10).
//
// A client only has to read chunks and single-owner chunks (and, for writing
// later, write them). Everything else is done here, the same in every client:
// chunk trees are joined in the page, and every chunk is checked against the
// address that named it, so a client or a gateway cannot hand the page wrong
// data. A blob's whole tree is checked from its root reference down.
//
// Sources:
//   FreedomSwarm  Freedom Browser's window.swarm provider (readChunk,
//                 readSingleOwnerChunk, readFeedEntry); the node's own HTTP
//                 API is closed to pages there.
//   HttpSwarm     a Bee or Ant node, or a gateway, over HTTP (GET /chunks).
//
// Reading is here; writing (a node's batches, a feed signed by the person's
// key) is publish.js, which builds on the addresses computed here. Freedom
// writes once it publishes a chunk the page signed (freedom-browser#647).

import { keccak_256 } from "./vendor/noble-hashes/sha3.js";

export const CHUNK_SIZE = 4096;
const SEGMENT_PAIRS = 64;          // 128 segments of 32 bytes, hashed in pairs

// ---------------------------------------------------------------- bytes

export function hex(bytes) {
  let s = "";
  for (const b of bytes) s += b.toString(16).padStart(2, "0");
  return s;
}

export function unhex(s) {
  s = s.replace(/^0x/, "");
  if (s.length % 2 || /[^0-9a-fA-F]/.test(s)) throw new Error(`not hex: ${s}`);
  const out = new Uint8Array(s.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(s.slice(2 * i, 2 * i + 2), 16);
  return out;
}

function fromBase64(text) {
  const raw = atob(text);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function concat(parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
}

const utf8 = new TextEncoder();

// A chunk's span: how many bytes of data lie under it, 8 bytes little-endian.
export function spanBytes(span) {
  const out = new Uint8Array(8);
  let v = BigInt(span);
  for (let i = 0; i < 8; i++) { out[i] = Number(v & 0xffn); v >>= 8n; }
  return out;
}

export function spanValue(bytes) {
  let v = 0n;
  for (let i = 7; i >= 0; i--) v = (v << 8n) | BigInt(bytes[i]);
  return v;
}

// ---------------------------------------------------------------- erasure coding

// Bee erasure-codes uploads on request, and some nodes by default (Bee 2.8
// does for /bytes without a level): an intermediate chunk then carries its
// level in the span's top byte (0x80 | level) and lists its data references
// first, its parity references after them. Joining reads the data
// references only; how many there are follows from the span and the level's
// table (bee pkg/file/redundancy/level.go, pkg/file/utils.go ReferenceCount).
const ERASURE_TABLES = {
  1: [[95, 69, 47, 29, 15, 6, 2, 1], [9, 8, 7, 6, 5, 4, 3, 2]],
  2: [[105, 96, 87, 78, 70, 62, 54, 47, 40, 33, 27, 21, 16, 11, 7, 4, 2, 1],
      [21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4]],
  3: [[93, 88, 83, 78, 74, 69, 64, 60, 55, 51, 46, 42, 38, 34, 30, 27, 23, 20, 17, 14, 11, 9, 6, 4, 3, 2, 1],
      [31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5]],
  4: [[37, 36, 35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18,
       17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
      [89, 87, 86, 84, 83, 81, 80, 78, 76, 75, 73, 71, 70, 68, 66, 65, 63, 61, 59, 58,
       56, 54, 52, 50, 48, 47, 45, 43, 40, 38, 36, 34, 31, 29, 26, 23, 19]],
};

function parities(level, shards) {
  const [shardSteps, parityCounts] = ERASURE_TABLES[level];
  for (let k = 0; k < shardSteps.length; k++) if (shards >= shardSteps[k]) return parityCounts[k];
  return 0;
}

// How many data references an intermediate chunk of `span` bytes holds at
// `level` (unencrypted references).
export function dataReferenceCount(span, level) {
  const branching = BigInt(128 - parities(level, 128));
  let branchSize = BigInt(CHUNK_SIZE), branchLevel = 1;
  while (branchSize < span) { branchSize *= branching; branchLevel++; }
  let referenceSize = BigInt(CHUNK_SIZE);
  for (let i = 1; i < branchLevel - 1; i++) referenceSize *= branching;
  let count = 1;
  for (let at = referenceSize; at < span; at += referenceSize) count++;
  return count;
}

// ---------------------------------------------------------------- addresses

// The binary Merkle tree root of a chunk's payload, zero-padded to 4096 bytes.
export function bmtRoot(payload) {
  if (payload.length > CHUNK_SIZE) throw new Error(`payload of ${payload.length} bytes`);
  let level = new Uint8Array(CHUNK_SIZE);
  level.set(payload);
  for (let pairs = SEGMENT_PAIRS; pairs >= 1; pairs >>= 1) {
    const next = new Uint8Array(pairs * 32);
    for (let i = 0; i < pairs; i++) {
      next.set(keccak_256(level.subarray(i * 64, i * 64 + 64)), i * 32);
    }
    level = next;
  }
  return level;
}

// A content-addressed chunk's address: keccak256(span || BMT root).
export function chunkAddress(span, payload) {
  return hex(keccak_256(concat([spanBytes(span), bmtRoot(payload)])));
}

// A blob's Swarm reference for a plain upload (no erasure coding), as Bee's
// splitter and recordstore's Swarm addressing compute it: leaves of 4096
// bytes, intermediate chunks of up to 128 references, and a group of one
// promoted a level rather than wrapped.
export function contentAddress(data) {
  if (data.length === 0) return chunkAddress(0, data);
  let level = [];
  for (let at = 0; at < data.length; at += CHUNK_SIZE) {
    const leaf = data.subarray(at, at + CHUNK_SIZE);
    level.push({ address: unhex(chunkAddress(leaf.length, leaf)), span: leaf.length });
  }
  while (level.length > 1) {
    const upper = [];
    for (let i = 0; i < level.length; i += 128) {
      const group = level.slice(i, i + 128);
      if (group.length === 1) { upper.push(group[0]); continue; }
      const span = group.reduce((n, c) => n + c.span, 0);
      upper.push({ address: unhex(chunkAddress(span, concat(group.map((c) => c.address)))), span });
    }
    level = upper;
  }
  return hex(level[0].address);
}

// A single-owner chunk's address: keccak256(identifier || owner).
export function socAddress(identifier, owner) {
  return hex(keccak_256(concat([unhex(identifier), unhex(owner)])));
}

// A feed's topic from its name, as bee-js' Topic.fromString and recordstore's
// SwarmFeedPointer derive it.
export function topicOf(name) {
  return hex(keccak_256(utf8.encode(name)));
}

// A sequence feed's update identifier: keccak256(topic || index, 8 bytes BE).
export function feedIdentifier(topic, index) {
  const i = new Uint8Array(8);
  let v = BigInt(index);
  for (let k = 7; k >= 0; k--) { i[k] = Number(v & 0xffn); v >>= 8n; }
  return hex(keccak_256(concat([unhex(topic), i])));
}

// ---------------------------------------------------------------- errors

export class Unreachable extends Error {
  constructor(ref, why) {
    super(`chunk ${ref.slice(0, 16)}… is not retrievable${why ? `: ${why}` : ""}`);
    this.ref = ref;
    this.unreachable = true;
  }
}

export class Forged extends Error {
  constructor(ref, got) {
    super(`chunk ${ref.slice(0, 16)}… came back with content addressed ${got.slice(0, 16)}…`);
    this.forged = true;
  }
}

const reasonOf = (e) => (e && e.data && e.data.reason) || (e && e.reason) || "";

// ---------------------------------------------------------------- sources

// Freedom Browser: window.swarm. Reads need no permission, but an origin that
// has not connected gets a small read budget (120 reads and 512 KB a minute);
// connect() asks for access, which raises it to 600 reads and 5 MB.
export class FreedomSwarm {
  constructor(swarm = globalThis.swarm) {
    this.swarm = swarm;
    this.kind = "Freedom Browser (window.swarm)";
  }

  static present() {
    return Boolean(globalThis.swarm && globalThis.swarm.isFreedomBrowser);
  }

  async connect() {
    return this.swarm.requestAccess();
  }

  async readChunk(ref) {
    let r;
    try {
      r = await this.swarm.readChunk({ reference: ref });
    } catch (e) {
      if (reasonOf(e) === "chunk_not_found") return null;
      throw e;
    }
    return { span: BigInt(r.span), payload: fromBase64(r.data) };
  }

  async readSignedChunk(owner, identifier) {
    let r;
    try {
      r = await this.swarm.readSingleOwnerChunk({ owner, identifier });
    } catch (e) {
      if (reasonOf(e) === "chunk_not_found") return null;
      throw e;
    }
    // Freedom's node checks the signature against the owner before answering.
    return { span: BigInt(r.span), payload: fromBase64(r.data), signature: r.signature };
  }

  // The newest index of a sequence feed, or null for an empty one.
  async latestFeedIndex(owner, topic) {
    try {
      const r = await this.swarm.readFeedEntry({ topic, owner });
      return Number(r.index);
    } catch (e) {
      if (["feed_empty", "entry_not_found"].includes(reasonOf(e))) return null;
      throw e;
    }
  }
}

// A Bee or Ant node, or a gateway, over HTTP.
export class HttpSwarm {
  constructor(base) {
    this.base = base.replace(/\/+$/, "");
    this.kind = `Swarm over HTTP (${this.base})`;
  }

  async connect() {}

  async readChunk(ref) {
    const res = await fetch(`${this.base}/chunks/${ref}`);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`GET /chunks/${ref.slice(0, 16)}…: HTTP ${res.status}`);
    const wire = new Uint8Array(await res.arrayBuffer());
    return { span: spanValue(wire.subarray(0, 8)), payload: wire.subarray(8) };
  }

  // A single-owner chunk on the wire is identifier(32) | signature(65) |
  // span(8) | payload. The signature is not checked here (no secp256k1 in
  // the page yet): over HTTP, trust in a feed update is trust in the node.
  async readSignedChunk(owner, identifier) {
    const res = await fetch(`${this.base}/chunks/${socAddress(identifier, owner)}`);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`GET single-owner chunk: HTTP ${res.status}`);
    const wire = new Uint8Array(await res.arrayBuffer());
    if (hex(wire.subarray(0, 32)) !== identifier.toLowerCase()) {
      throw new Error("single-owner chunk with another identifier");
    }
    return {
      span: spanValue(wire.subarray(97, 105)),
      payload: wire.subarray(105),
      signature: hex(wire.subarray(32, 97)),
    };
  }

  async latestFeedIndex(owner, topic) {
    const res = await fetch(`${this.base}/feeds/${owner.replace(/^0x/, "")}/${topic}`);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`GET /feeds: HTTP ${res.status}`);
    const index = res.headers.get("swarm-feed-index");
    if (index === null) throw new Error("the node did not say which feed index it read");
    return Number(BigInt("0x" + index));
  }
}

export function detectSource(gateway) {
  if (FreedomSwarm.present()) return new FreedomSwarm();
  return new HttpSwarm(gateway);
}

// ---------------------------------------------------------------- reading

class Gate {
  constructor(n) { this.free = n; this.waiting = []; }
  async enter() {
    if (this.free > 0) { this.free--; return; }
    await new Promise((resolve) => this.waiting.push(resolve));
  }
  leave() {
    const next = this.waiting.shift();
    if (next) next(); else this.free++;
  }
}

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Checked chunks kept in the browser's own database (IndexedDB) across
// visits: a chunk never changes, so a second visit reads from here instead of
// spending the client's read budget. Every failure here is a cache miss.
export class StoredChunks {
  static async open(name = "ontodag-swarm-chunks") {
    try {
      const db = await new Promise((resolve, reject) => {
        const req = indexedDB.open(name, 1);
        req.onupgradeneeded = () => req.result.createObjectStore("chunks");
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
      return new StoredChunks(db);
    } catch {
      return null;
    }
  }

  constructor(db) { this.db = db; }

  get(ref) {
    return new Promise((resolve) => {
      try {
        const req = this.db.transaction("chunks").objectStore("chunks").get(ref);
        req.onsuccess = () => resolve(req.result || null);
        req.onerror = () => resolve(null);
      } catch {
        resolve(null);
      }
    });
  }

  put(ref, chunk) {
    try {
      this.db.transaction("chunks", "readwrite").objectStore("chunks")
        .put({ span: chunk.span.toString(), payload: chunk.payload }, ref);
    } catch {
      // full, or closed: the next visit reads the network again
    }
  }
}

// Checked chunks, cached for the session (a chunk never changes), with a cap
// on reads in flight and a wait-and-retry when a client says "too many".
export class ChunkReader {
  constructor(source, { inFlight = 16, onRateLimit = () => {}, stored = null } = {}) {
    this.source = source;
    this.cache = new Map();
    this.stored = stored;
    this.gate = new Gate(inFlight);
    this.onRateLimit = onRateLimit;
    this.stats = { reads: 0, cached: 0, stored: 0, bytes: 0, waits: 0 };
  }

  chunk(ref) {
    ref = ref.toLowerCase();
    const hit = this.cache.get(ref);
    if (hit) { this.stats.cached++; return hit; }
    const pending = this._fetch(ref);
    this.cache.set(ref, pending);
    pending.catch(() => this.cache.delete(ref));
    return pending;
  }

  async _fetch(ref) {
    if (this.stored) {
      const kept = await this.stored.get(ref);
      if (kept) {
        const chunk = { span: BigInt(kept.span), payload: new Uint8Array(kept.payload) };
        if (chunkAddress(chunk.span, chunk.payload) === ref) {
          this.stats.stored++;
          return chunk;
        }
      }
    }
    await this.gate.enter();
    try {
      for (let wait = 2000; ; wait = Math.min(wait * 2, 30000)) {
        let got;
        try {
          got = await this.source.readChunk(ref);
        } catch (e) {
          if (reasonOf(e) !== "rate_limited") throw new Unreachable(ref, e.message);
          this.stats.waits++;
          this.onRateLimit(wait);
          await pause(wait);
          continue;
        }
        if (got === null) throw new Unreachable(ref);
        const address = chunkAddress(got.span, got.payload);
        if (address !== ref) throw new Forged(ref, address);
        this.stats.reads++;
        this.stats.bytes += got.payload.length;
        if (this.stored) this.stored.put(ref, got);
        return got;
      }
    } finally {
      this.gate.leave();
    }
  }

  // The bytes of a blob: its chunk tree joined, every chunk checked (an
  // erasure-coded tree's parity chunks are not read).
  async bytes(ref) {
    const { span: wire, payload } = await this.chunk(ref);
    const coded = (wire >> 63n) === 1n;
    const level = coded ? Number((wire >> 56n) & 0x7fn) : 0;
    const span = wire & 0x00ffffffffffffffn;
    if (coded && !ERASURE_TABLES[level]) throw new Error(`${ref.slice(0, 16)}… has unknown redundancy level ${level}`);
    if (span <= BigInt(CHUNK_SIZE)) return payload.slice(0, Number(span));
    if (payload.length % 32) throw new Error(`intermediate chunk ${ref.slice(0, 16)}… of ${payload.length} bytes`);
    const count = coded ? dataReferenceCount(span, level) : payload.length / 32;
    if (count * 32 > payload.length) throw new Error(`${ref.slice(0, 16)}… holds fewer references than its span needs`);
    const children = [];
    for (let i = 0; i < count; i++) children.push(hex(payload.subarray(32 * i, 32 * i + 32)));
    const data = concat(await Promise.all(children.map((c) => this.bytes(c))));
    if (BigInt(data.length) !== span) throw new Error(`${ref.slice(0, 16)}… joined to ${data.length} bytes, not ${span}`);
    return data;
  }

  // The newest root a recordstore feed names (8-byte timestamp, then the
  // root reference), with its index; null for an empty feed.
  async feedRoot(owner, topic) {
    owner = owner.replace(/^0x/, "").toLowerCase();
    const index = await this.source.latestFeedIndex(owner, topic);
    if (index === null) return null;
    const soc = await this.source.readSignedChunk(owner, feedIdentifier(topic, index));
    if (soc === null) throw new Unreachable(socAddress(feedIdentifier(topic, index), owner), "feed update");
    const payload = soc.payload.slice(0, Number(soc.span));
    if (payload.length !== 40) throw new Error(`feed update of ${payload.length} bytes, not a timestamp and a root`);
    let timestamp = 0n;
    for (const b of payload.subarray(0, 8)) timestamp = (timestamp << 8n) | BigInt(b);
    return { index, timestamp: Number(timestamp), root: hex(payload.subarray(8)) };
  }
}

// The object ontodag.browser.JsBytesStore calls through JSPI: download(ref)
// and downloadMany(refs). An unreachable or forged blob rejects, and Python
// raises it as an error, never as "absent" (a wrong answer would be worse
// than none).
export class BlobStore {
  constructor(reader) { this.reader = reader; this.held = new Map(); }
  download(ref) { return this.reader.bytes(String(ref)); }
  downloadMany(refs) { return Promise.all(Array.from(refs, (r) => this.download(r))); }
  async upload() { throw new Error("this page reads Swarm; it does not write"); }

  // Retry mode (ontodag.browser.RETRY), where Python cannot wait on a
  // promise (Pyodide on iOS): Python reads synchronously what the page has
  // fetched, and a call that needs more names it; the page fetches those
  // and runs the call again. `cached` is the blob, undefined if not
  // fetched, or a throw if fetching it failed.
  cached(ref) {
    const value = this.held.get(String(ref));
    if (value instanceof Error) throw value;
    return value;
  }

  async fetch(refs) {
    await Promise.all(Array.from(refs, async (ref) => {
      ref = String(ref);
      if (this.held.has(ref)) return;
      try {
        this.held.set(ref, await this.download(ref));
      } catch (e) {
        this.held.set(ref, e instanceof Error ? e : new Error(String(e)));
      }
    }));
  }

  // Failed fetches are kept for the call that met them (so it fails rather
  // than taking a blob for absent); a new action tries them again.
  forgetFailures() {
    for (const [ref, value] of this.held) if (value instanceof Error) this.held.delete(ref);
  }
}
