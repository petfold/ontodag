// Writing your store to Swarm from the page, the way `odag -f swarm:NAME`
// does it (docs/plans/BROWSER.md §16): blobs uploaded plain (no erasure
// coding, so every reference is the one the page computed), checked
// retrievable, and only then the store's feed pointed at the new root, in
// recordstore's feed format, signed by the person's key.
//
// For now the key is a random one in a plain file the person keeps (the
// `bee_signer` value odag keeps in its config), and the node that served the
// page pays from its batches (BROWSER.md §14.3, questions 37 and 38). Later
// an identity carries that same key; nothing here changes owner then.

import { keccak_256 } from "./vendor/noble-hashes/sha3.js";
import { secp256k1 } from "./vendor/noble-curves/secp256k1.js";
import {
  HttpSwarm, chunkAddress, contentAddress, feedIdentifier, hex, socAddress, spanBytes, unhex,
} from "./swarm.js";

const utf8 = new TextEncoder();
const ETH_PREFIX = utf8.encode("\x19Ethereum Signed Message:\n32");

function concat(parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
}

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---------------------------------------------------------------- the key

// A secp256k1 key. It never leaves the page's memory except as the file the
// person asked for; the page shows only its address.
export class Key {
  constructor(secret) {
    if (!secp256k1.utils.isValidPrivateKey(secret)) throw new Error("not a secp256k1 key");
    this._secret = secret;
    const uncompressed = secp256k1.getPublicKey(secret, false);
    this.address = hex(keccak_256(uncompressed.subarray(1)).subarray(12));
  }

  static generate() {
    return new Key(secp256k1.utils.randomPrivateKey());
  }

  // A key file's text: the key as 64 hex digits, with or without 0x.
  static fromText(text) {
    const s = String(text).trim();
    if (!/^(0x)?[0-9a-fA-F]{64}$/.test(s)) {
      throw new Error("not a key file: it should hold one key, 64 hex digits");
    }
    return new Key(unhex(s));
  }

  text() {
    return `0x${hex(this._secret)}\n`;
  }

  // The address with EIP-55 capitals, for showing.
  get checksummed() {
    const nibbles = hex(keccak_256(utf8.encode(this.address)));
    return "0x" + [...this.address].map((c, i) => (parseInt(nibbles[i], 16) >= 8 ? c.toUpperCase() : c)).join("");
  }

  // r || s || v (v 27 or 28) over the Ethereum signed-message digest of a
  // 32-byte digest: what Bee checks on a single-owner chunk.
  signDigest(digest32) {
    const sig = secp256k1.sign(keccak_256(concat([ETH_PREFIX, digest32])), this._secret, { lowS: true });
    return concat([sig.toCompactRawBytes(), Uint8Array.of(27 + sig.recovery)]);
  }

  // r || s || v (v 0 or 1) over a bare 32-byte hash, as loopmarket signs an
  // offer id (its sigs.py), recoverable to this key's address.
  signHash(hash32) {
    const sig = secp256k1.sign(hash32, this._secret, { lowS: true });
    return concat([sig.toCompactRawBytes(), Uint8Array.of(sig.recovery)]);
  }
}

// The owner a feed update's signature recovers to, or null.
export function signerOf(identifier, cacAddress, signature) {
  try {
    const sig = unhex(signature);
    const digest = keccak_256(concat([ETH_PREFIX, keccak_256(concat([unhex(identifier), unhex(cacAddress)]))]));
    const point = secp256k1.Signature.fromCompact(sig.subarray(0, 64)).addRecoveryBit(sig[64] - 27).recoverPublicKey(digest);
    return hex(keccak_256(point.toRawBytes(false).subarray(1)).subarray(12));
  } catch {
    return null;
  }
}

// A feed update in recordstore's format (swarmfs FeedOps.update): the payload
// is the time in seconds (8 bytes, big-endian) and the root, wrapped in a
// content chunk, signed as a single-owner chunk at the feed's identifier.
export function feedUpdate(key, topic, index, root, timestamp) {
  const payload = new Uint8Array(40);
  let t = BigInt(timestamp);
  for (let i = 7; i >= 0; i--) { payload[i] = Number(t & 0xffn); t >>= 8n; }
  payload.set(unhex(root), 8);
  const identifier = feedIdentifier(topic, index);
  const cac = chunkAddress(40, payload);
  const signature = hex(key.signDigest(keccak_256(concat([unhex(identifier), unhex(cac)]))));
  return {
    owner: key.address, identifier, signature,
    data: concat([spanBytes(40), payload]),
    address: socAddress(identifier, key.address),
  };
}

// ---------------------------------------------------------------- staging

// The blobs a publish writes, kept until they are uploaded and seen
// retrievable. Python's StagedBlobs calls put and get synchronously, so
// writing needs no bridge (in retry mode either).
export class Stage {
  constructor() { this.kept = new Map(); }

  put(data) {
    const bytes = new Uint8Array(data);
    const ref = contentAddress(bytes);
    if (!this.kept.has(ref)) this.kept.set(ref, { bytes, confirmed: false });
    return ref;
  }

  get(ref) {
    const kept = this.kept.get(String(ref));
    return kept ? kept.bytes : undefined;
  }

  // Everything not yet seen retrievable: a root may reach blobs a failed
  // publish staged, so each publish sends all of them.
  pending() {
    return [...this.kept].filter(([, k]) => !k.confirmed).map(([ref, k]) => ({ ref, bytes: k.bytes }));
  }

  confirm(ref) {
    const kept = this.kept.get(ref);
    if (kept) kept.confirmed = true;
  }
}

// ---------------------------------------------------------------- the node

// A Bee node over HTTP, as odag reaches it: its batches pay, and its
// /stewardship says whether the network serves what was uploaded.
export class NodeWriter {
  constructor(base) {
    this.base = base.replace(/\/+$/, "");
    this.http = new HttpSwarm(this.base);
    this.retry = { tries: 15, wait: 500, cap: 5000 };
  }

  // The node's usable batches, the longest-lived first; null if this is
  // not a node with batches (a gateway, say).
  async batches() {
    let res;
    try { res = await fetch(`${this.base}/stamps`); } catch { return null; }
    if (!res.ok) return null;
    let body;
    try { body = await res.json(); } catch { return null; }
    if (!body || !Array.isArray(body.stamps)) return null;
    return body.stamps
      .filter((s) => s.usable && s.exists !== false)
      .map((s) => ({
        id: s.batchID, label: s.label || "", depth: s.depth, ttl: Number(s.batchTTL),
        full: Number(s.utilization) / 2 ** (s.depth - s.bucketDepth), immutable: s.immutableFlag,
      }))
      .sort((a, b) => b.ttl - a.ttl);
  }

  async uploadBlob(bytes, batch, ref) {
    const res = await fetch(`${this.base}/bytes`, {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "Swarm-Postage-Batch-Id": batch,
        "Swarm-Redundancy-Level": "0",
        "Swarm-Deferred-Upload": "false",
      },
      body: bytes,
    });
    if (!res.ok) throw new Error(`uploading a blob: HTTP ${res.status} ${(await res.text()).slice(0, 200)}`);
    const got = (await res.json()).reference;
    if (got !== ref) throw new Error(`the node addressed a blob ${got.slice(0, 16)}… that the page addressed ${ref.slice(0, 16)}…`);
  }

  async retrievable(ref) {
    try {
      const res = await fetch(`${this.base}/stewardship/${ref}`);
      return res.ok && (await res.json()).isRetrievable === true;
    } catch {
      return false;
    }
  }

  // A single-owner chunk, or null if there is none. A light node answers
  // 500 as well as 404 for a chunk it could not find, for seconds at a
  // time and at once while it remembers the failed retrieval, so a 500 is
  // asked again with SwarmFeedPointer's budget (15 tries, the wait doubling
  // from 0.5 s to 5 s, about a minute) and raised only once that is spent:
  // taken for "none", it could make the page write over an update that
  // exists.
  async _signed(owner, identifier) {
    const { tries, wait: first, cap } = this.retry;
    for (let attempt = 1, wait = first; ; attempt++, wait = Math.min(wait * 2, cap)) {
      try {
        return await this.http.readSignedChunk(owner, identifier);
      } catch (e) {
        if (attempt >= tries) throw e;
        await pause(wait);
      }
    }
  }

  // The newest update of a sequence feed ({index, root, timestamp}), or
  // null for an empty feed. Found by probing the updates themselves, as
  // recordstore's SwarmFeedPointer does (the node's /feeds lookup is
  // unreliable on a light node), and checked: the signature must recover
  // to the owner.
  async feedRoot(owner, topic) {
    owner = owner.replace(/^0x/, "").toLowerCase();
    const at = async (i) => this._signed(owner, feedIdentifier(topic, i));
    if (!(await at(0))) return null;
    let lo = 0, hi = 1;
    while (await at(hi)) { lo = hi; hi *= 2; }
    while (hi - lo > 1) {
      const mid = Math.floor((lo + hi) / 2);
      if (await at(mid)) lo = mid; else hi = mid;
    }
    const identifier = feedIdentifier(topic, lo);
    const soc = await at(lo);
    const payload = soc.payload.slice(0, Number(soc.span));
    if (payload.length !== 40) throw new Error(`feed update of ${payload.length} bytes, not a time and a root`);
    if (signerOf(identifier, chunkAddress(soc.span, soc.payload), soc.signature) !== owner) {
      throw new Error(`feed update ${lo} is not signed by ${owner}`);
    }
    let timestamp = 0n;
    for (const b of payload.subarray(0, 8)) timestamp = (timestamp << 8n) | BigInt(b);
    return { index: lo, root: hex(payload.subarray(8)), timestamp: Number(timestamp) };
  }

  async writeFeed(update, batch) {
    const res = await fetch(`${this.base}/soc/${update.owner}/${update.identifier}?sig=${update.signature}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "Swarm-Postage-Batch-Id": batch,
        "Swarm-Deferred-Upload": "false",
      },
      body: update.data,
    });
    if (!res.ok) throw new Error(`writing the feed update: HTTP ${res.status} ${(await res.text()).slice(0, 200)}`);
    const got = (await res.json()).reference;
    if (got !== update.address) throw new Error(`the node stored the feed update at ${got.slice(0, 16)}…, not ${update.address.slice(0, 16)}…`);
  }
}

// Upload what the stage holds and wait until the network serves all of it.
// `progress(text)` is told how far it got. Throws if something is still not
// retrievable after `minutes`: the feed must not point at what the network
// cannot serve.
export async function uploadStaged(stage, writer, batch, { progress = () => {}, minutes = 3, inFlight = 8 } = {}) {
  const pending = stage.pending();
  let sent = 0;
  const queue = [...pending];
  await Promise.all(Array.from({ length: Math.min(inFlight, queue.length) }, async () => {
    for (let item = queue.shift(); item; item = queue.shift()) {
      await writer.uploadBlob(item.bytes, batch, item.ref);
      progress(`uploaded ${++sent} of ${pending.length} blobs`);
    }
  }));
  const deadline = Date.now() + minutes * 60_000;
  let open = pending.map((p) => p.ref);
  for (let wait = 1000; open.length; wait = Math.min(wait * 2, 15_000)) {
    const results = await Promise.all(open.map(async (ref) => [ref, await writer.retrievable(ref)]));
    for (const [ref, ok] of results) if (ok) stage.confirm(ref);
    open = results.filter(([, ok]) => !ok).map(([ref]) => ref);
    if (!open.length) break;
    progress(`${pending.length - open.length} of ${pending.length} blobs retrievable; waiting for the rest`);
    if (Date.now() > deadline) {
      throw new Error(`${open.length} of ${pending.length} blobs are not retrievable yet, so the feed was not moved; publish again in a while`);
    }
    await pause(wait);
  }
  return pending.length;
}
