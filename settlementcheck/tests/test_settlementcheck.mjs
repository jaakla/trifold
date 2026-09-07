import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { inflateSync, deflateSync } from "node:zlib";
import { CLASSES, SettlementCheck, DetailsNotLoadedError } from "../js/settlementcheck.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const raw = new Uint8Array(await readFile(join(here, "fixture_L2.tfdg")));
const points = JSON.parse(await readFile(join(here, "points.json"), "utf8"));
let reads = 0;
const loader = async face => {
  reads++;
  return readFile(join(here, "fixture_L2.details", "face-" + String(face).padStart(2, "0") + ".tfdd"));
};
const sc = await SettlementCheck.fromBytes(raw, { detailsLoader: loader, cacheFaces: 1 });
for (const p of points) {
  const r = sc.classify(p.lon, p.lat);
  assert.equal(r.code, p.code);
  assert.equal(r.detailsLoaded, false);
  assert.equal(r.mixed, null);
  assert.equal(r.nodataMixed, null);
  assert.equal(r.classShare, null);
  assert.equal(sc.classCode(p.lon, p.lat), p.code);
  assert.equal(sc.settlement(p.lon, p.lat), p.code === null ? null : CLASSES[p.code].settlementClass);
  assert.equal(sc.isUrban(p.lon, p.lat), p.code === null ? null : [21,22,23,30].includes(p.code));
}
assert.equal(reads, 0);
const p = points[0];
assert.throws(() => sc.check(p.lon, p.lat), DetailsNotLoadedError);
await Promise.all([sc.checkAsync(p.lon, p.lat), sc.checkAsync(p.lon, p.lat)]);
assert.equal(reads, 1, "concurrent same-face loads are deduplicated");
assert.equal(sc.check(p.lon, p.lat).surface, "water");
for (const p of points) {
  const result = await sc.checkAsync(p.lon, p.lat);
  assert.equal(result.detailsLoaded, true);
  assert.equal(result.code, p.code);
  assert.equal(result.mixed, p.mixed);
  assert.equal(result.nodataMixed, p.index === 24 || p.index === 26);
  if (p.index === 23) {
    assert.equal(result.surface, "mixed");
    assert.equal(result.classShare, 0.6);
  }
  if (p.code === null) assert.equal(result.classShare, null);
  assert.ok(sc.stats.detailsFaces.length <= 1);
}
assert.deepEqual(await sc.checkBatchAsync(points.map(p=>p.lon), points.map(p=>p.lat)),
                 await Promise.all(points.map(p=>sc.checkAsync(p.lon,p.lat))));
sc.unloadDetails();
assert.deepEqual(sc.stats.detailsFaces, []);
assert.equal(sc.settlementBatch([p.lon], [p.lat])[0], "water");
assert.throws(() => sc.checkBatch([0, 1], [0]), /same length/);
await assert.rejects(() => sc.checkBatchAsync([0, 1], [0]), /same length/);
assert.throws(() => sc.classCode(181, 0), /longitude/);
await assert.rejects(() => SettlementCheck.fromBytes(raw.subarray(0,20)), /truncated/);
for (const [offset, value] of [[0,0], [4,2], [6,0], [6,1], [7,1], [5,14]]) {
  const bad = raw.slice(); bad[offset] = value;
  await assert.rejects(() => SettlementCheck.fromBytes(bad));
}
let attempts = 0;
const retry = await SettlementCheck.fromBytes(raw, { detailsLoader: async face => {
  const bytes = new Uint8Array(await loader(face));
  if (attempts++ === 0) bytes[60] ^= 1;
  return bytes;
}});
await assert.rejects(() => retry.checkAsync(p.lon,p.lat), /match/);
assert.deepEqual(retry.stats.detailsFaces, []);
assert.equal((await retry.checkAsync(p.lon,p.lat)).code, 10);
assert.equal(attempts, 2);
const unavailable = await SettlementCheck.fromBytes(raw);
await assert.rejects(() => unavailable.checkAsync(p.lon,p.lat), DetailsNotLoadedError);
assert.equal(unavailable.classCode(p.lon,p.lat), 10);
function repack(raw, index, mutate, trailing = false) {
  raw = Buffer.from(raw);
  const count = raw.toString('ascii', 0, 4) === 'TFDG' ? 2 : 4;
  let position = 92 + 8 * count;
  const blocks = [];
  for (let i = 0; i < count; i++) {
    const size = raw.readUInt32LE(92 + 8 * i);
    blocks.push(inflateSync(raw.subarray(position, position + size))); position += size;
  }
  blocks[index] = mutate(blocks[index]);
  const packed = blocks.map(b => deflateSync(b));
  if (trailing) packed[index] = Buffer.concat([packed[index], Buffer.from('junk')]);
  const header = Buffer.from(raw.subarray(0, 92)), directory = Buffer.alloc(8 * count);
  header.writeUInt32LE(blocks.reduce((n, b) => n + b.length, 0), 24);
  for (let i = 0; i < count; i++) {
    directory.writeUInt32LE(packed[i].length, 8 * i);
    directory.writeUInt32LE(blocks[i].length, 8 * i + 4);
  }
  return Buffer.concat([header, directory, ...packed]);
}
for (const [index, value] of [[0, 0], [1, 9]]) {
  await assert.rejects(() => SettlementCheck.fromBytes(repack(raw, index, b => {b[0] = value; return b;})));
}
await assert.rejects(() => SettlementCheck.fromBytes(repack(raw, 0, b => b, true)));
const badPadding = repack(await loader(1), 2, b => {b[b.length - 1] |= 1; return b;});
const invalidDetails = await SettlementCheck.fromBytes(raw, {detailsLoader: async () => badPadding});
await assert.rejects(() => invalidDetails._loadFace(1), /padding/);
assert.deepEqual(invalidDetails.stats.detailsFaces, []);
console.log("settlementcheck JS fixtures: classes, lazy loading, cache, retry, identity and validation passed");

if (!process.argv.includes("--fixture-only")) {
  const release = await SettlementCheck.fromFile();
  assert.equal(release.classCode(24.7536,59.4370),30);
  assert.equal(release.classCode(-0.1276,51.5072),30);
  assert.equal(release.classify(0,90).status,"no_data");
  assert.deepEqual(await release.checkAsync(180,0), await release.checkAsync(-180,0));
  console.log("settlementcheck JS bundled release passed");
}
