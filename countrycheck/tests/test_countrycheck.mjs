// Tests for the countrycheck JS library: node --test countrycheck/tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { CountryCheck } from "../js/countrycheck.mjs";

const cc = await CountryCheck.fromFile();
const fixtureUrl = new URL("./points.json", import.meta.url);
const points = JSON.parse(await readFile(fixtureUrl, "utf8"));

test("stats", () => {
  const s = cc.stats;
  assert.equal(s.level, 10);
  assert.equal(s.countries, 256);
  assert.ok(s.hasShares);
  assert.ok(s.borderCells > 100_000);
  assert.ok(s.interiorCells > 1_000_000);
});

test("country table", () => {
  const codes = cc.countries.map((c) => c.code);
  assert.deepEqual(codes, [...codes].sort());
  const est = cc.countries.find((c) => c.code === "EST");
  assert.equal(est.iso2, "EE");
  assert.equal(est.name, "Estonia");
  const xko = cc.countries.find((c) => c.code === "XKO");
  assert.equal(xko.iso2, ""); // X-coded territories have no ISO code
});

test("known points", () => {
  assert.equal(cc.country(24.7536, 59.437), "EST");   // Tallinn
  assert.equal(cc.country(-0.1276, 51.5072), "GBR");  // London
  assert.equal(cc.country(-30, 30), null);            // mid-Atlantic
  assert.equal(cc.country(0, 89.99), null);           // Arctic ocean
  assert.equal(cc.country(0, -89.99), "ATA");         // Antarctica
  assert.equal(cc.country(20.9, 42.6), "XKO");        // Kosovo
});

test("result semantics", () => {
  const none = cc.check(-30, 30);
  assert.deepEqual(none, { country: null, iso2: null, name: null, kind: "none",
                           confidence: 1, share: 0, cell: null, refined: false });
  const interior = cc.check(13.4, 52.52); // Berlin
  assert.equal(interior.kind, "country");
  assert.equal(interior.country, "DEU");
  assert.equal(interior.confidence, 1);
  const border = cc.check(24.3, 59.6); // Estonian coastal waters
  assert.equal(border.kind, "border");
  assert.ok(border.share > 0 && border.share <= 1);
  assert.equal(border.confidence, border.share);
});

test("input validation", () => {
  assert.throws(() => cc.check(181, 0), RangeError);
  assert.throws(() => cc.check(0, 91), RangeError);
});

test("refined fixture parity with Python", async (t) => {
  const tfcrUrl = new URL("../data/borders_L10.tfcr", import.meta.url);
  const refinedUrl = new URL("./refined_points.json", import.meta.url);
  let refinedPoints, ccRefined;
  try {
    refinedPoints = JSON.parse(await readFile(refinedUrl, "utf8"));
    ccRefined = await CountryCheck.fromFile(); // isolated: shared cc stays unrefined
    await ccRefined.loadRefinement(tfcrUrl.pathname);
  } catch {
    t.skip("border refinement dataset not built");
    return;
  }
  for (const p of refinedPoints) {
    const r = ccRefined.check(p.lon, p.lat);
    assert.equal(r.country, p.country);
    assert.equal(r.kind, p.kind);
    assert.equal(r.refined, p.refined);
    assert.equal(r.cell, p.cell);
    assert.equal(Math.round(r.confidence * 1e6) / 1e6, p.confidence);
  }
});

test("fixture parity with Python", () => {
  for (const p of points) {
    const r = cc.check(p.lon, p.lat);
    assert.equal(r.country, p.country, p.name);
    assert.equal(r.iso2, p.iso2, p.name);
    assert.equal(r.kind, p.kind, p.name);
    assert.equal(r.cell, p.cell, p.name);
    assert.equal(Math.round(r.confidence * 1e6) / 1e6, p.confidence, p.name);
    const share = r.share === null ? null : Math.round(r.share * 1e6) / 1e6;
    assert.equal(share, p.share, p.name);
  }
});
