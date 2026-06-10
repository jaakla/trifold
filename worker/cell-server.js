/**
 * Trifold cell server — Cloudflare Worker (free tier friendly).
 *
 * Generates cell geometry on the fly from addresses; no stored data.
 *
 * Endpoints (all return JSON, CORS enabled):
 *   GET /cell/{addr}                GeoJSON Feature for a cell
 *   GET /cells/{addr1},{addr2},...  FeatureCollection (max 500)
 *   GET /locate/{lon},{lat}?level=N address containing a point
 *   GET /parent/{addr}              parent address
 *   GET /children/{addr}            4 child addresses
 *   GET /level/{N}?face=F           FeatureCollection of one face at level N
 *                                   (N<=5 to stay within CPU limits)
 *
 * {addr} accepts compact base32 ('TF6958') or digit path ('F15-102111').
 *
 * Deploy:  npx wrangler deploy worker/cell-server.js
 */

// ---------------------------------------------------------- icosahedron
const LON_ROT = 7.3 * Math.PI / 180;

function icosahedron() {
  const phi = (1 + Math.sqrt(5)) / 2;
  let v = [
    [-1, phi, 0], [1, phi, 0], [-1, -phi, 0], [1, -phi, 0],
    [0, -1, phi], [0, 1, phi], [0, -1, -phi], [0, 1, -phi],
    [phi, 0, -1], [phi, 0, 1], [-phi, 0, -1], [-phi, 0, 1],
  ].map(norm);
  const c = Math.cos(LON_ROT), s = Math.sin(LON_ROT);
  v = v.map(p => [p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2]]);
  const faces = [
    [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
    [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
    [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
    [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
  ];
  return { v, faces };
}
const ICO = icosahedron();

function norm(p) {
  const n = Math.hypot(p[0], p[1], p[2]);
  return [p[0] / n, p[1] / n, p[2] / n];
}
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1],
                         a[2] * b[0] - a[0] * b[2],
                         a[0] * b[1] - a[1] * b[0]];

function subdivide(t) {
  const [v0, v1, v2] = t;
  const m01 = norm(add(v0, v1)), m12 = norm(add(v1, v2)), m20 = norm(add(v2, v0));
  return [[v0, m01, m20], [m01, v1, m12], [m20, m12, v2], [m01, m12, m20]];
}

function containsPoint(t, p) {
  return dot(cross(t[0], t[1]), p) >= -1e-14 &&
         dot(cross(t[1], t[2]), p) >= -1e-14 &&
         dot(cross(t[2], t[0]), p) >= -1e-14;
}

function cellTriangle(face, digits) {
  const [i, j, k] = ICO.faces[face];
  let tri = [ICO.v[i], ICO.v[j], ICO.v[k]];
  for (const d of digits) tri = subdivide(tri)[d];
  return tri;
}

function locate(lon, lat, level) {
  const lam = lon * Math.PI / 180, phi = lat * Math.PI / 180;
  const p = [Math.cos(phi) * Math.cos(lam), Math.cos(phi) * Math.sin(lam),
             Math.sin(phi)];
  let face = -1, tri = null;
  for (let f = 0; f < 20; f++) {
    const t = cellTriangle(f, []);
    if (containsPoint(t, p)) { face = f; tri = t; break; }
  }
  if (face < 0) {  // numeric fallback: face with max-centre dot
    let best = -2;
    for (let f = 0; f < 20; f++) {
      const [i, j, k] = ICO.faces[f];
      const c = norm(add(add(ICO.v[i], ICO.v[j]), ICO.v[k]));
      if (dot(c, p) > best) { best = dot(c, p); face = f; }
    }
    tri = cellTriangle(face, []);
  }
  const digits = [];
  for (let l = 0; l < level; l++) {
    const ch = subdivide(tri);
    let pick = -1, bestMargin = -2;
    for (let d = 0; d < 4; d++) {
      const m = Math.min(dot(cross(ch[d][0], ch[d][1]), p),
                         dot(cross(ch[d][1], ch[d][2]), p),
                         dot(cross(ch[d][2], ch[d][0]), p));
      if (m >= -1e-14) { pick = d; break; }
      if (m > bestMargin) { bestMargin = m; pick = d; }
    }
    digits.push(pick);
    tri = ch[pick];
  }
  return { face, digits };
}

// ---------------------------------------------------------- addressing
const B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const B32_INV = {}; [...B32].forEach((c, i) => B32_INV[c] = i);
B32_INV.I = 1; B32_INV.L = 1; B32_INV.O = 0; B32_INV.U = 27;

function toCompact(face, digits) {
  const L = digits.length;
  const nbits = 2 * L, nchars = Math.ceil(nbits / 5);
  let bits = 0n;
  for (const d of digits) bits = (bits << 2n) | BigInt(d);
  bits <<= BigInt(nchars * 5 - nbits);
  let s = 'T' + B32[face] + B32[L];
  for (let i = nchars - 1; i >= 0; i--)
    s += B32[Number((bits >> BigInt(5 * i)) & 31n)];
  return s;
}

function parseAddr(s) {
  s = decodeURIComponent(s).trim().toUpperCase();
  if (s.startsWith('F')) {                       // digit path form
    const [head, tail = ''] = s.split('-');
    return { face: parseInt(head.slice(1), 10),
             digits: [...tail].map(Number) };
  }
  if (!s.startsWith('T') || s.length < 3) throw new Error('bad address');
  const face = B32_INV[s[1]], L = B32_INV[s[2]];
  const nbits = 2 * L, nchars = Math.ceil(nbits / 5);
  if (s.length !== 3 + nchars) throw new Error('bad address length');
  let bits = 0n;
  for (const c of s.slice(3)) bits = (bits << 5n) | BigInt(B32_INV[c]);
  bits >>= BigInt(nchars * 5 - nbits);
  const digits = [];
  for (let i = L - 1; i >= 0; i--)
    digits.push(Number((bits >> BigInt(2 * i)) & 3n));
  return { face, digits };
}

function toPath(face, digits) {
  return 'F' + String(face).padStart(2, '0') + '-' + digits.join('');
}

function toAddr64(face, digits) {
  let path = 0n;
  for (const d of digits) path = (path << 2n) | BigInt(d);
  path <<= BigInt(2 * (27 - digits.length));
  return ((BigInt(face) << 59n) | (BigInt(digits.length) << 54n) | path)
         .toString();
}

// ---------------------------------------------------------- geometry out
const EXPORT_DEPTH = 8;

function edgePoints(a, b, halvings) {
  if (halvings <= 0) return [a];
  const m = norm(add(a, b));
  return [...edgePoints(a, m, halvings - 1), ...edgePoints(m, b, halvings - 1)];
}

function toLonLat(p) {
  return [Math.atan2(p[1], p[0]) * 180 / Math.PI,
          Math.asin(Math.max(-1, Math.min(1, p[2]))) * 180 / Math.PI];
}

function cellRing(face, digits) {
  const tri = cellTriangle(face, digits);
  const h = Math.max(0, EXPORT_DEPTH - digits.length);
  const pts = [
    ...edgePoints(tri[0], tri[1], h),
    ...edgePoints(tri[1], tri[2], h),
    ...edgePoints(tri[2], tri[0], h)];

  // pole-vertex wedge handling
  const poleIdx = pts.map((p, i) => Math.abs(p[2]) >= 1 - 1e-9 ? i : -1)
                     .filter(i => i >= 0);
  const n = pts.length;
  const ring = [];
  if (poleIdx.length) {
    const polelat = pts[poleIdx[0]][2] > 0 ? 90 : -90;
    const lonlat = {};
    let prev = null, off = 0;
    for (let i = 0; i < n; i++) {
      if (poleIdx.includes(i)) continue;
      let [lon, lat] = toLonLat(pts[i]);
      lon += off;
      if (prev !== null) {
        while (lon - prev > 180) { lon -= 360; off -= 360; }
        while (lon - prev < -180) { lon += 360; off += 360; }
      }
      lonlat[i] = [lon, lat]; prev = lon;
    }
    for (let i = 0; i < n; i++) {
      if (poleIdx.includes(i)) {
        let ip = (i - 1 + n) % n, inx = (i + 1) % n;
        while (poleIdx.includes(ip)) ip = (ip - 1 + n) % n;
        while (poleIdx.includes(inx)) inx = (inx + 1) % n;
        ring.push([lonlat[ip][0], polelat], [lonlat[inx][0], polelat]);
      } else ring.push(lonlat[i]);
    }
  } else {
    let prev = null, off = 0;
    for (const p of pts) {
      let [lon, lat] = toLonLat(p);
      lon += off;
      if (prev !== null) {
        while (lon - prev > 180) { lon -= 360; off -= 360; }
        while (lon - prev < -180) { lon += 360; off += 360; }
      }
      ring.push([lon, lat]); prev = lon;
    }
  }
  // recentre
  const mean = ring.reduce((s, q) => s + q[0], 0) / ring.length;
  let shift = 0;
  while (mean + shift > 180) shift -= 360;
  while (mean + shift <= -180) shift += 360;
  const out = ring.map(q => [+(q[0] + shift).toFixed(6), +q[1].toFixed(6)]);
  out.push(out[0]);
  return out;
}

function cellFeature(face, digits) {
  const ring = cellRing(face, digits);
  return {
    type: 'Feature',
    properties: {
      id: toCompact(face, digits),
      path: toPath(face, digits),
      addr64: toAddr64(face, digits),
      level: digits.length,
    },
    geometry: { type: 'Polygon', coordinates: [ring] },
  };
}

// ---------------------------------------------------------- HTTP
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Content-Type': 'application/json',
  'Cache-Control': 'public, max-age=86400',
};
const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: CORS });

export default {
  async fetch(req) {
    const url = new URL(req.url);
    const seg = url.pathname.split('/').filter(Boolean);
    try {
      if (seg[0] === 'cell' && seg[1]) {
        const { face, digits } = parseAddr(seg[1]);
        return json(cellFeature(face, digits));
      }
      if (seg[0] === 'cells' && seg[1]) {
        const addrs = seg[1].split(',').slice(0, 500);
        return json({ type: 'FeatureCollection',
          features: addrs.map(a => {
            const { face, digits } = parseAddr(a);
            return cellFeature(face, digits);
          }) });
      }
      if (seg[0] === 'locate' && seg[1]) {
        const [lon, lat] = seg[1].split(',').map(Number);
        const level = Math.min(27,
          parseInt(url.searchParams.get('level') ?? '6', 10));
        const { face, digits } = locate(lon, lat, level);
        return json({ id: toCompact(face, digits),
                      path: toPath(face, digits),
                      addr64: toAddr64(face, digits), level });
      }
      if (seg[0] === 'parent' && seg[1]) {
        const { face, digits } = parseAddr(seg[1]);
        if (!digits.length) return json({ error: 'level-0 has no parent' }, 400);
        return json({ id: toCompact(face, digits.slice(0, -1)) });
      }
      if (seg[0] === 'children' && seg[1]) {
        const { face, digits } = parseAddr(seg[1]);
        return json({ ids: [0, 1, 2, 3].map(d =>
          toCompact(face, [...digits, d])) });
      }
      if (seg[0] === 'level' && seg[1]) {
        const L = parseInt(seg[1], 10);
        if (L > 5) return json({ error: 'level > 5: use /cells or PMTiles' }, 400);
        const faceParam = url.searchParams.get('face');
        const facesToDo = faceParam !== null
          ? [parseInt(faceParam, 10)] : [...Array(20).keys()];
        const feats = [];
        const gen = (face, digits) => {
          if (digits.length === L) { feats.push(cellFeature(face, digits)); return; }
          for (let d = 0; d < 4; d++) gen(face, [...digits, d]);
        };
        for (const f of facesToDo) gen(f, []);
        return json({ type: 'FeatureCollection', features: feats });
      }
      return json({
        endpoints: ['/cell/{addr}', '/cells/{a1},{a2},…', '/locate/{lon},{lat}?level=N',
                    '/parent/{addr}', '/children/{addr}', '/level/{N}?face=F'],
        example: '/locate/-0.1276,51.5072?level=6  ->  TF6958',
      });
    } catch (e) {
      return json({ error: String(e.message ?? e) }, 400);
    }
  },
};
