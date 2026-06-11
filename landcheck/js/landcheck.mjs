/**
 * landcheck — offline land/sea lookup for lon/lat points (Trifold subproject).
 *
 * Loads the ~180 KB TFLS dataset (built by landcheck/build.py from the
 * Trifold level-10 grid, ~7 km triangles, Natural Earth 1:50m land) and
 * answers "is this point on land?" in microseconds, fully offline.
 *
 *   import { LandCheck } from "./landcheck.mjs";
 *   const lc = await LandCheck.fromFile("../data/landsea_L10.tfls"); // Node
 *   const lc = await LandCheck.fromUrl("/data/landsea_L10.tfls");    // browser
 *   lc.isLand(24.75, 59.44)        // true (Tallinn)
 *   lc.check(-0.1276, 51.5072)     // {land, kind, confidence, landFraction, cell}
 *
 * Answer semantics (mirrors the Python library exactly):
 *   kind 'land'  — cell wholly inside land            -> land, confidence 1
 *   kind 'sea'   — cell absent from the dataset        -> sea,  confidence 1
 *   kind 'coast' — mixed cell; bundled land fraction:
 *                  land = fraction >= 0.5, confidence = max(f, 1 - f).
 *
 * Confidence is relative to Natural Earth 1:50m: features below its
 * resolution (islets, narrow fjords) can be misrepresented, and 'coast'
 * answers flag exactly where that risk lives.
 */

const EPS = -1e-14;
const LON_ROT = (7.3 * Math.PI) / 180;
const REFINED_CONFIDENCE = 0.99; // OSM simplified polygons; quantization ~0.1 m
const B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"; // Crockford, as trifold.js

// ------------------------------------------------------- fast point location
// Pure-double re-statement of trifold.js locate(): normalized-sum midpoints,
// plane-side tests with the -1e-14 tolerance, first-match child order,
// max-margin fallback. Bit-identical to the SDK and the Python library;
// the test suite cross-checks all three.
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
  const verts = raw.map(([x, y, z]) => {
    const n = Math.sqrt(x * x + y * y + z * z);
    x /= n; y /= n; z /= n;
    return [c * x - s * y, s * x + c * y, z];
  });
  const faces = FACE_INDEXES.map(([i, j, k]) => [verts[i], verts[j], verts[k]]);
  const cents = faces.map(([v0, v1, v2]) => {
    const x = v0[0] + v1[0] + v2[0], y = v0[1] + v1[1] + v2[1], z = v0[2] + v1[2] + v2[2];
    const n = Math.sqrt(x * x + y * y + z * z);
    return [x / n, y / n, z / n];
  });
  return { faces, cents };
}

const { faces: FACES, cents: CENTROIDS } = buildFaces();

function mid(a, b) {
  const x = a[0] + b[0], y = a[1] + b[1], z = a[2] + b[2];
  const n = Math.sqrt(x * x + y * y + z * z);
  return [x / n, y / n, z / n];
}

function side(a, b, p) { // dot(cross(a, b), p)
  return (a[1] * b[2] - a[2] * b[1]) * p[0]
       + (a[2] * b[0] - a[0] * b[2]) * p[1]
       + (a[0] * b[1] - a[1] * b[0]) * p[2];
}

function inside(v0, v1, v2, p) {
  return side(v0, v1, p) >= EPS && side(v1, v2, p) >= EPS && side(v2, v0, p) >= EPS;
}

/** Canonical cell index `(face << 2*level) | pathBits` for a point. */
export function locateIndex(lon, lat, level) {
  const lam = (lon * Math.PI) / 180, phi = (lat * Math.PI) / 180;
  const cp = Math.cos(phi);
  const p = [cp * Math.cos(lam), cp * Math.sin(lam), Math.sin(phi)];

  let face = -1, tri = null;
  for (let f = 0; f < 20; f++) {
    const [v0, v1, v2] = FACES[f];
    if (inside(v0, v1, v2, p)) { face = f; tri = FACES[f]; break; }
  }
  if (tri === null) { // numeric edge case: nearest face centroid
    let best = -2;
    for (let f = 0; f < 20; f++) {
      const c = CENTROIDS[f];
      const d = c[0] * p[0] + c[1] * p[1] + c[2] * p[2];
      if (d > best) { best = d; face = f; }
    }
    tri = FACES[face];
  }

  let path = 0;
  let [v0, v1, v2] = tri;
  for (let l = 0; l < level; l++) {
    const m01 = mid(v0, v1), m12 = mid(v1, v2), m20 = mid(v2, v0);
    const children = [[v0, m01, m20], [m01, v1, m12], [m20, m12, v2], [m01, m12, m20]];
    let digit = -1;
    for (let d = 0; d < 4; d++) {
      const [c0, c1, c2] = children[d];
      if (inside(c0, c1, c2, p)) { digit = d; break; }
    }
    if (digit < 0) { // tolerance fallback: max min-margin, first max
      let best = null;
      for (let d = 0; d < 4; d++) {
        const [c0, c1, c2] = children[d];
        const m = Math.min(side(c0, c1, p), side(c1, c2, p), side(c2, c0, p));
        if (best === null || m > best) { best = m; digit = d; }
      }
    }
    [v0, v1, v2] = children[digit];
    path = path * 4 + digit; // stays well below 2^53 for level <= 10
  }
  return face * Math.pow(4, level) + path;
}

/** Unit-sphere triangle vertices of a canonical cell index. */
export function indexToTriangle(index, level) {
  const span = Math.pow(4, level);
  const face = Math.floor(index / span);
  const path = index % span;
  let [v0, v1, v2] = FACES[face];
  for (let l = level - 1; l >= 0; l--) {
    const digit = Math.floor(path / Math.pow(4, l)) & 3;
    const m01 = mid(v0, v1), m12 = mid(v1, v2), m20 = mid(v2, v0);
    if (digit === 0) { v1 = m01; v2 = m20; }
    else if (digit === 1) { v0 = m01; v2 = m12; }
    else if (digit === 2) { v0 = m20; v1 = m12; }
    else { v0 = m01; v1 = m12; v2 = m20; }
  }
  return [v0, v1, v2];
}

/** Triangle ring in degrees, antimeridian-unwrapped (lons may exceed 180). */
export function indexToLonLatRing(index, level) {
  const ring = indexToTriangle(index, level).map(([x, y, z]) => [
    (Math.atan2(y, x) * 180) / Math.PI,
    (Math.asin(Math.max(-1, Math.min(1, z))) * 180) / Math.PI,
  ]);
  const lons = ring.map((p) => p[0]);
  if (Math.max(...lons) - Math.min(...lons) > 180) {
    return ring.map(([lon, lat]) => [lon < 0 ? lon + 360 : lon, lat]);
  }
  return ring;
}

/** Compact Trifold address (e.g. 'TFAVKGR') of a canonical cell index. */
export function indexToCompact(index, level) {
  const span = Math.pow(4, level);
  const face = Math.floor(index / span);
  let path = index % span;
  const bits = 2 * level;
  const nchars = Math.ceil(bits / 5);
  path *= Math.pow(2, nchars * 5 - bits); // right-pad to 5-bit boundary
  let out = "T" + B32[face] + B32[level];
  for (let i = nchars - 1; i >= 0; i--) {
    out += B32[Math.floor(path / Math.pow(2, 5 * i)) & 31];
  }
  return out;
}

// ------------------------------------------------------------- TFLS decoding
async function inflate(compressed) {
  if (typeof DecompressionStream === "function") {
    const ds = new DecompressionStream("deflate"); // zlib wrapper
    const stream = new Blob([compressed]).stream().pipeThrough(ds);
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }
  const zlib = await import("node:zlib"); // older Node fallback
  return new Uint8Array(zlib.inflateSync(compressed));
}

export class LandCheck {
  /** Build from raw TFLS bytes (ArrayBuffer or Uint8Array). */
  static async fromBytes(bytes) {
    const raw = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
    if (String.fromCharCode(...raw.subarray(0, 4)) !== "TFLS") {
      throw new Error("not a TFLS file");
    }
    const version = raw[4];
    if (version !== 1) throw new Error(`unsupported TFLS version ${version}`);
    const level = raw[5];
    const flags = raw[6];
    const nRuns = view.getUint32(8, true);
    const nCoast = view.getUint32(12, true);
    const body = await inflate(raw.subarray(16));

    const starts = new Uint32Array(nRuns);
    const ends = new Uint32Array(nRuns);
    const coastal = new Uint8Array(nRuns);
    const coastBefore = new Uint32Array(nRuns);
    let pos = 0, cursor = 0, coastSeen = 0;
    const readVarint = () => {
      let shift = 0, value = 0;
      for (;;) {
        const b = body[pos++];
        value += (b & 0x7f) * Math.pow(2, shift); // values < 2^32, exact
        if (!(b & 0x80)) return value;
        shift += 7;
      }
    };
    for (let i = 0; i < nRuns; i++) {
      cursor += readVarint();
      const packed = readVarint();
      const length = Math.floor(packed / 2);
      starts[i] = cursor;
      ends[i] = cursor + length;
      coastBefore[i] = coastSeen;
      if (packed & 1) { coastal[i] = 1; coastSeen += length; }
      cursor += length;
    }
    if (coastSeen !== nCoast) throw new Error("coastal count mismatch");
    const fractions = (flags & 1) ? body.subarray(pos) : null;
    if (fractions && fractions.length < Math.ceil(nCoast / 2)) {
      throw new Error("truncated fraction block");
    }
    return new LandCheck(level, starts, ends, coastal, coastBefore, fractions);
  }

  /** Load via fetch (browser or Node >= 18). */
  static async fromUrl(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`fetch ${url}: ${res.status}`);
    return LandCheck.fromBytes(await res.arrayBuffer());
  }

  /** Load from the filesystem (Node). Defaults to the bundled dataset. */
  static async fromFile(path) {
    const { readFile } = await import("node:fs/promises");
    if (!path) {
      const { fileURLToPath } = await import("node:url");
      path = fileURLToPath(new URL("../data/landsea_L10.tfls", import.meta.url));
    }
    return LandCheck.fromBytes(await readFile(path));
  }

  constructor(level, starts, ends, coastal, coastBefore, fractions) {
    this.level = level;
    this._starts = starts;
    this._ends = ends;
    this._coastal = coastal;
    this._coastBefore = coastBefore;
    this._fractions = fractions;
    this._refine = null;
  }

  /** Load a TFLR coastal-refinement dataset (built by refine_build.py). */
  async loadRefinement(source) {
    let raw;
    if (source instanceof Uint8Array || source instanceof ArrayBuffer) {
      raw = source instanceof Uint8Array ? source : new Uint8Array(source);
    } else if (/^https?:|^\//.test(source) && typeof window !== "undefined") {
      const res = await fetch(source);
      if (!res.ok) throw new Error(`fetch ${source}: ${res.status}`);
      raw = new Uint8Array(await res.arrayBuffer());
    } else {
      const { readFile } = await import("node:fs/promises");
      raw = new Uint8Array(await readFile(source));
    }
    const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
    if (String.fromCharCode(...raw.subarray(0, 4)) !== "TFLR") {
      throw new Error("not a TFLR file");
    }
    if (raw[4] !== 1) throw new Error(`unsupported TFLR version ${raw[4]}`);
    if (raw[5] !== this.level) throw new Error("TFLR level mismatch");
    const nCells = view.getUint32(8, true);
    const body = await inflate(raw.subarray(12));
    let pos = 0;
    const readVarint = () => {
      let shift = 0, value = 0;
      for (;;) {
        const b = body[pos++];
        value += (b & 0x7f) * Math.pow(2, shift);
        if (!(b & 0x80)) return value;
        shift += 7;
      }
    };
    const cells = new Map();
    let index = 0;
    for (let c = 0; c < nCells; c++) {
      index += readVarint();
      const code = readVarint();
      if (code < 2) {
        cells.set(index, code); // 0 = all sea, 1 = all land
      } else {
        const rings = [];
        for (let r = 0; r < code - 1; r++) {
          const nPts = readVarint();
          const pts = new Int32Array(nPts * 2);
          let x = 0, y = 0;
          for (let i = 0; i < nPts; i++) {
            const zx = readVarint(), zy = readVarint();
            x += (zx >>> 1) ^ -(zx & 1);
            y += (zy >>> 1) ^ -(zy & 1);
            pts[2 * i] = x;
            pts[2 * i + 1] = y;
          }
          rings.push(pts);
        }
        cells.set(index, rings);
      }
    }
    this._refine = cells;
  }

  _refinedLand(index, lon, lat) {
    if (!this._refine) return null;
    const entry = this._refine.get(index);
    if (entry === undefined) return null;
    if (typeof entry === "number") return entry === 1;
    const ring = indexToLonLatRing(index, this.level);
    const lons = ring.map((p) => p[0]), lats = ring.map((p) => p[1]);
    const minx = Math.min(...lons), maxx = Math.max(...lons);
    const miny = Math.min(...lats), maxy = Math.max(...lats);
    if (maxx > 180 && lon < 0) lon += 360;
    const qx = ((lon - minx) * 65535) / (maxx - minx);
    const qy = ((lat - miny) * 65535) / (maxy - miny);
    let inside = false; // even-odd rule over all rings
    for (const pts of entry) {
      const n = pts.length / 2;
      let x1 = pts[2 * (n - 1)], y1 = pts[2 * (n - 1) + 1];
      for (let i = 0; i < n; i++) {
        const x2 = pts[2 * i], y2 = pts[2 * i + 1];
        if ((y1 > qy) !== (y2 > qy) && qx < x1 + ((qy - y1) * (x2 - x1)) / (y2 - y1)) {
          inside = !inside;
        }
        x1 = x2; y1 = y2;
      }
    }
    return inside;
  }

  _findRun(index) {
    const starts = this._starts;
    let lo = 0, hi = starts.length; // bisect_right
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (starts[mid] <= index) lo = mid + 1; else hi = mid;
    }
    const run = lo - 1;
    if (run < 0 || index >= this._ends[run]) return -1;
    return run;
  }

  _fractionAt(run, index) {
    if (!this._fractions) return null;
    const n = this._coastBefore[run] + (index - this._starts[run]);
    const byte = this._fractions[n >> 1];
    const q = n & 1 ? byte >> 4 : byte & 0x0f;
    return (q + 0.5) / 16;
  }

  /** Full answer: {land, kind, confidence, landFraction, cell}. */
  check(lon, lat) {
    if (!(lon >= -180 && lon <= 180)) throw new RangeError("longitude must be in [-180, 180]");
    if (!(lat >= -90 && lat <= 90)) throw new RangeError("latitude must be in [-90, 90]");
    const index = locateIndex(lon, lat, this.level);
    const run = this._findRun(index);
    if (run < 0) {
      return { land: false, kind: "sea", confidence: 1, landFraction: 0, cell: null, refined: false };
    }
    const cell = indexToCompact(index, this.level);
    if (!this._coastal[run]) {
      return { land: true, kind: "land", confidence: 1, landFraction: 1, cell, refined: false };
    }
    const fraction = this._fractionAt(run, index);
    const refined = this._refinedLand(index, lon, lat);
    if (refined !== null) {
      return { land: refined, kind: "coast", confidence: REFINED_CONFIDENCE,
               landFraction: fraction, cell, refined: true };
    }
    if (fraction === null) {
      return { land: true, kind: "coast", confidence: 0.5, landFraction: null, cell, refined: false };
    }
    return {
      land: fraction >= 0.5,
      kind: "coast",
      confidence: Math.max(fraction, 1 - fraction),
      landFraction: fraction,
      cell,
      refined: false,
    };
  }

  /** Best land/sea bool for one point. */
  isLand(lon, lat) {
    const index = locateIndex(lon, lat, this.level);
    const run = this._findRun(index);
    if (run < 0) return false;
    if (!this._coastal[run]) return true;
    const refined = this._refinedLand(index, lon, lat);
    if (refined !== null) return refined;
    const fraction = this._fractionAt(run, index);
    return fraction === null ? true : fraction >= 0.5;
  }

  /** Dataset summary (for diagnostics). */
  get stats() {
    let interior = 0, coast = 0;
    for (let i = 0; i < this._starts.length; i++) {
      const n = this._ends[i] - this._starts[i];
      if (this._coastal[i]) coast += n; else interior += n;
    }
    return {
      level: this.level,
      runs: this._starts.length,
      interiorCells: interior,
      coastalCells: coast,
      hasFractions: !!this._fractions,
    };
  }
}
