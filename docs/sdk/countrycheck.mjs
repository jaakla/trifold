/**
 * countrycheck — offline country lookup for lon/lat points (Trifold subproject).
 *
 * Loads the TFCS dataset (built by countrycheck/build.py from the Trifold
 * level-10 grid, ~7 km triangles, GADM-derived country polygons extended
 * with coastal waters) and answers "which country is this point in?" in
 * microseconds, fully offline.
 *
 *   import { CountryCheck } from "./countrycheck.mjs";
 *   const cc = await CountryCheck.fromFile("../data/countries_L10.tfcs"); // Node
 *   const cc = await CountryCheck.fromUrl("/data/countries_L10.tfcs");    // browser
 *   cc.country(24.75, 59.44)       // 'EST' (Tallinn)
 *   cc.check(-0.1276, 51.5072)     // {country, iso2, name, kind, confidence, share, cell}
 *
 * Answer semantics (mirrors the Python library exactly):
 *   kind 'country' — cell wholly inside one country -> that country, confidence 1
 *   kind 'none'    — cell absent from the dataset   -> no country,   confidence 1
 *                    (international waters)
 *   kind 'border'  — mixed cell; the bundled best call is used with its
 *                    area share as confidence.
 *
 * With the optional border refinement loaded, border cells are decided by a
 * point-in-polygon test against the exact clipped country polygons.
 */

const EPS = -1e-14;
const LON_ROT = (7.3 * Math.PI) / 180;
const REFINED_CONFIDENCE = 0.99; // exact source polygons; quantization ~0.1 m
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

// ---------------------------------------------------- polyline sampling
// Self-contained great-circle sampling; mirrors trifold.api.sample_polyline
// (slerp + xyz conversions match trifold.core exactly).
const EARTH_R = 6371.0088; // km

function lonLatToXyz(lon, lat) {
  const lam = (lon * Math.PI) / 180, phi = (lat * Math.PI) / 180;
  const cp = Math.cos(phi);
  return [cp * Math.cos(lam), cp * Math.sin(lam), Math.sin(phi)];
}

function xyzToLonLat(p) {
  return [
    (Math.atan2(p[1], p[0]) * 180) / Math.PI,
    (Math.asin(Math.max(-1, Math.min(1, p[2]))) * 180) / Math.PI,
  ];
}

function slerp(p, q, t) {
  let dot = p[0] * q[0] + p[1] * q[1] + p[2] * q[2];
  dot = Math.max(-1, Math.min(1, dot));
  const om = Math.acos(dot);
  if (om < 1e-12) return [...p];
  const s = Math.sin(om);
  const a = Math.sin((1 - t) * om) / s, b = Math.sin(t * om) / s;
  return [a * p[0] + b * q[0], a * p[1] + b * q[1], a * p[2] + b * q[2]];
}

function greatCircleKm(lon1, lat1, lon2, lat2) {
  const p = lonLatToXyz(lon1, lat1), q = lonLatToXyz(lon2, lat2);
  let dot = p[0] * q[0] + p[1] * q[1] + p[2] * q[2];
  dot = Math.max(-1, Math.min(1, dot));
  return Math.acos(dot) * EARTH_R;
}

/**
 * Sample a polyline at uniform great-circle intervals.
 * Mirrors trifold.api.sample_polyline.
 * @param {Array<[number, number]>} coords  [lon, lat] vertices (WGS84 degrees)
 * @param {number} stepKm  approximate sample spacing in km (default 3.5)
 * @param {"uniform"|"vertex"} mode  walk segments ('uniform') or vertices only
 * @returns {{samples: Array<[number, number]>, cumulativeKm: number[], segmentIds: number[]}}
 */
export function samplePolyline(coords, stepKm = 3.5, mode = "uniform") {
  if (coords.length < 2) throw new Error("polyline must have at least 2 vertices");
  if (mode !== "uniform" && mode !== "vertex") {
    throw new Error("mode must be 'uniform' or 'vertex'");
  }
  if (mode === "vertex") {
    const samples = coords.map(([lon, lat]) => [lon, lat]);
    const n = coords.length;
    const cumulativeKm = new Array(n).fill(0);
    const segmentIds = new Array(n).fill(0);
    for (let i = 1; i < n; i++) {
      const [lon1, lat1] = coords[i - 1], [lon2, lat2] = coords[i];
      cumulativeKm[i] = cumulativeKm[i - 1] + greatCircleKm(lon1, lat1, lon2, lat2);
      segmentIds[i] = i - 1;
    }
    return { samples, cumulativeKm, segmentIds };
  }
  const samples = [], cumulativeKm = [], segmentIds = [];
  let runningKm = 0;
  for (let segIdx = 0; segIdx < coords.length - 1; segIdx++) {
    const [lon1, lat1] = coords[segIdx], [lon2, lat2] = coords[segIdx + 1];
    const segLen = greatCircleKm(lon1, lat1, lon2, lat2);
    if (samples.length === 0) {
      samples.push([lon1, lat1]); cumulativeKm.push(runningKm); segmentIds.push(segIdx);
    }
    if (segLen < 1e-9) continue;
    const nSteps = Math.max(1, Math.ceil(segLen / stepKm));
    const p1 = lonLatToXyz(lon1, lat1), p2 = lonLatToXyz(lon2, lat2);
    for (let step = 1; step < nSteps; step++) {
      const t = step / nSteps;
      const [slon, slat] = xyzToLonLat(slerp(p1, p2, t));
      samples.push([slon, slat]);
      cumulativeKm.push(runningKm + step * (segLen / nSteps));
      segmentIds.push(segIdx);
    }
    runningKm += segLen;
    samples.push([lon2, lat2]); cumulativeKm.push(runningKm); segmentIds.push(segIdx);
  }
  return { samples, cumulativeKm, segmentIds };
}

/** Merge consecutive samples sharing the same (country, kind) into segments. */
function mergeCountrySegments(results, cumulativeKm) {
  const n = results.length;
  const segments = [];
  let i = 0;
  while (i < n) {
    const { country, kind } = results[i];
    let j = i;
    while (j + 1 < n && results[j + 1].country === country && results[j + 1].kind === kind) j++;
    const startKm = i === 0 ? 0 : (cumulativeKm[i - 1] + cumulativeKm[i]) / 2;
    const endKm = j === n - 1 ? cumulativeKm[n - 1] : (cumulativeKm[j] + cumulativeKm[j + 1]) / 2;
    let confSum = 0;
    for (let k = i; k <= j; k++) confSum += results[k].confidence;
    const r = results[i];
    segments.push({
      country, iso2: r.iso2, name: r.name, kind,
      confidence: confSum / (j - i + 1),
      distanceKm: Math.max(endKm - startKm, 0),
      fraction: 0,
    });
    i = j + 1;
  }
  return segments;
}

// ------------------------------------------------------------- TFCS decoding
async function inflate(compressed) {
  if (typeof DecompressionStream === "function") {
    const ds = new DecompressionStream("deflate"); // zlib wrapper
    const stream = new Blob([compressed]).stream().pipeThrough(ds);
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }
  const zlib = await import("node:zlib"); // older Node fallback
  return new Uint8Array(zlib.inflateSync(compressed));
}

export class CountryCheck {
  /** Build from raw TFCS bytes (ArrayBuffer or Uint8Array). */
  static async fromBytes(bytes) {
    const raw = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
    if (String.fromCharCode(...raw.subarray(0, 4)) !== "TFCS") {
      throw new Error("not a TFCS file");
    }
    const version = raw[4];
    if (version !== 1) throw new Error(`unsupported TFCS version ${version}`);
    const level = raw[5];
    const flags = raw[6];
    const nRuns = view.getUint32(8, true);
    const nBorder = view.getUint32(12, true);
    const nCountries = view.getUint16(16, true);
    const body = await inflate(raw.subarray(20));

    let pos = 0;
    const readVarint = () => {
      let shift = 0, value = 0;
      for (;;) {
        const b = body[pos++];
        value += (b & 0x7f) * Math.pow(2, shift); // values < 2^32, exact
        if (!(b & 0x80)) return value;
        shift += 7;
      }
    };
    const decoder = new TextDecoder();
    const readStr = () => {
      const n = readVarint();
      const s = decoder.decode(body.subarray(pos, pos + n));
      pos += n;
      return s;
    };
    const countries = [];
    for (let i = 0; i < nCountries; i++) {
      countries.push({ code: readStr(), iso2: readStr(), name: readStr() });
    }

    const starts = new Uint32Array(nRuns);
    const ends = new Uint32Array(nRuns);
    const border = new Uint8Array(nRuns);
    const runCid = new Uint16Array(nRuns);
    const borderBefore = new Uint32Array(nRuns);
    let cursor = 0, borderSeen = 0;
    for (let i = 0; i < nRuns; i++) {
      cursor += readVarint();
      const packed = readVarint();
      const length = Math.floor(packed / 2);
      starts[i] = cursor;
      ends[i] = cursor + length;
      borderBefore[i] = borderSeen;
      if (packed & 1) { border[i] = 1; borderSeen += length; }
      else runCid[i] = readVarint();
      cursor += length;
    }
    if (borderSeen !== nBorder) throw new Error("border count mismatch");
    const calls = new Uint16Array(nBorder);
    for (let i = 0; i < nBorder; i++) calls[i] = readVarint();
    const shares = (flags & 1) ? body.subarray(pos) : null;
    if (shares && shares.length < Math.ceil(nBorder / 2)) {
      throw new Error("truncated share block");
    }
    return new CountryCheck(level, countries, starts, ends, border, runCid,
                            borderBefore, calls, shares);
  }

  /** Load via fetch (browser or Node >= 18). */
  static async fromUrl(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`fetch ${url}: ${res.status}`);
    return CountryCheck.fromBytes(await res.arrayBuffer());
  }

  /** Load from the filesystem (Node). Defaults to the bundled dataset. */
  static async fromFile(path) {
    const { readFile } = await import("node:fs/promises");
    if (!path) {
      const { fileURLToPath } = await import("node:url");
      path = fileURLToPath(new URL("../data/countries_L10.tfcs", import.meta.url));
    }
    return CountryCheck.fromBytes(await readFile(path));
  }

  constructor(level, countries, starts, ends, border, runCid, borderBefore,
              calls, shares) {
    this.level = level;
    this.countries = countries;
    this._starts = starts;
    this._ends = ends;
    this._border = border;
    this._runCid = runCid;
    this._borderBefore = borderBefore;
    this._calls = calls;
    this._shares = shares;
    this._refine = null;
  }

  /** Load a TFCR border-refinement dataset (built by build.py). */
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
    if (String.fromCharCode(...raw.subarray(0, 4)) !== "TFCR") {
      throw new Error("not a TFCR file");
    }
    if (raw[4] !== 1) throw new Error(`unsupported TFCR version ${raw[4]}`);
    if (raw[5] !== this.level) throw new Error("TFCR level mismatch");
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
      const nZones = readVarint();
      const zones = [];
      for (let z = 0; z < nZones; z++) {
        const cid = readVarint();
        const nRings = readVarint();
        if (nRings === 0) { zones.push([cid, null]); continue; } // whole cell
        const rings = [];
        for (let r = 0; r < nRings; r++) {
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
        zones.push([cid, rings]);
      }
      cells.set(index, zones);
    }
    this._refine = cells;
  }

  /** Exact country id from the refinement zones; -1 = no country,
   *  null = cell not covered. */
  _refinedCid(index, lon, lat) {
    if (!this._refine) return null;
    const zones = this._refine.get(index);
    if (zones === undefined) return null;
    const ring = indexToLonLatRing(index, this.level);
    const lons = ring.map((p) => p[0]), lats = ring.map((p) => p[1]);
    const minx = Math.min(...lons), maxx = Math.max(...lons);
    const miny = Math.min(...lats), maxy = Math.max(...lats);
    if (maxx > 180 && lon < 0) lon += 360;
    const qx = ((lon - minx) * 65535) / (maxx - minx);
    const qy = ((lat - miny) * 65535) / (maxy - miny);
    for (const [cid, rings] of zones) {
      if (rings === null) return cid;
      let inside = false; // even-odd rule over the zone's rings
      for (const pts of rings) {
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
      if (inside) return cid;
    }
    return -1;
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

  _shareAt(run, index) {
    if (!this._shares) return null;
    const n = this._borderBefore[run] + (index - this._starts[run]);
    const byte = this._shares[n >> 1];
    const q = n & 1 ? byte >> 4 : byte & 0x0f;
    return (q + 0.5) / 16;
  }

  _fields(cid) {
    if (cid === null) return { country: null, iso2: null, name: null };
    const c = this.countries[cid];
    return { country: c.code, iso2: c.iso2, name: c.name };
  }

  /** Full answer: {country, iso2, name, kind, confidence, share, cell, refined}. */
  check(lon, lat) {
    if (!(lon >= -180 && lon <= 180)) throw new RangeError("longitude must be in [-180, 180]");
    if (!(lat >= -90 && lat <= 90)) throw new RangeError("latitude must be in [-90, 90]");
    const index = locateIndex(lon, lat, this.level);
    const run = this._findRun(index);
    const refined = this._refinedCid(index, lon, lat);
    if (refined !== null) {
      const share = run < 0 ? 0 :
        (this._border[run] ? this._shareAt(run, index) : 1);
      return { ...this._fields(refined < 0 ? null : refined), kind: "border",
               confidence: REFINED_CONFIDENCE, share,
               cell: indexToCompact(index, this.level), refined: true };
    }
    if (run < 0) {
      return { country: null, iso2: null, name: null, kind: "none",
               confidence: 1, share: 0, cell: null, refined: false };
    }
    const cell = indexToCompact(index, this.level);
    if (!this._border[run]) {
      return { ...this._fields(this._runCid[run]), kind: "country",
               confidence: 1, share: 1, cell, refined: false };
    }
    const call = this._calls[this._borderBefore[run] + (index - this._starts[run])];
    const share = this._shareAt(run, index);
    return {
      ...this._fields(call === 0 ? null : call - 1),
      kind: "border",
      confidence: share === null ? 0.5 : share,
      share,
      cell,
      refined: false,
    };
  }

  /** Best country code (gid_0) for one point, null = no country. */
  country(lon, lat) {
    const index = locateIndex(lon, lat, this.level);
    const refined = this._refinedCid(index, lon, lat);
    if (refined !== null) return refined < 0 ? null : this.countries[refined].code;
    const run = this._findRun(index);
    if (run < 0) return null;
    if (!this._border[run]) return this.countries[this._runCid[run]].code;
    const call = this._calls[this._borderBefore[run] + (index - this._starts[run])];
    return call === 0 ? null : this.countries[call - 1].code;
  }

  /**
   * Country classification for every segment of a polyline.
   * Samples the line at `stepKm` intervals (or at vertices when
   * `mode==='vertex'`), runs the point lookup per sample, then merges
   * consecutive same-(country, kind) samples into directed,
   * distance-annotated segments. Mirrors Python `check_polyline`.
   * @returns {{segments: object[], totalDistanceKm: number, stats: object, refined: boolean}}
   */
  checkPolyline(coords, { stepKm = 3.5, mode = "uniform" } = {}) {
    const { samples, cumulativeKm } = samplePolyline(coords, stepKm, mode);
    const totalKm = cumulativeKm.length ? cumulativeKm[cumulativeKm.length - 1] : 0;
    const results = samples.map(([lon, lat]) => this.check(lon, lat));
    const segments = mergeCountrySegments(results, cumulativeKm);
    for (const seg of segments) seg.fraction = totalKm > 0 ? seg.distanceKm / totalKm : 0;
    const unique = [...new Set(segments.map((s) => s.country).filter((c) => c))].sort();
    const refined = !!this._refine;
    return {
      segments,
      totalDistanceKm: totalKm,
      stats: {
        totalDistanceKm: totalKm,
        nSegments: segments.length,
        uniqueCountries: unique.length,
        countries: unique,
        refined,
      },
      refined,
    };
  }

  /** Directed country segments for a polyline (segment list only). */
  countryPolyline(coords, opts) {
    return this.checkPolyline(coords, opts).segments;
  }

  /** Dataset summary (for diagnostics). */
  get stats() {
    let interior = 0, borderCells = 0;
    for (let i = 0; i < this._starts.length; i++) {
      const n = this._ends[i] - this._starts[i];
      if (this._border[i]) borderCells += n; else interior += n;
    }
    return {
      level: this.level,
      countries: this.countries.length,
      runs: this._starts.length,
      interiorCells: interior,
      borderCells: borderCells,
      hasShares: !!this._shares,
      hasRefinement: !!this._refine,
    };
  }
}
