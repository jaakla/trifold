/** Offline GHS-WUP Degree of Urbanisation lookup on the Trifold T3 grid. */

const EPS = -1e-14;
const LON_ROT = (7.3 * Math.PI) / 180;
const B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const NODATA = 255;
const URBAN = new Set([21, 22, 23, 30]);

export const CLASSES = Object.freeze({
  30: { settlementClass: "urban_centre", label: "Urban centre", level1Code: 3, level1Class: "urban_centre" },
  23: { settlementClass: "dense_urban_cluster", label: "Dense urban cluster", level1Code: 2, level1Class: "urban_cluster" },
  22: { settlementClass: "semi_dense_urban_cluster", label: "Semi-dense urban cluster", level1Code: 2, level1Class: "urban_cluster" },
  21: { settlementClass: "suburban_or_peri_urban", label: "Suburban or peri-urban", level1Code: 2, level1Class: "urban_cluster" },
  13: { settlementClass: "rural_cluster", label: "Rural cluster", level1Code: 1, level1Class: "rural_grid_cell" },
  12: { settlementClass: "low_density_rural", label: "Low-density rural", level1Code: 1, level1Class: "rural_grid_cell" },
  11: { settlementClass: "very_low_density_rural", label: "Very-low-density rural", level1Code: 1, level1Class: "rural_grid_cell" },
  10: { settlementClass: "water", label: "Water", level1Code: 1, level1Class: "rural_grid_cell" },
});

const FACE_INDEXES = [
  [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
  [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
  [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
  [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
];

function buildFaces() {
  const phi = (1 + Math.sqrt(5)) / 2;
  const raw = [
    [-1, phi, 0], [1, phi, 0], [-1, -phi, 0], [1, -phi, 0],
    [0, -1, phi], [0, 1, phi], [0, -1, -phi], [0, 1, -phi],
    [phi, 0, -1], [phi, 0, 1], [-phi, 0, -1], [-phi, 0, 1],
  ];
  const c = Math.cos(LON_ROT), s = Math.sin(LON_ROT);
  const vertices = raw.map(([x, y, z]) => {
    const n = Math.sqrt(x * x + y * y + z * z);
    x /= n; y /= n; z /= n;
    return [c * x - s * y, s * x + c * y, z];
  });
  const faces = FACE_INDEXES.map(([i, j, k]) => [vertices[i], vertices[j], vertices[k]]);
  const centroids = faces.map(([a, b, c0]) => {
    const x = a[0] + b[0] + c0[0], y = a[1] + b[1] + c0[1], z = a[2] + b[2] + c0[2];
    const n = Math.sqrt(x * x + y * y + z * z);
    return [x / n, y / n, z / n];
  });
  return { faces, centroids };
}

const { faces: FACES, centroids: CENTROIDS } = buildFaces();
function mid(a, b) {
  const x = a[0] + b[0], y = a[1] + b[1], z = a[2] + b[2];
  const n = Math.sqrt(x * x + y * y + z * z);
  return [x / n, y / n, z / n];
}
function side(a, b, p) {
  return (a[1] * b[2] - a[2] * b[1]) * p[0]
    + (a[2] * b[0] - a[0] * b[2]) * p[1]
    + (a[0] * b[1] - a[1] * b[0]) * p[2];
}
function inside([a, b, c], p) {
  return side(a, b, p) >= EPS && side(b, c, p) >= EPS && side(c, a, p) >= EPS;
}

export function locateIndex(lon, lat, level) {
  const lambda = lon * Math.PI / 180, phi = lat * Math.PI / 180;
  const cp = Math.cos(phi), point = [cp * Math.cos(lambda), cp * Math.sin(lambda), Math.sin(phi)];
  let face = -1, tri = null;
  for (let candidate = 0; candidate < 20; candidate++) {
    if (inside(FACES[candidate], point)) { face = candidate; tri = FACES[candidate]; break; }
  }
  if (tri === null) {
    let best = -2;
    for (let candidate = 0; candidate < 20; candidate++) {
      const centre = CENTROIDS[candidate];
      const dot = centre[0] * point[0] + centre[1] * point[1] + centre[2] * point[2];
      if (dot > best) { best = dot; face = candidate; }
    }
    tri = FACES[face];
  }
  let path = 0;
  let [v0, v1, v2] = tri;
  for (let depth = 0; depth < level; depth++) {
    const m01 = mid(v0, v1), m12 = mid(v1, v2), m20 = mid(v2, v0);
    const children = [[v0, m01, m20], [m01, v1, m12], [m20, m12, v2], [m01, m12, m20]];
    let digit = children.findIndex((child) => inside(child, point));
    if (digit < 0) {
      let margin = -Infinity;
      for (let candidate = 0; candidate < 4; candidate++) {
        const [a, b, c] = children[candidate];
        const value = Math.min(side(a, b, point), side(b, c, point), side(c, a, point));
        if (value > margin) { margin = value; digit = candidate; }
      }
    }
    [v0, v1, v2] = children[digit];
    path = path * 4 + digit;
  }
  return face * 4 ** level + path;
}

function compact(index, level) {
  const span = 4 ** level, face = Math.floor(index / span);
  let path = index % span;
  const bits = 2 * level, chars = Math.ceil(bits / 5);
  path *= 2 ** (chars * 5 - bits);
  let output = `T${B32[face]}${B32[level]}`;
  for (let i = chars - 1; i >= 0; i--) output += B32[Math.floor(path / 2 ** (5 * i)) & 31];
  return output;
}

const SLOTS = [10, 11, 12, 13, 21, 22, 23, 30, NODATA];
const MAX_RAW = 256 * 1024 * 1024;
export class DetailsNotLoadedError extends Error {}

async function inflate(compressed, expected) {
  if (typeof process !== "undefined" && process.versions?.node) {
    const { inflateSync } = await import("node:zlib");
    const result = inflateSync(compressed, { maxOutputLength: Math.max(1, expected + 1), info: true });
    if (result.engine.bytesWritten !== compressed.length) throw new Error("trailing TFDG compressed payload");
    return new Uint8Array(result.buffer);
  }
  const reader = new Blob([compressed]).stream()
    .pipeThrough(new DecompressionStream("deflate")).getReader();
  const output = new Uint8Array(expected);
  let offset = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (offset + value.length > expected) throw new Error("TFDG payload exceeds declared size");
      output.set(value, offset); offset += value.length;
    }
    if (offset !== expected) throw new Error("truncated TFDG payload");
  } catch (error) { await reader.cancel().catch(() => {}); throw error; }
  finally { reader.releaseLock(); }
  return output;
}

function hex(bytes) { return Array.from(bytes, v => v.toString(16).padStart(2, "0")).join(""); }
async function readContainer(input, magic, flags, sections) {
  const raw = input instanceof Uint8Array ? input : new Uint8Array(input);
  let offset = 92 + 8 * sections;
  if (raw.length < offset) throw new Error("truncated TFDG header/directory");
  if (String.fromCharCode(...raw.subarray(0, 4)) !== magic) throw new Error("not a TFDG/TFDD file");
  if (raw[4] !== 1 || raw[6] !== flags) throw new Error("unsupported TFDG layout (rebuild obsolete WIP v1 files)");
  const v = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  const h = { level: raw[5], face: raw[7], year: v.getUint16(8, true),
    runs: v.getUint32(12, true), mixed: v.getUint32(16, true),
    cells: v.getUint32(20, true), size: v.getUint32(24, true),
    rasterSha256: hex(raw.subarray(28, 60)), datasetId: hex(raw.subarray(60, 92)) };
  if (h.level < 1 || h.level > 13 || h.cells !== 20 * 4 ** h.level || h.year !== 2025
      || raw[10] !== 1 || raw[11] !== 10 || h.face >= 20 || (magic === "TFDG" && h.face !== 0)
      || h.size > MAX_RAW || h.runs > h.cells || h.mixed > h.cells) throw new Error("invalid TFDG metadata");
  const blocks = [];
  let total = 0;
  for (let i = 0; i < sections; i++) {
    const length = v.getUint32(92 + 8 * i, true), expected = v.getUint32(96 + 8 * i, true);
    total += expected;
    if (total > h.size || offset + length > raw.length) throw new Error("truncated/invalid TFDG payload section");
    const block = await inflate(raw.subarray(offset, offset + length), expected);
    if (block.length !== expected) throw new Error("invalid TFDG payload length");
    blocks.push(block); offset += length;
  }
  if (offset !== raw.length || total !== h.size) throw new Error("invalid TFDG section directory");
  return { h, blocks };
}

function* varints(block) {
  let value = 0, multiplier = 1;
  for (const byte of block) {
    if (multiplier >= 2 ** 35) throw new Error("invalid TFDG varint");
    value += (byte & 127) * multiplier;
    if (byte & 128) multiplier *= 128;
    else {
      if (value > 0xffffffff) throw new Error("TFDG varint overflow");
      yield value; value = 0; multiplier = 1;
    }
  }
  if (multiplier !== 1) throw new Error("truncated TFDG varint");
}
function upperBound(ends, index) {
  let low = 0, high = ends.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (ends[middle] <= index) low = middle + 1; else high = middle;
  }
  return low;
}
async function fetchBytes(url) {
  const response = await fetch(url);
  if (!response.ok) throw new DetailsNotLoadedError("Failed to load data: HTTP " + response.status);
  return response.arrayBuffer();
}
function detailUrl(core, face) {
  const url = new URL(core, typeof location !== "undefined" ? location.href : undefined);
  url.pathname = url.pathname.replace(/\.tfdg$/, ".details") + "/face-" + String(face).padStart(2, "0") + ".tfdd";
  return url;
}

export class SettlementCheck {
  static async fromBytes(input, { detailsLoader = null, cacheFaces = 2 } = {}) {
    if (!Number.isInteger(cacheFaces) || cacheFaces < 1 || cacheFaces > 20) throw new Error("cacheFaces must be in 1..20");
    const { h, blocks: [lengths, slots] } = await readContainer(input, "TFDG", 3, 2);
    if (!h.runs || slots.length !== h.runs || lengths.length < h.runs) throw new Error("invalid TFDG class table");
    const ends = new Uint32Array(h.runs), codes = new Uint8Array(h.runs);
    let cursor = 0, run = 0;
    for (const length of varints(lengths)) {
      cursor += length;
      if (!length || cursor > h.cells || run >= h.runs || slots[run] > 8) throw new Error("invalid TFDG coverage/class code");
      ends[run] = cursor; codes[run] = SLOTS[slots[run]]; run++;
    }
    if (run !== h.runs || cursor !== h.cells) throw new Error("incomplete TFDG coverage");
    return Object.assign(new SettlementCheck(), { level: h.level, year: h.year,
      source: "GHS-WUP-DEGURBA", sourceRelease: "R2025A", estimateKind: "projected",
      sourceResolutionKm: 1, rasterSha256: h.rasterSha256, datasetId: h.datasetId,
      ends, codes, nCells: h.cells, nMixed: h.mixed, _detailsLoader: detailsLoader,
      _cacheFaces: cacheFaces, _details: new Map(), _pending: new Map(), _generation: 0 });
  }
  static async fromFile(path = new URL("../data/degurba_R2025A_E2025_L12.tfdg", import.meta.url), options = {}) {
    const fs = await import("node:fs/promises");
    const { pathToFileURL } = await import("node:url"), { resolve } = await import("node:path");
    const url = path instanceof URL ? path : pathToFileURL(resolve(path));
    return this.fromBytes(await fs.readFile(url), {
      ...options, detailsLoader: options.detailsLoader ?? (face => fs.readFile(detailUrl(url, face))) });
  }
  static async fromUrl(url, options = {}) {
    return this.fromBytes(await fetchBytes(url), {
      ...options, detailsLoader: options.detailsLoader ?? (face => fetchBytes(detailUrl(url, face))) });
  }
  _index(lon, lat) {
    if (!(lon >= -180 && lon <= 180)) throw new Error("longitude must be in [-180, 180]");
    if (!(lat >= -90 && lat <= 90)) throw new Error("latitude must be in [-90, 90]");
    return locateIndex(lon, lat, this.level);
  }
  async loadDetails(lon, lat) {
    return this._loadFace(Math.floor(this._index(lon, lat) / 4 ** this.level));
  }
  async _loadFace(face) {
    if (this._details.has(face)) {
      const shard = this._details.get(face);
      this._details.delete(face); this._details.set(face, shard); return shard;
    }
    if (this._pending.has(face)) return this._pending.get(face);
    if (!this._detailsLoader) throw new DetailsNotLoadedError("Configure detailsLoader, or use classify()/classCode() without details");
    const generation = this._generation;
    const task = (async () => {
      const { h, blocks: [encoded, shares, water, nodata] } = await readContainer(
        await this._detailsLoader(face), "TFDD", 1, 4);
      if (h.datasetId !== this.datasetId || h.level !== this.level || h.face !== face
          || h.rasterSha256 !== this.rasterSha256) throw new Error("TFDD details do not match this core/face");
      const bitBytes = Math.ceil(h.mixed / 8);
      if (shares.length !== h.mixed || water.length !== bitBytes || nodata.length !== bitBytes
          || h.mixed > 4 ** this.level || h.runs > h.mixed || encoded.length < 2 * h.runs) throw new Error("invalid TFDD mixed-cell blocks");
      const unused = (8 - h.mixed % 8) % 8;
      if (unused && ((water.at(-1) | nodata.at(-1)) & ((1 << unused) - 1))) throw new Error("invalid TFDD bit padding");
      const starts = new Uint32Array(h.runs), ends = new Uint32Array(h.runs), before = new Uint32Array(h.runs);
      const values = varints(encoded);
      let cursor = 0, seen = 0, run = 0;
      for (const gap of values) {
        const length = values.next().value;
        if (!length || run >= h.runs) throw new Error("invalid TFDD interval");
        const start = cursor + gap; cursor = start + length;
        if (cursor > 4 ** this.level || seen + length > h.mixed) throw new Error("invalid TFDD interval bounds");
        starts[run] = start; ends[run] = cursor; before[run] = seen; seen += length; run++;
      }
      if (run !== h.runs || seen !== h.mixed) throw new Error("inconsistent TFDD coverage");
      const shard = { starts, ends, before, shares, water, nodata };
      if (generation === this._generation) {
        this._details.set(face, shard);
        while (this._details.size > this._cacheFaces) this._details.delete(this._details.keys().next().value);
      }
      return shard;
    })();
    this._pending.set(face, task);
    try { return await task; }
    catch (error) {
      if (error.code === "ENOENT") throw new DetailsNotLoadedError("Download the matching .details directory or configure detailsLoader; core packages contain classes only");
      throw error;
    } finally { if (this._pending.get(face) === task) this._pending.delete(face); }
  }
  unloadDetails() { this._generation++; this._details.clear(); this._pending.clear(); }
  _result(index, shard = null) {
    const code = this.codes[upperBound(this.ends, index)];
    let mixed = null, classShare = null, nodataMixed = null, surface = null;
    if (shard) {
      const local = index % 4 ** this.level, run = upperBound(shard.ends, local);
      mixed = run < shard.ends.length && local >= shard.starts[run];
      let water = false; nodataMixed = false; classShare = 1;
      if (mixed) {
        const offset = shard.before[run] + local - shard.starts[run], bit = 7 - offset % 8;
        classShare = shard.shares[offset] / 255;
        water = Boolean((shard.water[Math.floor(offset / 8)] >> bit) & 1);
        nodataMixed = Boolean((shard.nodata[Math.floor(offset / 8)] >> bit) & 1);
      }
      surface = water ? "mixed" : code === 10 ? "water" : "land";
    }
    const cls = code === NODATA ? { settlementClass: null, label: null, level1Code: null, level1Class: null } : CLASSES[code];
    return { code: code === NODATA ? null : code, ...cls,
      surface: code === NODATA ? "unknown" : surface, classShare: code === NODATA ? null : classShare,
      mixed, nodataMixed, status: code === NODATA ? "no_data" : "classified", detailsLoaded: shard !== null,
      cell: compact(index, this.level), level: this.level, source: this.source, sourceRelease: this.sourceRelease,
      year: this.year, estimateKind: this.estimateKind, sourceResolutionKm: this.sourceResolutionKm };
  }
  classify(lon, lat) { return this._result(this._index(lon, lat)); }
  check(lon, lat) {
    const index = this._index(lon, lat), shard = this._details.get(Math.floor(index / 4 ** this.level));
    if (!shard) throw new DetailsNotLoadedError("Use await checkAsync(lon, lat) or await loadDetails(lon, lat) first");
    return this._result(index, shard);
  }
  async checkAsync(lon, lat) {
    const index = this._index(lon, lat), shard = await this._loadFace(Math.floor(index / 4 ** this.level));
    return this._result(index, shard);
  }
  classCode(lon, lat) {
    const code = this.codes[upperBound(this.ends, this._index(lon, lat))];
    return code === NODATA ? null : code;
  }
  settlement(lon, lat) { const code = this.classCode(lon, lat); return code === null ? null : CLASSES[code].settlementClass; }
  isUrban(lon, lat) { const code = this.classCode(lon, lat); return code === null ? null : URBAN.has(code); }
  checkBatch(lons, lats) {
    if (lons.length !== lats.length) throw new Error("lons and lats must have the same length");
    return Array.from(lons, (lon, i) => this.check(lon, lats[i]));
  }
  async checkBatchAsync(lons, lats) {
    if (lons.length !== lats.length) throw new Error("lons and lats must have the same length");
    const faces = Array.from(lons, (lon, i) => Math.floor(this._index(lon, lats[i]) / 4 ** this.level));
    const order = Array.from(lons, (_, i) => i).sort((a, b) => faces[a] - faces[b]), results = new Array(lons.length);
    for (const i of order) results[i] = await this.checkAsync(lons[i], lats[i]);
    return results;
  }
  settlementBatch(lons, lats) {
    if (lons.length !== lats.length) throw new Error("lons and lats must have the same length");
    return Array.from(lons, (lon, i) => this.settlement(lon, lats[i]));
  }
  get stats() { return { level: this.level, runs: this.ends.length, mixedCells: this.nMixed,
    cells: this.nCells, sourceRelease: this.sourceRelease, year: this.year, detailsFaces: [...this._details.keys()] }; }
}
