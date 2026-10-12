// node demo/freedom/test/test_publish.mjs feed_vector.json [vectors.json]
// Checks publish.js against swarmfs: a feed update signed in the page must
// be byte for byte the one swarmfs (libsecp256k1) signs, so a feed the page
// writes reads as one odag wrote; and, given make_vectors.py's trees, a
// blob's address computed in the page must be the splitter's.
import { readFileSync } from "node:fs";
import { Key, Stage, feedUpdate, signerOf } from "../publish.js";
import { chunkAddress, contentAddress, hex, topicOf, unhex } from "../swarm.js";

let failures = 0;
const check = (ok, what) => { console.log(`${ok ? "ok  " : "FAIL"} ${what}`); if (!ok) failures++; };

const v = JSON.parse(readFileSync(process.argv[2], "utf8"));
const key = Key.fromText(v.key);
check(key.address === v.owner, "the key's address");
check(topicOf(v.name) === v.topic, "the feed's topic from its name");
const update = feedUpdate(key, v.topic, v.index, v.root, v.timestamp);
check(update.identifier === v.identifier, "the update's identifier");
check(hex(update.data) === v.data, "the update's chunk (span, time, root)");
check(update.signature === v.signature, "the signature, byte for byte libsecp256k1's");
check(update.address === v.address, "the update's address");
check(signerOf(update.identifier, chunkAddress(40, update.data.subarray(8)), update.signature) === v.owner,
      "the signature recovers to the owner");
const other = Key.generate();
check(signerOf(update.identifier, chunkAddress(40, update.data.subarray(8)),
               feedUpdate(other, v.topic, v.index, v.root, v.timestamp).signature) !== v.owner,
      "another key's signature does not");
check(Key.fromText(`0x${v.key}\n`).address === v.owner && Key.fromText(key.text()).address === v.owner,
      "a key file read back");
for (const bad of ["", "0x12", "hello", "11".repeat(33)]) {
  let refused = false;
  try { Key.fromText(bad); } catch { refused = true; }
  check(refused, `not a key file: ${JSON.stringify(bad.slice(0, 12))}`);
}
check(/^0x[0-9a-fA-F]{40}$/.test(key.checksummed) && key.checksummed.toLowerCase() === `0x${v.owner}`,
      "the address with its checksum capitals");

if (process.argv[3]) {
  for (const c of JSON.parse(readFileSync(process.argv[3], "utf8"))) {
    // the tree's leaves, in order, are the blob: rebuild it from the chunks
    const leaves = [];
    const walk = (ref) => {
      const w = unhex(c.chunks[ref]);
      const span = Number(new DataView(w.buffer, w.byteOffset).getBigUint64(0, true));
      if (span <= 4096) { leaves.push(w.subarray(8, 8 + span)); return; }
      for (let i = 8; i < w.length; i += 32) walk(hex(w.subarray(i, i + 32)));
    };
    walk(c.root);
    const blob = new Uint8Array(leaves.reduce((n, l) => n + l.length, 0));
    let at = 0;
    for (const l of leaves) { blob.set(l, at); at += l.length; }
    check(contentAddress(blob) === c.root, `address of a ${c.size}-byte blob`);
  }
  const stage = new Stage();
  const blob = new Uint8Array(5000).fill(7);
  const ref = stage.put(blob);
  check(stage.get(ref).length === 5000 && stage.get("00".repeat(32)) === undefined, "the stage keeps what it addressed");
  check(stage.pending().length === 1 && (stage.confirm(ref), stage.pending().length === 0), "the stage forgets nothing until confirmed");
}
process.exit(failures ? 1 : 0);
