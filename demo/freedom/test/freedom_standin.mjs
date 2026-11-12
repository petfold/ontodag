// A stand-in for Freedom Browser's window.swarm, in memory, for tests: the
// calls the page makes, answered with the shapes, checks and refusals of
// Freedom's own handlers (docs/swarm-provider-api.md and
// src/main/swarm/{swarm-provider-ipc,chunk-service}.js there, read at
// e17c9d01, the nightly of 2026-11-12). It keeps chunks in a Map instead of
// a node, and its prompts are answered by `approve`.
import { keccak_256 } from "../vendor/noble-hashes/sha3.js";
import { secp256k1 } from "../vendor/noble-curves/secp256k1.js";
import { CHUNK_SIZE, chunkAddress, feedIdentifier, hex, socAddress, unhex } from "../swarm.js";

const utf8 = new TextEncoder();
const ETH_PREFIX = utf8.encode("\x19Ethereum Signed Message:\n32");

function concat(parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
}

const base64 = (bytes) => Buffer.from(bytes).toString("base64");

function refusal(code, message, reason, more = {}) {
  const e = new Error(message);
  e.code = code;
  if (reason) e.data = { reason, ...more };
  return e;
}

const invalid = (message, reason = "invalid_params", more) => refusal(-32602, message, reason, more);
const isHex = (s, bytes) => typeof s === "string" && new RegExp(`^[0-9a-fA-F]{${2 * bytes}}$`).test(s);

function checksummed(address) {
  const nibbles = hex(keccak_256(utf8.encode(address)));
  return "0x" + [...address].map((c, i) => (parseInt(nibbles[i], 16) >= 8 ? c.toUpperCase() : c)).join("");
}

export class FreedomStandIn {
  constructor({
    pageSigned = true,          // false: a Freedom from before the page-signed chunk call
    wholeBlobs = true,          // false: one from before swarm_readData
    stamps = true,              // false: the node has no usable postage
    own = [],                   // addresses of Freedom's own wallet accounts
    approve = () => true,       // answers a prompt: ("connect" | "publish", details) -> true, false, or "always"
    byteBudget = 5 * 2 ** 20,   // what a connected site may read in a minute
    lookupLag = 0,              // the node's feed lookup reports this many updates short
  } = {}) {
    Object.assign(this, { pageSigned, wholeBlobs, stamps, approve, byteBudget, lookupLag });
    this.own = new Set(own.map((a) => a.replace(/^0x/, "").toLowerCase()));
    this.isFreedomBrowser = true;
    this.connected = false;
    this.always = false;
    this.chunks = new Map();    // address -> { span: BigInt, payload }
    this.socs = new Map();      // address -> { owner, identifier, signature, span, payload }
    this.hidden = new Set();    // addresses the node fails to find, as a light node sometimes does
    this.limited = 0;           // reads to answer "rate_limited" before answering
    this.calls = [];            // every method asked, in order
    this.order = [];            // the chunks published, in the order they arrived
    this.prompts = [];
    this.writing = 0;
    this.mostWriting = 0;
  }

  count(method) { return this.calls.filter((m) => m === method).length; }

  requestAccess() { return this.request({ method: "swarm_requestAccess" }); }
  readChunk(params) { return this.request({ method: "swarm_readChunk", params }); }
  readSingleOwnerChunk(params) { return this.request({ method: "swarm_readSingleOwnerChunk", params }); }
  readFeedEntry(params) { return this.request({ method: "swarm_readFeedEntry", params }); }

  async request({ method, params = {} }) {
    this.calls.push(method);
    await Promise.resolve();
    const handler = {
      swarm_getCapabilities: () => this._capabilities(),
      swarm_requestAccess: () => this._connect(),
      swarm_readChunk: () => this._readChunk(params),
      swarm_readData: () => this._readData(params),
      swarm_readSingleOwnerChunk: () => this._readSoc(params),
      swarm_readFeedEntry: () => this._readFeedEntry(params),
      swarm_publishChunk: () => this._publish(() => this._publishChunk(params), { type: "Chunk" }),
      swarm_publishSingleOwnerChunk: this.pageSigned
        ? () => this._publish(() => this._publishSoc(params), { type: "Single Owner Chunk", owner: params.owner })
        : undefined,
    }[method];
    if (!handler || (method === "swarm_readData" && !this.wholeBlobs)) {
      throw refusal(4200, `Unknown method: ${method}`);
    }
    return handler();
  }

  _capabilities() {
    return {
      specVersion: "1.0",
      canPublish: this.connected && this.stamps,
      reason: !this.connected ? "not-connected" : this.stamps ? null : "no-usable-stamps",
      extensions: this.pageSigned ? { publisherSigning: true, pageSignedSingleOwnerChunks: true } : { publisherSigning: true },
      limits: { maxChunkPayloadBytes: CHUNK_SIZE },
    };
  }

  async _prompt(kind, details) {
    this.prompts.push(kind);
    const answer = await this.approve(kind, details);
    if (!answer) throw refusal(4001, "User rejected the request");
    return answer;
  }

  async _connect() {
    if (!this.connected) {
      await this._prompt("connect");
      this.connected = true;
    }
    return { connected: true, origin: "stand-in", capabilities: ["publish"] };
  }

  // The publish tier: the connection, then the prompt unless the site may
  // always publish, then the write.
  async _publish(write, details) {
    if (!this.connected) throw refusal(4100, "Origin not authorized", "not_connected");
    this.writing++;
    this.mostWriting = Math.max(this.mostWriting, this.writing);
    try {
      if (!this.always && (await this._prompt("publish", details)) === "always") this.always = true;
      return write();
    } finally {
      this.writing--;
    }
  }

  _payload(data) {
    const bytes = typeof data === "string" ? utf8.encode(data)
      : data instanceof ArrayBuffer ? new Uint8Array(data)
      : data instanceof Uint8Array ? data : null;
    if (!bytes) throw invalid("data must be a string, Uint8Array or ArrayBuffer");
    if (bytes.length < 1 || bytes.length > CHUNK_SIZE) {
      throw invalid("data must be 1-4096 bytes", "payload_too_large", { limit: CHUNK_SIZE, actual: bytes.length });
    }
    return bytes.slice();
  }

  _span(span, payload) {
    if (span === undefined || span === null) return BigInt(payload.length);
    if (typeof span === "bigint" ? span < 0n : !Number.isSafeInteger(span) || span < 0) {
      throw invalid("span must be a non-negative unsigned 64-bit integer", "invalid_span");
    }
    return BigInt(span);
  }

  _ready() {
    if (!this.stamps) throw refusal(4900, "Node not available: no-usable-stamps", "no-usable-stamps");
  }

  _publishChunk({ data, span, options }) {
    if (options !== undefined && Object.keys(options).length) throw invalid("unsupported option", "unsupported_option");
    const payload = this._payload(data);
    const s = this._span(span, payload);
    this._ready();
    const reference = chunkAddress(s, payload);
    this.chunks.set(reference, { span: s, payload });
    this.order.push(reference);
    return { reference };
  }

  // As chunk-service.publishSignedSingleOwnerChunk checks it: a recovery
  // byte of 27 or 28, and a signature that recovers to `owner` over the
  // Ethereum signed-message digest of keccak256(identifier || the address
  // of the content chunk built from span and data). The owner must not be
  // one of Freedom's own accounts.
  _publishSoc({ owner, identifier, signature, data, span, options }) {
    if (options !== undefined && Object.keys(options).length) throw invalid("unsupported option", "unsupported_option");
    const o = String(owner || "").replace(/^0x/, "");
    if (!isHex(o, 20)) throw invalid("owner must be a valid 40-character hex address", "invalid_owner");
    if (!isHex(identifier, 32)) throw invalid("identifier must be 32 bytes of hex", "invalid_identifier");
    const sig = String(signature || "").replace(/^0x/, "");
    if (!isHex(sig, 65)) throw invalid("signature must be 65 bytes of hex", "invalid_signature");
    const payload = this._payload(data);
    const s = this._span(span, payload);
    if (this.own.has(o.toLowerCase())) {
      throw refusal(4100, "The owner is one of Freedom's own identities", "freedom_identity");
    }
    this._ready();
    const bytes = unhex(sig);
    const v = bytes[64];
    if (v !== 27 && v !== 28) throw invalid("signature must end in a recovery byte of 27 or 28", "invalid_signature");
    const digest = keccak_256(concat([ETH_PREFIX, keccak_256(concat([unhex(identifier), unhex(chunkAddress(s, payload))]))]));
    let signer = null;
    try {
      const point = secp256k1.Signature.fromCompact(bytes.subarray(0, 64)).addRecoveryBit(v - 27).recoverPublicKey(digest);
      signer = hex(keccak_256(point.toRawBytes(false).subarray(1)).subarray(12));
    } catch { /* not a signature at all */ }
    if (signer !== o.toLowerCase()) {
      throw invalid("The signature does not recover to owner for this identifier and chunk", "invalid_signature");
    }
    const reference = socAddress(identifier, o);
    this.socs.set(reference, { owner: o.toLowerCase(), identifier: identifier.toLowerCase(), signature: sig.toLowerCase(), span: s, payload });
    return { reference, owner: checksummed(o.toLowerCase()), identifier: identifier.toLowerCase() };
  }

  _read() {
    if (this.limited > 0) {
      this.limited--;
      throw invalid("Read budget exceeded", "rate_limited", { windowMs: 60000 });
    }
  }

  _readChunk({ reference }) {
    if (!isHex(reference, 32)) throw invalid("reference must be 32 bytes of hex", "invalid_reference");
    this._read();
    const ref = reference.toLowerCase();
    if (this.socs.has(ref)) throw invalid("not a content-addressed chunk", "chunk_type_mismatch");
    const chunk = this.chunks.get(ref);
    if (!chunk || this.hidden.has(ref)) throw invalid(`Chunk not found: ${ref}`, "chunk_not_found");
    return { data: base64(chunk.payload), encoding: "base64", span: Number(chunk.span) };
  }

  _join(ref) {
    const chunk = this.chunks.get(ref);
    if (!chunk || this.hidden.has(ref)) throw invalid(`Data not found: ${ref}`, "chunk_not_found");
    if (chunk.span <= BigInt(CHUNK_SIZE)) return chunk.payload.slice(0, Number(chunk.span));
    const parts = [];
    for (let at = 0; at < chunk.payload.length; at += 32) parts.push(this._join(hex(chunk.payload.subarray(at, at + 32))));
    return concat(parts);
  }

  _readData({ reference }) {
    if (!isHex(reference, 32)) throw invalid("reference must be 32 bytes of hex", "invalid_reference");
    this._read();
    const ref = reference.toLowerCase();
    const root = this.chunks.get(ref);
    if (!root || this.hidden.has(ref)) throw invalid(`Data not found: ${ref}`, "chunk_not_found");
    if (root.span > BigInt(this.byteBudget)) {
      throw invalid("Data is larger than this site may read", "data_too_large", { limit: this.byteBudget, actual: Number(root.span) });
    }
    return { data: base64(this.tamper ? this.tamper(this._join(ref)) : this._join(ref)), encoding: "base64" };
  }

  _readSoc({ owner, identifier }) {
    this._read();
    const o = String(owner || "").replace(/^0x/, "").toLowerCase();
    if (!isHex(o, 20)) throw invalid("owner must be a valid 40-character hex address", "invalid_owner");
    if (!isHex(identifier, 32)) throw invalid("identifier must be 32 bytes of hex", "invalid_identifier");
    const reference = socAddress(identifier, o);
    const soc = this.socs.get(reference);
    if (!soc || this.hidden.has(reference)) throw invalid("Single Owner Chunk not found", "chunk_not_found");
    return {
      data: base64(soc.payload), encoding: "base64", span: Number(soc.span), reference,
      owner: checksummed(soc.owner), identifier: soc.identifier, signature: soc.signature,
    };
  }

  // The node's own lookup of a feed's newest entry.
  _readFeedEntry({ topic, owner }) {
    this._read();
    const o = String(owner || "").replace(/^0x/, "").toLowerCase();
    let newest = -1;
    while (this.socs.has(socAddress(feedIdentifier(topic, newest + 1), o))) newest++;
    newest -= this.lookupLag;
    if (newest < 0) throw invalid("Feed is empty", "feed_empty");
    const soc = this.socs.get(socAddress(feedIdentifier(topic, newest), o));
    return { data: base64(soc.payload), encoding: "base64", index: newest, nextIndex: newest + 1 };
  }
}
