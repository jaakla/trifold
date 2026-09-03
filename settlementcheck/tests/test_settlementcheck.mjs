import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { CLASSES, SettlementCheck } from "../js/settlementcheck.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const checker = await SettlementCheck.fromFile(join(here, "fixture_L2.tfdg"));
const points = JSON.parse(await readFile(join(here, "points.json"), "utf8"));

for (const point of points.slice(0, 9)) {
  const result = checker.check(point.lon, point.lat);
  assert.equal(result.code, point.code);
  assert.equal(result.status, point.code === null ? "no_data" : "classified");
  if (point.code !== null) assert.equal(result.settlementClass, CLASSES[point.code].settlementClass);
}

const byCode = new Map(points.slice(0, 9).map((point) => [point.code, point]));
const water = checker.check(byCode.get(10).lon, byCode.get(10).lat);
assert.equal(water.surface, "water");
assert.equal(water.level1Code, 1);
assert.equal(water.level1Class, "rural_grid_cell");
assert.equal(checker.isUrban(byCode.get(30).lon, byCode.get(30).lat), true);
assert.equal(checker.isUrban(byCode.get(11).lon, byCode.get(11).lat), false);
assert.equal(checker.isUrban(byCode.get(null).lon, byCode.get(null).lat), null);

const mixedPoint = points.find((point) => point.mixed);
const mixed = checker.check(mixedPoint.lon, mixedPoint.lat);
assert.equal(mixed.mixed, true);
assert.equal(mixed.surface, "mixed");
assert.ok(Math.abs(mixed.classShare - Math.round(0.6 * 255) / 255) < 1e-12);
assert.deepEqual(checker.settlementBatch([mixedPoint.lon], [mixedPoint.lat]), [mixed.settlementClass]);
assert.throws(() => checker.checkBatch([0, 1], [0]), /same length/);
assert.throws(() => checker.check(181, 0), /longitude/);

const raw = new Uint8Array(await readFile(join(here, "fixture_L2.tfdg")));
await assert.rejects(() => SettlementCheck.fromBytes(raw.subarray(0, 20)), /truncated/);
const badMagic = raw.slice(); badMagic[0] = 0;
await assert.rejects(() => SettlementCheck.fromBytes(badMagic), /not a TFDG/);

const release = await SettlementCheck.fromFile();
assert.equal(release.classCode(24.7536, 59.4370), 30);
assert.equal(release.classCode(-0.1276, 51.5072), 30);
assert.equal(release.check(0, 90).status, "no_data");
assert.deepEqual(release.check(180, 0), release.check(-180, 0));

console.log(`settlementcheck JS: ${points.length} cross-language fixture points passed`);
