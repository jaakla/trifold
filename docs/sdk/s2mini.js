// s2mini.js — a minimal, self-contained Google S2 implementation for the
// Trifold coverage demo. Just enough to cover a drawn bbox/polygon with S2
// cells at a fixed level, compact them (4 siblings -> parent), and draw them.
//
// Cell ids are BigInt (S2's 64-bit S2CellId layout: 3 face bits, 2 bits per
// level along the Hilbert curve, then a trailing "1" sentinel marking depth).
// Geometry uses S2's quadratic UV<->ST projection so cells line up with the
// reference s2sphere boundaries. Not a full S2 port: fixed-level covering
// only, planar lon/lat overlap tests (fine at demo scales).

const MASK64 = (1n << 64n) - 1n;
const MAX_LEVEL = 30;

const kSwapMask = 0x01;
const kInvertMask = 0x02;
// Hilbert traversal tables (identical to s2geometry s2coords).
const kPosToIJ = [
  [0, 1, 3, 2],
  [0, 2, 3, 1],
  [3, 2, 0, 1],
  [3, 1, 0, 2],
];
const kPosToOrientation = [kSwapMask, 0, 0, kSwapMask | kInvertMask];
// inverse of kPosToIJ: ij -> pos, per orientation
const kIJToPos = kPosToIJ.map((row) => {
  const inv = [0, 0, 0, 0];
  row.forEach((ij, pos) => { inv[ij] = pos; });
  return inv;
});

const D2R = Math.PI / 180;
const R2D = 180 / Math.PI;
const EARTH_AREA_KM2 = 4 * Math.PI * 6371.0088 * 6371.0088;

// ---- projection helpers -------------------------------------------------

function lonLatToXYZ(lon, lat) {
  const lr = lat * D2R;
  const gr = lon * D2R;
  const c = Math.cos(lr);
  return [c * Math.cos(gr), c * Math.sin(gr), Math.sin(lr)];
}

function xyzToLonLat([x, y, z]) {
  const lat = Math.atan2(z, Math.hypot(x, y)) * R2D;
  const lon = Math.atan2(y, x) * R2D;
  return [lon, lat];
}

function getFace([x, y, z]) {
  const ax = Math.abs(x), ay = Math.abs(y), az = Math.abs(z);
  let face;
  if (ax > ay) face = ax > az ? 0 : 2;
  else face = ay > az ? 1 : 2;
  const v = face === 0 ? x : face === 1 ? y : z;
  if (v < 0) face += 3;
  return face;
}

function validFaceXYZtoUV(face, [x, y, z]) {
  switch (face) {
    case 0: return [y / x, z / x];
    case 1: return [-x / y, z / y];
    case 2: return [-x / z, -y / z];
    case 3: return [z / x, y / x];
    case 4: return [z / y, -x / y];
    default: return [-y / z, -x / z];
  }
}

function faceUVtoXYZ(face, u, v) {
  switch (face) {
    case 0: return [1, u, v];
    case 1: return [-u, 1, v];
    case 2: return [-u, -v, 1];
    case 3: return [-1, -v, -u];
    case 4: return [v, -1, -u];
    default: return [v, u, -1];
  }
}

// quadratic UV<->ST
function uvToST(u) {
  return u >= 0 ? 0.5 * Math.sqrt(1 + 3 * u) : 1 - 0.5 * Math.sqrt(1 - 3 * u);
}
function stToUV(s) {
  return s >= 0.5 ? (1 / 3) * (4 * s * s - 1) : (1 / 3) * (1 - 4 * (1 - s) * (1 - s));
}

function clampIndex(value, size) {
  return value < 0 ? 0 : value >= size ? size - 1 : value;
}

// ---- cell id <-> (face, i, j, level) ------------------------------------

function ijToPos(face, i, j, level) {
  let bits = face & kSwapMask;
  let pos = 0;
  for (let k = level - 1; k >= 0; k--) {
    const ij = (((i >> k) & 1) << 1) | ((j >> k) & 1);
    const sub = kIJToPos[bits][ij];
    pos = pos * 4 + sub;
    bits ^= kPosToOrientation[sub];
  }
  return pos;
}

function posToIJ(face, posBig, level) {
  let bits = face & kSwapMask;
  let i = 0, j = 0;
  for (let k = level - 1; k >= 0; k--) {
    const sub = Number((posBig >> BigInt(2 * k)) & 3n);
    const ij = kPosToIJ[bits][sub];
    i = (i << 1) | (ij >> 1);
    j = (j << 1) | (ij & 1);
    bits ^= kPosToOrientation[sub];
  }
  return [i, j];
}

function cellId(face, i, j, level) {
  const pos = BigInt(ijToPos(face, i, j, level));
  const shift = BigInt(61 - 2 * level);
  return (BigInt(face) << 61n) | (pos << shift) | (1n << BigInt(60 - 2 * level));
}

function lsbOf(id) { return id & (((~id) & MASK64) + 1n) & MASK64; }

function levelOf(id) {
  let x = lsbOf(id), tz = 0;
  while ((x & 1n) === 0n) { x >>= 1n; tz++; }
  return MAX_LEVEL - (tz >> 1);
}

function faceOf(id) { return Number((id >> 61n) & 7n); }

function parentOf(id) {
  const newLsb = lsbOf(id) << 2n;
  return ((id & (MASK64 ^ (newLsb - 1n))) | newLsb) & MASK64;
}

function decodeCell(id) {
  const level = levelOf(id);
  const face = faceOf(id);
  const pos = (id >> BigInt(61 - 2 * level)) & ((1n << BigInt(2 * level)) - 1n);
  const [i, j] = posToIJ(face, pos, level);
  return { face, level, i, j };
}

function cellOfLonLat(lon, lat, level) {
  const xyz = lonLatToXYZ(lon, lat);
  const face = getFace(xyz);
  const [u, v] = validFaceXYZtoUV(face, xyz);
  const size = 1 << level;
  const i = clampIndex(Math.floor(uvToST(u) * size), size);
  const j = clampIndex(Math.floor(uvToST(v) * size), size);
  return cellId(face, i, j, level);
}

// ---- geometry -----------------------------------------------------------

function cornerLonLat(face, i, j, size) {
  const xyz = faceUVtoXYZ(face, stToUV(i / size), stToUV(j / size));
  return xyzToLonLat(xyz);
}

// boundary ring (lon/lat), densified a little so the spherical edges curve
function cellBoundaryRing(id, segs = 4) {
  const { face, level, i, j } = decodeCell(id);
  const size = 1 << level;
  const ij = [[i, j], [i + 1, j], [i + 1, j + 1], [i, j + 1]];
  const ring = [];
  for (let e = 0; e < 4; e++) {
    const [ai, aj] = ij[e];
    const [bi, bj] = ij[(e + 1) % 4];
    for (let s = 0; s < segs; s++) {
      const t = s / segs;
      ring.push(cornerLonLat(face, ai + (bi - ai) * t, aj + (bj - aj) * t, size));
    }
  }
  ring.push(ring[0].slice());
  return ring;
}

function cellCenterLonLat(id) {
  const { face, level, i, j } = decodeCell(id);
  const size = 1 << level;
  return cornerLonLat(face, i + 0.5, j + 0.5, size);
}

export function s2CellFeature(id, { precision = 5 } = {}) {
  const ring = cellBoundaryRing(id).map(([lon, lat]) =>
    [Number(lon.toFixed(precision)), Number(lat.toFixed(precision))]);
  return {
    type: 'Feature',
    properties: { s2: id.toString(16), level: levelOf(id) },
    geometry: { type: 'Polygon', coordinates: [ring] },
  };
}

// ---- level matching -----------------------------------------------------

export function s2LevelArea(level) {
  return EARTH_AREA_KM2 / (6 * Math.pow(4, level));
}

// pick the S2 level whose mean cell area is closest to a T3 level's area
export function s2LevelForT3(t3Level) {
  const t3Area = 25.5e6 / Math.pow(4, t3Level); // T3 L0 ~ 25.5M km^2, aperture 4
  let best = 0, bestErr = Infinity;
  for (let l = 0; l <= MAX_LEVEL; l++) {
    const err = Math.abs(Math.log(s2LevelArea(l) / t3Area));
    if (err < bestErr) { bestErr = err; best = l; }
  }
  return best;
}

// ---- overlap predicates -------------------------------------------------

function pointInRing(lon, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    if ((yi > lat) !== (yj > lat) &&
        lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function segIntersect(a, b, c, d) {
  const o = (p, q, r) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  const d1 = o(c, d, a), d2 = o(c, d, b), d3 = o(a, b, c), d4 = o(a, b, d);
  return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
}

function ringsOverlap(cellRing, queryRing) {
  for (const [lon, lat] of cellRing) if (pointInRing(lon, lat, queryRing)) return true;
  for (const [lon, lat] of queryRing) if (pointInRing(lon, lat, cellRing)) return true;
  for (let i = 0; i < cellRing.length - 1; i++)
    for (let j = 0; j < queryRing.length - 1; j++)
      if (segIntersect(cellRing[i], cellRing[i + 1], queryRing[j], queryRing[j + 1])) return true;
  return false;
}

// ---- covering -----------------------------------------------------------

function queryRing(query) {
  if (query.kind === 'bbox') {
    const [w, s, e, n] = query.bbox;
    return [[w, s], [e, s], [e, n], [w, n], [w, s]];
  }
  const coords = query.geometry.coordinates[0];
  const ring = coords.map(([lon, lat]) => [lon, lat]);
  if (ring.length && (ring[0][0] !== ring[ring.length - 1][0] ||
      ring[0][1] !== ring[ring.length - 1][1])) ring.push(ring[0].slice());
  return ring;
}

// densify the query boundary so we discover every cube face it touches and
// get tight (i,j) ranges per face
function sampleBoundary(ring, perEdge = 24) {
  const pts = [];
  for (let i = 0; i < ring.length - 1; i++) {
    const [ax, ay] = ring[i], [bx, by] = ring[i + 1];
    for (let s = 0; s < perEdge; s++) {
      const t = s / perEdge;
      pts.push([ax + (bx - ax) * t, ay + (by - ay) * t]);
    }
  }
  // include a centroid-ish interior point
  const cx = ring.reduce((a, p) => a + p[0], 0) / ring.length;
  const cy = ring.reduce((a, p) => a + p[1], 0) / ring.length;
  pts.push([cx, cy]);
  return pts;
}

const COVER_CELL_CAP = 50000;

// Returns { cells: BigInt[], capped: bool }
export function s2Cover(query, level, { mode = 'intersects', cap = COVER_CELL_CAP } = {}) {
  const ring = queryRing(query);
  const size = 1 << level;
  const samples = sampleBoundary(ring);

  // per-face (i,j) ranges from the boundary samples
  const ranges = new Map(); // face -> {imin,imax,jmin,jmax}
  for (const [lon, lat] of samples) {
    const xyz = lonLatToXYZ(lon, lat);
    const face = getFace(xyz);
    const [u, v] = validFaceXYZtoUV(face, xyz);
    const i = clampIndex(Math.floor(uvToST(u) * size), size);
    const j = clampIndex(Math.floor(uvToST(v) * size), size);
    const r = ranges.get(face);
    if (!r) ranges.set(face, { imin: i, imax: i, jmin: j, jmax: j });
    else {
      if (i < r.imin) r.imin = i; if (i > r.imax) r.imax = i;
      if (j < r.jmin) r.jmin = j; if (j > r.jmax) r.jmax = j;
    }
  }

  const out = [];
  const seen = new Set();
  let capped = false;
  for (const [face, r] of ranges) {
    // pad by one cell so footprints straddling the sampled edge are caught
    const imin = Math.max(0, r.imin - 1), imax = Math.min(size - 1, r.imax + 1);
    const jmin = Math.max(0, r.jmin - 1), jmax = Math.min(size - 1, r.jmax + 1);
    if ((imax - imin + 1) * (jmax - jmin + 1) > cap * 4) { capped = true; continue; }
    for (let i = imin; i <= imax; i++) {
      for (let j = jmin; j <= jmax; j++) {
        const id = cellId(face, i, j, level);
        const key = id.toString();
        if (seen.has(key)) continue;
        let hit;
        if (mode === 'centroid') {
          const [clon, clat] = cellCenterLonLat(id);
          hit = pointInRing(clon, clat, ring);
        } else {
          hit = ringsOverlap(cellBoundaryRing(id, 1), ring);
        }
        if (hit) {
          seen.add(key);
          out.push(id);
          if (out.length > cap) return { cells: out, capped: true };
        }
      }
    }
  }
  return { cells: out, capped };
}

export function s2Compact(ids) {
  let current = [...new Set(ids.map((x) => x.toString()))].map(BigInt);
  let changed = true;
  while (changed) {
    changed = false;
    const groups = new Map();
    const next = [];
    for (const cell of current) {
      if (levelOf(cell) === 0) { next.push(cell); continue; }
      const parent = parentOf(cell);
      const key = parent.toString();
      if (!groups.has(key)) groups.set(key, { parent, children: [] });
      groups.get(key).children.push(cell);
    }
    for (const g of groups.values()) {
      if (g.children.length === 4) { next.push(g.parent); changed = true; }
      else next.push(...g.children);
    }
    current = [...new Set(next.map((x) => x.toString()))].map(BigInt);
  }
  return current.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

// exported for validation/tests
export const _internal = { cellOfLonLat, levelOf, parentOf, decodeCell, cellId };
