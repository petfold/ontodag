// node demo/freedom/test/test_freedom.mjs vectors.json feed_vector.json
// The page in Freedom Browser, through a stand-in for its window.swarm
// (freedom_standin.mjs): whole blobs read in one call, and your store
// published through Freedom's own node, its feed signed by the page's key.
// The trees are swarmfs's splitter's (make_vectors.py), so what the page
// uploads chunk by chunk is checked against the reference implementation.
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { FreedomStandIn } from "./freedom_standin.mjs";
import { ChunkReader, FreedomSwarm, Unreachable, hex, spanValue, topicOf, unhex } from "../swarm.js";
import { FreedomWriter, Key, Stage, feedUpdate, uploadStaged } from "../publish.js";

let failures = 0;
const check = (ok, what) => { console.log(`${ok ? "ok  " : "FAIL"} ${what}`); if (!ok) failures++; };
const sha = (data) => createHash("sha256").update(data).digest("hex");
const failing = async (action) => { try { await action(); return null; } catch (e) { return e; } };

const cases = JSON.parse(readFileSync(process.argv[2], "utf8"));
const vector = JSON.parse(readFileSync(process.argv[3], "utf8"));

// Each case's bytes, joined from the splitter's own chunks.
class SplitterSource {
  constructor(chunks) { this.chunks = chunks; }
  async readChunk(ref) {
    if (!(ref in this.chunks)) return null;
    const wire = unhex(this.chunks[ref]);
    return { span: spanValue(wire.subarray(0, 8)), payload: wire.slice(8) };
  }
}
for (const c of cases) c.data = await new ChunkReader(new SplitterSource(c.chunks)).bytes(c.root);

// A stand-in whose site is already connected; `approve` answers the prompts
// after that.
const connectedStandIn = async (options = {}) => {
  const freedom = new FreedomStandIn({ ...options, approve: () => true });
  await freedom.requestAccess();
  if (options.approve) freedom.approve = options.approve;
  freedom.calls.length = 0;
  freedom.prompts.length = 0;
  return freedom;
};

// ---------------------------------------------------------------- writing blobs

// A blob goes up as the chunks of its plain tree: afterwards Freedom's node
// holds exactly the splitter's chunks, byte for byte, the root included.
for (const c of cases.filter((c) => c.size > 0)) {
  const freedom = await connectedStandIn({ approve: () => "always" });
  const writer = new FreedomWriter(freedom);
  await writer.uploadBlob(c.data, null, c.root);
  const same = freedom.chunks.size === Object.keys(c.chunks).length
    && Object.entries(c.chunks).every(([address, wire]) => {
      const held = freedom.chunks.get(address);
      const w = unhex(wire);
      return held && held.span === spanValue(w.subarray(0, 8)) && hex(held.payload) === hex(w.subarray(8));
    });
  check(same && await writer.retrievable(c.root),
        `a ${c.size}-byte blob published through Freedom is the splitter's ${Object.keys(c.chunks).length} chunks`);
}

{
  const big = cases.find((c) => c.size === 600_000);
  const freedom = await connectedStandIn({ approve: () => "always" });
  const writer = new FreedomWriter(freedom);
  await writer.uploadBlob(big.data, null, big.root);
  const sent = freedom.count("swarm_publishChunk");
  await writer.uploadBlob(big.data, null, big.root);
  check(sent === Object.keys(big.chunks).length && freedom.count("swarm_publishChunk") === sent,
        `a chunk goes up once: ${sent} writes for ${Object.keys(big.chunks).length} chunks, none for the same blob again`);
  check(freedom.prompts.length === 1, "letting the site always publish makes it one prompt");
  check(await writer.retrievable("ab".repeat(32)) === false, "a blob that was not published is not called retrievable");
}

{
  // A large blob's chunks go up a few at a time, never more than the
  // writer allows in flight, and its root last.
  const big = cases.find((c) => c.size === 600_000);
  const freedom = await connectedStandIn({ approve: async () => { await new Promise((r) => setTimeout(r, 1)); return "always"; } });
  const writer = new FreedomWriter(freedom);
  freedom.always = true;
  freedom.request = ((real) => async (r) => { await new Promise((resolve) => setTimeout(resolve, 1)); return real(r); })(freedom.request.bind(freedom));
  await Promise.all([writer.uploadBlob(big.data, null, big.root), writer.uploadBlob(cases[5].data, null, cases[5].root)]);
  check(freedom.order.indexOf(big.root) > freedom.order.length - 4 && freedom.chunks.size === Object.keys(big.chunks).length + Object.keys(cases[5].chunks).length,
        "a large blob's root goes up after its other chunks");
  const few = new FreedomWriter(await connectedStandIn({ approve: () => "always" }), { inFlight: 3 });
  let most = 0, now = 0;
  few.swarm.request = ((real) => async (r) => {
    if (r.method !== "swarm_publishChunk") return real(r);
    most = Math.max(most, ++now);
    await new Promise((resolve) => setTimeout(resolve, 1));
    try { return await real(r); } finally { now--; }
  })(few.swarm.request.bind(few.swarm));
  await few.uploadBlob(big.data, null, big.root);
  check(most === 3, `at most the writer's ${3} writes are in flight (${most} seen)`);
}

{
  const empty = cases.find((c) => c.size === 0);
  const freedom = await connectedStandIn();
  const e = await failing(() => new FreedomWriter(freedom).uploadBlob(empty.data, null, empty.root));
  check(e && /empty/.test(e.message) && freedom.count("swarm_publishChunk") === 0, "an empty blob is refused before anything is asked");
}

{
  // A node that addresses a chunk otherwise is not believed.
  const one = cases.find((c) => c.size === 4096);
  const freedom = await connectedStandIn();
  const real = freedom.request.bind(freedom);
  freedom.request = async (r) => {
    const answer = await real(r);
    return r.method === "swarm_publishChunk" ? { reference: "ab".repeat(32) } : answer;
  };
  const writer = new FreedomWriter(freedom);
  const e = await failing(() => writer.uploadBlob(one.data, null, one.root));
  check(e && /Freedom addressed a chunk/.test(e.message) && await writer.retrievable(one.root) === false,
        "a chunk Freedom addressed otherwise fails the upload");
}

{
  // Many blobs at once: one write, and with it one prompt, until the first
  // has gone through.
  const small = cases.filter((c) => c.size > 0 && c.size <= 8192);
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  const freedom = await connectedStandIn({ approve: async () => { await held; return true; } });
  const writer = new FreedomWriter(freedom);
  const all = Promise.all(small.map((c) => writer.uploadBlob(c.data, null, c.root)));
  await new Promise((resolve) => setTimeout(resolve, 20));
  const before = [freedom.count("swarm_publishChunk"), freedom.mostWriting];
  release();
  await all;
  check(before[0] === 1 && before[1] === 1 && freedom.mostWriting > 1,
        `${small.length} blobs at once ask one write until the first is through, then several`);
}

{
  // The person says no to the first prompt: the writes waiting behind it
  // fail with it, and nothing asks again.
  const small = cases.filter((c) => c.size > 0 && c.size <= 8192);
  const freedom = await connectedStandIn({ approve: () => false });
  const writer = new FreedomWriter(freedom);
  const results = await Promise.all(small.map((c) => failing(() => writer.uploadBlob(c.data, null, c.root))));
  check(results.every((e) => e && /declined Freedom's prompt/.test(e.message)) && freedom.prompts.length === 1 && freedom.chunks.size === 0,
        "a declined prompt fails every waiting write, with one prompt and nothing published");
  freedom.approve = () => "always";
  await writer.uploadBlob(small[0].data, null, small[0].root);
  check(freedom.chunks.size > 0, "and publishing again asks again");
}

{
  // Each publish starts with one write alone (the page connects first),
  // so a person who approved once without "always" meets one prompt first
  // the next time too.
  const small = cases.filter((c) => c.size > 0 && c.size <= 8192);
  const waiting = [];
  const freedom = await connectedStandIn({ approve: () => new Promise((resolve) => waiting.push(resolve)) });
  const writer = new FreedomWriter(freedom);
  const first = writer.uploadBlob(small[0].data, null, small[0].root);
  await new Promise((resolve) => setTimeout(resolve, 10));
  waiting.shift()(true);
  await first;
  await writer.connect();
  const all = Promise.all(small.slice(1).map((c) => writer.uploadBlob(c.data, null, c.root)));
  await new Promise((resolve) => setTimeout(resolve, 10));
  const asked = waiting.length;
  while (freedom.chunks.size < small.reduce((n, c) => n + Object.keys(c.chunks).length, 0)) {
    while (waiting.length) waiting.shift()(true);
    await new Promise((resolve) => setTimeout(resolve, 1));
  }
  await all;
  check(asked === 1, `a second publish starts with one prompt again (${asked} waiting)`);
}

// What Freedom says when it cannot write, as a sentence.
for (const [options, pattern, what] of [
  [{ stamps: false }, /no postage with room/, "a node without postage"],
]) {
  const freedom = await connectedStandIn(options);
  const e = await failing(() => new FreedomWriter(freedom).uploadBlob(cases[1].data, null, cases[1].root));
  check(e && pattern.test(e.message), `${what} is said in words: ${e && e.message}`);
}
{
  const freedom = new FreedomStandIn();
  const writer = new FreedomWriter(freedom);
  const unconnected = await failing(() => writer.uploadBlob(cases[1].data, null, cases[1].root));
  check(unconnected && /not connected/.test(unconnected.message), "a site that has not connected is told so");
  await writer.connect();
  await writer.uploadBlob(cases[1].data, null, cases[1].root);
  check(freedom.chunks.has(cases[1].root), "after connecting it publishes");
  const refusing = new FreedomWriter(new FreedomStandIn({ approve: () => false }));
  const e = await failing(() => refusing.connect());
  check(e && /declined/.test(e.message), "a declined connection is said in words");
}

// ---------------------------------------------------------------- can it write at all

check(await FreedomWriter.unable(new FreedomStandIn()) === null, "a Freedom with the page-signed chunk call can publish");
check(/does not yet publish a chunk the page signed/.test(await FreedomWriter.unable(new FreedomStandIn({ pageSigned: false }))),
      "a Freedom without it says so");
check(/did not say/.test(await FreedomWriter.unable({ request: async () => { throw new Error("off"); } })),
      "a provider that is switched off says so");

// ---------------------------------------------------------------- the feed

const key = Key.fromText(vector.key);
const topic = vector.topic;
const rootAt = (i) => hex(Uint8Array.from({ length: 32 }, (_, k) => (i * 7 + k) & 0xff));

{
  const freedom = await connectedStandIn({ approve: () => "always" });
  const writer = new FreedomWriter(freedom);
  check(await writer.feedRoot(key.address, topic) === null, "an empty feed has no newest update");
  // The update swarmfs signs (feed_vector.json) is taken as it is.
  const update = feedUpdate(key, topic, vector.index, vector.root, vector.timestamp);
  check(update.signature === vector.signature, "the update is swarmfs's, byte for byte");
  for (let i = 0; i < vector.index; i++) await writer.writeFeed(feedUpdate(key, topic, i, rootAt(i), 1000 + i));
  await writer.writeFeed(update);
  const soc = freedom.socs.get(vector.address);
  check(soc && hex(soc.payload) === vector.data.slice(16) && soc.span === 40n,
        "Freedom holds the feed update at its address, as a chunk of the time and the root");
  const now = await writer.feedRoot(`0x${key.address}`, topic);
  check(now && now.index === vector.index && now.root === vector.root && now.timestamp === vector.timestamp,
        `the newest update read back: index ${now && now.index}`);
  const through = await new ChunkReader(new FreedomSwarm(freedom)).feedRoot(key.address, topic);
  check(through && through.root === vector.root && through.index === vector.index, "and by the page's reader");
}

{
  // Six updates. Freedom reports a chunk its node failed to fetch as
  // missing, so each way of finding the newest can come up short; the later
  // index of the two counts.
  const written = async (options) => {
    const freedom = await connectedStandIn({ approve: () => "always", ...options });
    const writer = new FreedomWriter(freedom);
    for (let i = 0; i < 6; i++) await writer.writeFeed(feedUpdate(key, topic, i, rootAt(i), 1000 + i));
    return [freedom, writer];
  };
  const [, plain] = await written();
  check((await plain.feedRoot(key.address, topic)).index === 5, "six updates: the newest is 5");
  const [lagging, behind] = await written({ lookupLag: 2 });
  check((await lagging.readFeedEntry({ topic, owner: key.address })).index === 3
        && (await behind.feedRoot(key.address, topic)).index === 5,
        "the node's lookup two updates short: probing still finds 5");
  const [blind, probing] = await written();
  blind.hidden.add((await feedUpdate(key, topic, 2, rootAt(2), 0)).address);
  check((await probing.feedRoot(key.address, topic)).index === 5,
        "a probe that misses update 2: the node's lookup still finds 5");
  const [gone, lost] = await written();
  gone.hidden.add(feedUpdate(key, topic, 5, rootAt(5), 0).address);
  gone.hidden.add(feedUpdate(key, topic, 4, rootAt(4), 0).address);
  const e = await failing(() => lost.feedRoot(key.address, topic));
  check(e && /could not be read/.test(e.message), "an update the lookup names but nothing can read is an error, not an older root");
}

{
  // A spent read budget while looking for the newest update is waited out;
  // one that never ends is an error, never "an empty feed".
  const freedom = await connectedStandIn({ approve: () => "always" });
  const writer = new FreedomWriter(freedom);
  writer.retry = { tries: 6, wait: 1, cap: 2 };
  for (let i = 0; i < 3; i++) await writer.writeFeed(feedUpdate(key, topic, i, rootAt(i), 1000 + i));
  freedom.limited = 3;
  const found = await writer.feedRoot(key.address, topic);
  check(found && found.index === 2 && freedom.limited === 0, "a spent read budget during the feed lookup is waited out");
  freedom.limited = 1000;
  const e = await failing(() => writer.feedRoot(key.address, topic));
  check(e && e.data && e.data.reason === "rate_limited", "a budget that stays spent is an error, not an empty feed");
}

{
  // What Freedom refuses: a chunk another key signed, a signature with the
  // recovery byte as 0 or 1, and an owner that is one of its own accounts.
  const freedom = await connectedStandIn({ approve: () => "always" });
  const writer = new FreedomWriter(freedom);
  const other = Key.generate();
  const forged = { ...feedUpdate(key, topic, 0, rootAt(0), 1000), signature: feedUpdate(other, topic, 0, rootAt(0), 1000).signature };
  const e1 = await failing(() => writer.writeFeed(forged));
  check(e1 && /invalid_signature/.test(e1.message) && freedom.socs.size === 0, "a feed update another key signed is refused, and nothing is stored");
  const good = feedUpdate(key, topic, 0, rootAt(0), 1000);
  const low = { ...good, signature: good.signature.slice(0, 128) + (parseInt(good.signature.slice(128), 16) - 27).toString(16).padStart(2, "0") };
  const e2 = await failing(() => writer.writeFeed(low));
  check(e2 && /invalid_signature/.test(e2.message), "a recovery byte of 0 or 1 is refused: the page signs with 27 or 28");
  const owning = await connectedStandIn({ approve: () => "always", own: [key.address] });
  const e3 = await failing(() => new FreedomWriter(owning).writeFeed(good));
  check(e3 && /one of Freedom's own wallet accounts/.test(e3.message), "a key that is one of Freedom's own accounts is refused in words");
  const old = await connectedStandIn({ pageSigned: false });
  const e4 = await failing(() => new FreedomWriter(old).writeFeed(good));
  check(e4 && /too old/.test(e4.message), "a Freedom without the call says it is too old");
}

// ---------------------------------------------------------------- a whole publish

{
  // The page's own order (app.js swarmPublish): stage, upload, then the
  // feed; and a second device reading it back through Freedom.
  const freedom = await connectedStandIn({ approve: () => "always" });
  const writer = new FreedomWriter(freedom);
  const stage = new Stage();
  const refs = cases.filter((c) => c.size > 0).map((c) => stage.put(c.data));
  check(refs.every((ref, i) => ref === cases.filter((c) => c.size > 0)[i].root), "the stage addresses each blob as the splitter does");
  const said = [];
  const sent = await uploadStaged(stage, writer, null, { progress: (t) => said.push(t) });
  check(sent === refs.length && stage.pending().length === 0 && said.length >= refs.length,
        `${sent} staged blobs uploaded and confirmed`);
  const root = refs[refs.length - 1];
  await writer.writeFeed(feedUpdate(key, topic, 0, root, 1_800_000_000));
  const reader = new ChunkReader(new FreedomSwarm(freedom));
  const feed = await reader.feedRoot(key.address, topic);
  const back = await Promise.all(refs.map((ref) => reader.bytes(ref)));
  check(feed.root === root && back.every((data, i) => sha(data) === cases.filter((c) => c.size > 0)[i].sha256),
        "another reader finds the feed's root and reads every blob back");
  check(await uploadStaged(stage, writer, null) === 0, "nothing is left to upload");
}

// ---------------------------------------------------------------- reading whole blobs

{
  const freedom = await connectedStandIn({ approve: () => "always" });
  const writer = new FreedomWriter(freedom);
  for (const c of cases.filter((c) => c.size > 0)) await writer.uploadBlob(c.data, null, c.root);
  freedom.calls.length = 0;
  const reader = new ChunkReader(new FreedomSwarm(freedom));
  let right = true;
  for (const c of cases.filter((c) => c.size > 0)) right = right && sha(await reader.bytes(c.root)) === c.sha256;
  const blobs = cases.filter((c) => c.size > 0).length;
  check(right && freedom.count("swarm_readData") === blobs && freedom.count("swarm_readChunk") === 0,
        `Freedom hands over whole blobs: ${blobs} blobs in ${freedom.count("swarm_readData")} reads, no chunk reads`);

  // A Freedom from before swarm_readData is asked once, then read chunk by chunk.
  const old = await connectedStandIn({ wholeBlobs: false });
  for (const [address, chunk] of freedom.chunks) old.chunks.set(address, chunk);
  const oldReader = new ChunkReader(new FreedomSwarm(old));
  right = true;
  for (const c of cases.filter((c) => c.size > 0)) right = right && sha(await oldReader.bytes(c.root)) === c.sha256;
  check(right && old.count("swarm_readData") === 1 && old.count("swarm_readChunk") === freedom.chunks.size,
        `a Freedom without whole blobs is asked once, then read as ${old.count("swarm_readChunk")} chunks`);

  // A blob larger than a site may read in one go is read as its chunks.
  const tight = await connectedStandIn({ byteBudget: 100_000 });
  for (const [address, chunk] of freedom.chunks) tight.chunks.set(address, chunk);
  const big = cases.find((c) => c.size === 600_000);
  const tightReader = new ChunkReader(new FreedomSwarm(tight));
  check(sha(await tightReader.bytes(big.root)) === big.sha256 && tight.count("swarm_readChunk") === Object.keys(big.chunks).length,
        "a blob over the read budget is read chunk by chunk");

  // What Freedom hands over is checked: wrong bytes are not taken.
  const lying = await connectedStandIn();
  for (const [address, chunk] of freedom.chunks) lying.chunks.set(address, chunk);
  lying.tamper = (data) => { const bad = data.slice(); bad[0] ^= 1; return bad; };
  const lyingReader = new ChunkReader(new FreedomSwarm(lying));
  check(sha(await lyingReader.bytes(big.root)) === big.sha256 && lyingReader.stats.unchecked === 1 && lying.count("swarm_readChunk") > 0,
        "a whole blob that does not check out is read chunk by chunk, every chunk checked");

  // A missing blob is unreachable, never empty.
  const missing = await failing(() => new ChunkReader(new FreedomSwarm(freedom)).bytes("cd".repeat(32)));
  check(missing instanceof Unreachable, "a blob Freedom's node cannot find is unreachable");

  // A spent read budget is waited out (two seconds), as for chunks.
  const busy = await connectedStandIn();
  for (const [address, chunk] of freedom.chunks) busy.chunks.set(address, chunk);
  busy.limited = 1;
  const waits = [];
  const busyReader = new ChunkReader(new FreedomSwarm(busy), { onRateLimit: (ms) => waits.push(ms) });
  check(sha(await busyReader.bytes(big.root)) === big.sha256 && waits.length === 1 && busy.count("swarm_readData") === 2,
        "a whole-blob read refused for the budget waits and asks again");
}

check(topicOf(vector.name) === vector.topic, "the vector's topic");
process.exit(failures ? 1 : 0);
