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

async function inflate(compressed) {
  if (typeof DecompressionStream === "function") {
    const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("deflate"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }
  const zlib = await import("node:zlib");
  return new Uint8Array(zlib.inflateSync(compressed));
}

function hex(bytes) {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

export class SettlementCheck {
  static async fromBytes(input) {
    const raw = input instanceof Uint8Array ? input : new Uint8Array(input);
    if (raw.length < 60) throw new Error("truncated TFDG header");
    if (String.fromCharCode(...raw.subarray(0, 4)) !== "TFDG") throw new Error("not a TFDG file");
    if (raw[4] !== 1) throw new Error(`unsupported TFDG version ${raw[4]}`);
    const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
    const level = raw[5], flags = raw[6], reserved = raw[7];
    const year = view.getUint16(8, true), releaseId = raw[10], resolutionTenths = raw[11];
    const nRuns = view.getUint32(12, true), nMixed = view.getUint32(16, true);
    const nCells = view.getUint32(20, true), rawLength = view.getUint32(24, true);
    if (reserved || releaseId !== 1 || year !== 2025 || resolutionTenths !== 10
      || level < 1 || level > 13 || nCells !== 20 * 4 ** level) {
      throw new Error("unsupported or inconsistent TFDG metadata");
    }
    let body;
    try { body = await inflate(raw.subarray(60)); }
    catch { throw new Error("invalid TFDG payload"); }
    if (body.length !== rawLength) throw new Error("truncated TFDG payload");
    let position = 0;
    const readVarint = () => {
      let value = 0, multiplier = 1;
      while (true) {
        if (position >= body.length || multiplier > 2 ** 35) throw new Error("truncated TFDG run table");
        const byte = body[position++];
        value += (byte & 127) * multiplier;
        if (!(byte & 128)) return value;
        multiplier *= 128;
      }
    };
    const ends = new Uint32Array(nRuns);
    const codes = new Uint8Array(nRuns), mixedRuns = new Uint8Array(nRuns);
    const mixedBefore = new Uint32Array(nRuns);
    let cursor = 0, mixedSeen = 0;
    for (let run = 0; run < nRuns; run++) {
      const start = cursor + readVarint(), length = readVarint();
      if (!length || position + 2 > body.length) throw new Error("invalid TFDG run");
      const code = body[position++], mixed = body[position++];
      if (!(code in CLASSES) && code !== NODATA) throw new Error(`unexpected class code ${code}`);
      if (mixed > 1 || start + length > nCells) throw new Error("invalid TFDG run metadata");
      if ((flags & 1) && start !== cursor) throw new Error("incomplete all-runs TFDG dataset");
      ends[run] = start + length; codes[run] = code; mixedRuns[run] = mixed;
      mixedBefore[run] = mixedSeen;
      if (mixed) mixedSeen += length;
      cursor = start + length;
    }
    if (mixedSeen !== nMixed || position + 2 * nMixed !== body.length) {
      throw new Error("inconsistent TFDG mixed-cell block");
    }
    if ((flags & 1) && (!nRuns || ends[nRuns - 1] !== nCells)) {
      throw new Error("incomplete all-runs TFDG dataset");
    }
    const instance = new SettlementCheck();
    Object.assign(instance, {
      level, year, source: "GHS-WUP-DEGURBA", sourceRelease: "R2025A",
      estimateKind: "projected", sourceResolutionKm: resolutionTenths / 10,
      rasterSha256: hex(raw.subarray(28, 60)), ends, codes, mixedRuns,
      mixedBefore, mixedData: body.slice(position), nCells, nMixed,
    });
    return instance;
  }

  static async fromFile(path = new URL("../data/degurba_R2025A_E2025_L12.tfdg", import.meta.url)) {
    const fs = await import("node:fs/promises");
    return SettlementCheck.fromBytes(await fs.readFile(path));
  }

  static async fromUrl(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`failed to load TFDG: HTTP ${response.status}`);
    return SettlementCheck.fromBytes(await response.arrayBuffer());
  }

  _lookup(lon, lat) {
    if (!(lon >= -180 && lon <= 180)) throw new Error("longitude must be in [-180, 180]");
    if (!(lat >= -90 && lat <= 90)) throw new Error("latitude must be in [-90, 90]");
    const index = locateIndex(lon, lat, this.level);
    let low = 0, high = this.ends.length;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (this.ends[middle] <= index) low = middle + 1; else high = middle;
    }
    const run = low;
    if (run >= this.ends.length) return { index, code: NODATA, mixed: false, share: null, flags: 0 };
    const code = this.codes[run];
    if (!this.mixedRuns[run]) return { index, code, mixed: false, share: 1, flags: 0 };
    const start = run === 0 ? 0 : this.ends[run - 1];
    const offset = this.mixedBefore[run] + index - start;
    return { index, code, mixed: true, share: this.mixedData[2 * offset] / 255, flags: this.mixedData[2 * offset + 1] };
  }

  check(lon, lat) {
    const value = this._lookup(lon, lat), cell = compact(value.index, this.level);
    const metadata = {
      cell, level: this.level, source: this.source, sourceRelease: this.sourceRelease,
      year: this.year, estimateKind: this.estimateKind, sourceResolutionKm: this.sourceResolutionKm,
    };
    if (value.code === NODATA) return {
      code: null, settlementClass: null, label: null, level1Code: null, level1Class: null,
      surface: "unknown", classShare: null, mixed: value.mixed,
      nodataMixed: Boolean(value.flags & 2), status: "no_data", ...metadata,
    };
    const cls = CLASSES[value.code];
    const surface = value.flags & 1 ? "mixed" : value.code === 10 ? "water" : "land";
    return { code: value.code, ...cls, surface, classShare: value.share,
      mixed: value.mixed, nodataMixed: Boolean(value.flags & 2),
      status: "classified", ...metadata };
  }

  settlement(lon, lat) { return this.check(lon, lat).settlementClass; }
  classCode(lon, lat) { return this.check(lon, lat).code; }
  isUrban(lon, lat) { const code = this.classCode(lon, lat); return code === null ? null : URBAN.has(code); }
  checkBatch(lons, lats) {
    if (lons.length !== lats.length) throw new Error("lons and lats must have the same length");
    return Array.from({ length: lons.length }, (_, index) => this.check(lons[index], lats[index]));
  }
  settlementBatch(lons, lats) { return this.checkBatch(lons, lats).map((value) => value.settlementClass); }
  get stats() { return { level: this.level, runs: this.ends.length, mixedCells: this.nMixed,
    cells: this.nCells, sourceRelease: this.sourceRelease, year: this.year }; }
}
