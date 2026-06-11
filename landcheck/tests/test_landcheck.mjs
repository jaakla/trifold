// Tests for the landcheck JS library: node --test landcheck/tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { LandCheck } from "../js/landcheck.mjs";

const lc = await LandCheck.fromFile();
const fixtureUrl = new URL("./points.json", import.meta.url);
const points = JSON.parse(await readFile(fixtureUrl, "utf8"));

test("stats", () => {
  const s = lc.stats;
  assert.equal(s.level, 10);
  assert.ok(s.hasFractions);
  assert.ok(s.coastalCells > 100_000);
  assert.ok(s.interiorCells > 1_000_000);
});

test("known points", () => {
  assert.ok(lc.isLand(24.7536, 59.437));     // Tallinn
  assert.ok(lc.isLand(-0.1276, 51.5072));    // London
  assert.ok(!lc.isLand(-30, 30));            // mid-Atlantic
  assert.ok(!lc.isLand(0, 89.99));           // Arctic ocean
  assert.ok(lc.isLand(0, -89.99));           // Antarctica
});

test("result semantics", () => {
  const sea = lc.check(-30, 30);
  assert.deepEqual(sea, { land: false, kind: "sea", confidence: 1, landFraction: 0, cell: null, refined: false });
  const coast = lc.check(0, -89.99);
  assert.equal(coast.kind, "coast");
  assert.ok(coast.landFraction > 0 && coast.landFraction < 1);
  assert.equal(coast.confidence, Math.max(coast.landFraction, 1 - coast.landFraction));
});

test("input validation", () => {
  assert.throws(() => lc.check(181, 0), RangeError);
  assert.throws(() => lc.check(0, 91), RangeError);
});

test("refined fixture parity with Python", async (t) => {
  const tflrUrl = new URL("../data/coastal_osm_L10.tflr", import.meta.url);
  const refinedUrl = new URL("./refined_points.json", import.meta.url);
  let refinedPoints, lcRefined;
  try {
    refinedPoints = JSON.parse(await readFile(refinedUrl, "utf8"));
    lcRefined = await LandCheck.fromFile(); // isolated: shared lc stays unrefined
    await lcRefined.loadRefinement(tflrUrl.pathname);
  } catch {
    t.skip("coastal refinement dataset not built");
    return;
  }
  for (const p of refinedPoints) {
    const r = lcRefined.check(p.lon, p.lat);
    assert.equal(r.land, p.land);
    assert.equal(r.kind, p.kind);
    assert.equal(r.refined, p.refined);
    assert.equal(r.cell, p.cell);
    assert.equal(Math.round(r.confidence * 1e6) / 1e6, p.confidence);
  }
});

test("refinement overrides base land near Tallinn", async () => {
  const refined = await LandCheck.fromFile();
  const tflrUrl = new URL("../data/coastal_osm_L10.tflr", import.meta.url);
  await refined.loadRefinement(tflrUrl.pathname);
  const result = refined.check(24.8156, 59.4756);
  assert.equal(result.kind, "coast");
  assert.equal(result.refined, true);
  assert.equal(result.land, false);
  assert.equal(result.cell, "TFAVKGZ");
});

test("fixture parity with Python", () => {
  for (const p of points) {
    const r = lc.check(p.lon, p.lat);
    assert.equal(r.land, p.land, p.name);
    assert.equal(r.kind, p.kind, p.name);
    assert.equal(r.cell, p.cell, p.name);
    assert.equal(Math.round(r.confidence * 1e6) / 1e6, p.confidence, p.name);
    const frac = r.landFraction === null ? null : Math.round(r.landFraction * 1e6) / 1e6;
    assert.equal(frac, p.land_fraction, p.name);
  }
});
