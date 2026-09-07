#!/usr/bin/env node
import { performance } from "node:perf_hooks";
import { stat } from "node:fs/promises";
import { SettlementCheck } from "../settlementcheck/js/settlementcheck.mjs";

const count = Number(process.argv[2] || 100000);
const started = performance.now();
const checker = await SettlementCheck.fromFile();
const loadMs = performance.now() - started;
let state = 2025;
const random = () => {
  state = (1664525 * state + 1013904223) >>> 0;
  return state / 2 ** 32;
};
const lons = Array.from({ length: count }, () => random() * 360 - 180);
const lats = Array.from({ length: count }, () => random() * 180 - 90);
for (let index = 0; index < Math.min(count,1000); index++) checker.classCode(lons[index], lats[index]);
const lookupStarted = performance.now();
for (let index = 0; index < count; index++) checker.classCode(lons[index], lats[index]);
const lookupMs = performance.now() - lookupStarted;
const artifact = new URL("../settlementcheck/data/degurba_R2025A_E2025_L12.tfdg", import.meta.url);
console.log(`artifact_bytes=${(await stat(artifact)).size}`);
console.log(`load_seconds=${(loadMs / 1000).toFixed(6)}`);
console.log(`scalar_queries_per_second=${Math.round(count / (lookupMs / 1000))}`);
console.log(`core_peak_rss_mib=${(process.resourceUsage().maxRSS/1024).toFixed(2)}`);
const detailStarted = performance.now();
await checker.checkAsync(-0.1276,51.5072);
console.log(`first_detail_face_seconds=${((performance.now()-detailStarted)/1000).toFixed(6)}`);
const warm = performance.now();
for(let i=0;i<10000;i++)checker.check(-0.1276,51.5072);
console.log(`warm_detail_queries_per_second=${Math.round(1e7/(performance.now()-warm))}`);
console.log(`with_detail_peak_rss_mib=${(process.resourceUsage().maxRSS/1024).toFixed(2)}`);
