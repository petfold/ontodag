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
// Read-only for now: writing waits for the page-signed chunk Freedom has been
// asked for (freedom-browser#647) and for the user's key (BROWSER.md §11).

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

// Checked chunks, cached for the session (a chunk never changes), with a cap
// on reads in flight and a wait-and-retry when a client says "too many".
export class ChunkReader {
  constructor(source, { inFlight = 16, onRateLimit = () => {} } = {}) {
    this.source = source;
    this.cache = new Map();
    this.gate = new Gate(inFlight);
    this.onRateLimit = onRateLimit;
    this.stats = { reads: 0, cached: 0, bytes: 0, waits: 0 };
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
        return got;
      }
    } finally {
      this.gate.leave();
    }
  }

  // The bytes of a blob: its chunk tree joined, every chunk checked.
  async bytes(ref) {
    const { span, payload } = await this.chunk(ref);
    if (span > 0xffffffffffffffn) {
      throw new Error(`${ref.slice(0, 16)}… is erasure-coded, which this page does not read`);
    }
    if (span <= BigInt(CHUNK_SIZE)) return payload.slice(0, Number(span));
    if (payload.length % 32) throw new Error(`intermediate chunk ${ref.slice(0, 16)}… of ${payload.length} bytes`);
    const children = [];
    for (let i = 0; i < payload.length; i += 32) children.push(hex(payload.subarray(i, i + 32)));
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
  constructor(reader) { this.reader = reader; }
  download(ref) { return this.reader.bytes(String(ref)); }
  downloadMany(refs) { return Promise.all(Array.from(refs, (r) => this.download(r))); }
  async upload() { throw new Error("this page reads Swarm; it does not write"); }
}
