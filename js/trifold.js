/**
 * Trifold JavaScript SDK.
 *
 * This module has no runtime dependencies and works in browsers, Node.js,
 * service workers, and Cloudflare Workers. Addresses are represented as
 * BigInt values in code and decimal strings in GeoJSON properties.
 */

export const EARTH_RADIUS_KM = 6371.0088;
export const MAX_LEVEL = 27;
export const EXPORT_DEPTH = 8;

const LEVEL_BITS = 5n;
const PATH_BITS = 2n * BigInt(MAX_LEVEL);
const PATH_MASK = (1n << PATH_BITS) - 1n;
const LON_ROT = 7.3 * Math.PI / 180;
const B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const B32_INV = Object.fromEntries([...B32].map((char, index) => [char, index]));
Object.assign(B32_INV, { I: 1, L: 1, O: 0, U: 27 });

const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];

function norm(point) {
  const length = Math.hypot(point[0], point[1], point[2]);
  return [point[0] / length, point[1] / length, point[2] / length];
}

function validateIdentity(face, digits) {
  if (!Number.isInteger(face) || face < 0 || face >= 20) {
    throw new RangeError(`face ${face} is outside 0..19`);
  }
  if (!Array.isArray(digits) || digits.length > MAX_LEVEL) {
    throw new RangeError(`path level must be within 0..${MAX_LEVEL}`);
  }
  for (const digit of digits) {
    if (!Number.isInteger(digit) || digit < 0 || digit > 3) {
      throw new RangeError(`path digit ${digit} is outside 0..3`);
    }
  }
  return { face, digits: [...digits] };
}

/** Return the rotated unit icosahedron used by Trifold. */
export function icosahedron() {
  const phi = (1 + Math.sqrt(5)) / 2;
  let vertices = [
    [-1, phi, 0], [1, phi, 0], [-1, -phi, 0], [1, -phi, 0],
    [0, -1, phi], [0, 1, phi], [0, -1, -phi], [0, 1, -phi],
    [phi, 0, -1], [phi, 0, 1], [-phi, 0, -1], [-phi, 0, 1],
  ].map(norm);
  const cos = Math.cos(LON_ROT);
  const sin = Math.sin(LON_ROT);
  vertices = vertices.map(point => [
    point[0] * cos - point[1] * sin,
    point[0] * sin + point[1] * cos,
    point[2],
  ]);
  const faces = [
    [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
    [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
    [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
    [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
  ];
  return { vertices, faces };
}

const ICO = icosahedron();
const NORTH = [0, 0, 1];
const SOUTH = [0, 0, -1];

/** Split a spherical triangle into its four aperture-4 children. */
export function subdivide(triangle) {
  const [v0, v1, v2] = triangle;
  const m01 = norm(add(v0, v1));
  const m12 = norm(add(v1, v2));
  const m20 = norm(add(v2, v0));
  return [[v0, m01, m20], [m01, v1, m12], [m20, m12, v2], [m01, m12, m20]];
}

/** Test whether a unit vector lies inside a spherical triangle. */
export function containsPoint(triangle, point) {
  return dot(cross(triangle[0], triangle[1]), point) >= -1e-14 &&
    dot(cross(triangle[1], triangle[2]), point) >= -1e-14 &&
    dot(cross(triangle[2], triangle[0]), point) >= -1e-14;
}

/** Encode a face and base-4 path as an addr64 BigInt. */
export function encode64(face, digits) {
  const identity = validateIdentity(face, digits);
  let path = 0n;
  for (const digit of identity.digits) path = (path << 2n) | BigInt(digit);
  path <<= 2n * BigInt(MAX_LEVEL - identity.digits.length);
  return (BigInt(identity.face) << 59n) | (path << LEVEL_BITS) |
    BigInt(identity.digits.length);
}

/** Decode an addr64 value to `{face, digits}`. */
export function decode64(address) {
  if (typeof address === "number" && !Number.isSafeInteger(address)) {
    throw new RangeError("numeric addr64 values must be safe integers; use BigInt or string");
  }
  const value = typeof address === "bigint" ? address : BigInt(address);
  if (value < 0n || value >= (1n << 64n)) throw new RangeError("addr64 is outside uint64");
  const face = Number((value >> 59n) & 31n);
  const level = Number(value & 31n);
  if (face >= 20 || level > MAX_LEVEL) throw new RangeError("invalid addr64 value");
  const path = (value >> LEVEL_BITS) & PATH_MASK;
  const digits = [];
  for (let index = 0; index < level; index++) {
    const shift = PATH_BITS - 2n * BigInt(index + 1);
    digits.push(Number((path >> shift) & 3n));
  }
  return { face, digits };
}

/** Parse compact, path, addr64, or `{face, digits}` input. */
export function parseAddress(address) {
  if (typeof address === "bigint" || typeof address === "number") return decode64(address);
  if (Array.isArray(address) && address.length === 2) {
    return validateIdentity(Number(address[0]), [...address[1]].map(Number));
  }
  if (address && typeof address === "object" && "face" in address && "digits" in address) {
    return validateIdentity(Number(address.face), [...address.digits].map(Number));
  }
  if (typeof address !== "string") throw new TypeError("unsupported address value");
  const text = decodeURIComponent(address).trim().toUpperCase();
  if (text.startsWith("F")) {
    const [head, tail = ""] = text.split("-");
    if (!/^F\d{1,2}$/.test(head) || !/^[0-3]*$/.test(tail)) {
      throw new Error(`invalid path address ${address}`);
    }
    return validateIdentity(Number(head.slice(1)), [...tail].map(Number));
  }
  if (!text.startsWith("T") || text.length < 3) {
    if (/^\d+$/.test(text)) return decode64(BigInt(text));
    throw new Error(`invalid compact address ${address}`);
  }
  const face = B32_INV[text[1]];
  const level = B32_INV[text[2]];
  if (face === undefined || level === undefined || face >= 20 || level > MAX_LEVEL) {
    throw new Error(`invalid compact address ${address}`);
  }
  const bitCount = 2 * level;
  const charCount = Math.ceil(bitCount / 5);
  if (text.length !== 3 + charCount) throw new Error("invalid compact address length");
  let bits = 0n;
  for (const char of text.slice(3)) {
    if (B32_INV[char] === undefined) throw new Error(`invalid base32 character ${char}`);
    bits = (bits << 5n) | BigInt(B32_INV[char]);
  }
  bits >>= BigInt(charCount * 5 - bitCount);
  const digits = [];
  for (let index = level - 1; index >= 0; index--) {
    digits.push(Number((bits >> BigInt(2 * index)) & 3n));
  }
  return validateIdentity(face, digits);
}

function identityFromArgs(addressOrFace, digits) {
  return Array.isArray(digits)
    ? validateIdentity(addressOrFace, digits)
    : parseAddress(addressOrFace);
}

/** Convert an address to compact Crockford base32. */
export function toCompact(addressOrFace, digits) {
  const identity = identityFromArgs(addressOrFace, digits);
  const level = identity.digits.length;
  const bitCount = 2 * level;
  const charCount = Math.ceil(bitCount / 5);
  let bits = 0n;
  for (const digit of identity.digits) bits = (bits << 2n) | BigInt(digit);
  bits <<= BigInt(charCount * 5 - bitCount);
  let text = `T${B32[identity.face]}${B32[level]}`;
  for (let index = charCount - 1; index >= 0; index--) {
    text += B32[Number((bits >> BigInt(5 * index)) & 31n)];
  }
  return text;
}

export function fromCompact(address) {
  if (typeof address !== "string" || !address.trim().toUpperCase().startsWith("T")) {
    throw new Error("compact addresses start with T");
  }
  return encode64(...identityTuple(parseAddress(address)));
}

/** Convert an address to the `Fxx-digits` path form. */
export function toPath(addressOrFace, digits) {
  const identity = identityFromArgs(addressOrFace, digits);
  return `F${String(identity.face).padStart(2, "0")}-${identity.digits.join("")}`;
}

export function fromPath(address) {
  if (typeof address !== "string" || !address.trim().toUpperCase().startsWith("F")) {
    throw new Error("path addresses start with F");
  }
  return encode64(...identityTuple(parseAddress(address)));
}

function identityTuple(identity) {
  return [identity.face, identity.digits];
}

export function parent64(address) {
  const { face, digits } = decode64(address);
  if (!digits.length) throw new RangeError("level-0 cell has no parent");
  return encode64(face, digits.slice(0, -1));
}

export function children64(address) {
  const { face, digits } = decode64(address);
  if (digits.length >= MAX_LEVEL) throw new RangeError("cell is at the maximum level");
  return [0, 1, 2, 3].map(digit => encode64(face, [...digits, digit]));
}

export function isAncestor(ancestor, descendant) {
  const a = decode64(ancestor);
  const b = decode64(descendant);
  return a.face === b.face && a.digits.length <= b.digits.length &&
    a.digits.every((digit, index) => digit === b.digits[index]);
}

export function descendantRange(address) {
  const { face, digits } = decode64(address);
  const value = encode64(face, digits);
  const suffixBits = PATH_BITS - 2n * BigInt(digits.length);
  const path = (value >> LEVEL_BITS) & PATH_MASK;
  const highPath = path | (suffixBits ? (1n << suffixBits) - 1n : 0n);
  return [value, (BigInt(face) << 59n) | (highPath << LEVEL_BITS) | BigInt(MAX_LEVEL)];
}

/** Return the spherical triangle for an address. */
export function cellTriangle(addressOrFace, digits) {
  const identity = identityFromArgs(addressOrFace, digits);
  const [i, j, k] = ICO.faces[identity.face];
  let triangle = [ICO.vertices[i], ICO.vertices[j], ICO.vertices[k]];
  for (const digit of identity.digits) triangle = subdivide(triangle)[digit];
  return triangle;
}

/** Locate a point and return `{face, digits}`. */
export function locate(lon, lat, level) {
  if (!Number.isFinite(lon) || lon < -180 || lon > 180) {
    throw new RangeError("longitude must be within [-180, 180]");
  }
  if (!Number.isFinite(lat) || lat < -90 || lat > 90) {
    throw new RangeError("latitude must be within [-90, 90]");
  }
  if (!Number.isInteger(level) || level < 0 || level > MAX_LEVEL) {
    throw new RangeError(`level must be within 0..${MAX_LEVEL}`);
  }
  const lambda = lon * Math.PI / 180;
  const phi = lat * Math.PI / 180;
  const point = [Math.cos(phi) * Math.cos(lambda), Math.cos(phi) * Math.sin(lambda), Math.sin(phi)];
  let face = -1;
  let triangle = null;
  for (let index = 0; index < 20; index++) {
    const candidate = cellTriangle(index, []);
    if (containsPoint(candidate, point)) {
      face = index;
      triangle = candidate;
      break;
    }
  }
  if (face < 0) {
    let best = -2;
    for (let index = 0; index < 20; index++) {
      const [i, j, k] = ICO.faces[index];
      const centre = norm(add(add(ICO.vertices[i], ICO.vertices[j]), ICO.vertices[k]));
      const score = dot(centre, point);
      if (score > best) {
        best = score;
        face = index;
      }
    }
    triangle = cellTriangle(face, []);
  }
  const digits = [];
  for (let current = 0; current < level; current++) {
    const children = subdivide(triangle);
    let selected = -1;
    let bestMargin = -2;
    for (let digit = 0; digit < 4; digit++) {
      const child = children[digit];
      const margin = Math.min(
        dot(cross(child[0], child[1]), point),
        dot(cross(child[1], child[2]), point),
        dot(cross(child[2], child[0]), point),
      );
      if (margin >= -1e-14) {
        selected = digit;
        break;
      }
      if (margin > bestMargin) {
        bestMargin = margin;
        selected = digit;
      }
    }
    digits.push(selected);
    triangle = children[selected];
  }
  return { face, digits };
}

export function locateAddress(lon, lat, level) {
  const identity = locate(lon, lat, level);
  return encode64(identity.face, identity.digits);
}

export function edgeKm(triangle) {
  const edges = [[triangle[0], triangle[1]], [triangle[1], triangle[2]], [triangle[2], triangle[0]]];
  const angles = edges.map(([a, b]) => Math.acos(Math.max(-1, Math.min(1, dot(a, b)))));
  return angles.reduce((sum, angle) => sum + angle, 0) / angles.length * EARTH_RADIUS_KM;
}

export function areaKm2(triangle) {
  const angle = (a, b, c) => {
    const n1 = cross(a, b);
    const n2 = cross(a, c);
    return Math.acos(Math.max(-1, Math.min(1,
      dot(n1, n2) / (Math.hypot(...n1) * Math.hypot(...n2)))));
  };
  const excess = angle(triangle[0], triangle[1], triangle[2]) +
    angle(triangle[1], triangle[2], triangle[0]) +
    angle(triangle[2], triangle[0], triangle[1]) - Math.PI;
  return excess * EARTH_RADIUS_KM ** 2;
}

function edgePoints(a, b, halvings) {
  if (halvings <= 0) return [a];
  const midpoint = norm(add(a, b));
  return [...edgePoints(a, midpoint, halvings - 1), ...edgePoints(midpoint, b, halvings - 1)];
}

function toLonLat(point) {
  return [
    Math.atan2(point[1], point[0]) * 180 / Math.PI,
    Math.asin(Math.max(-1, Math.min(1, point[2]))) * 180 / Math.PI,
  ];
}

function recenter(ring) {
  const mean = ring.reduce((sum, point) => sum + point[0], 0) / ring.length;
  let shift = 0;
  while (mean + shift > 180) shift -= 360;
  while (mean + shift <= -180) shift += 360;
  return ring.map(([lon, lat]) => [lon + shift, lat]);
}

function unwrap(points) {
  const ring = [];
  let previous = null;
  let offset = 0;
  for (const point of points) {
    let [lon, lat] = toLonLat(point);
    lon += offset;
    if (previous !== null) {
      while (lon - previous > 180) { lon -= 360; offset -= 360; }
      while (lon - previous < -180) { lon += 360; offset += 360; }
    }
    ring.push([lon, lat]);
    previous = lon;
  }
  return recenter(ring);
}

function exportRing(points, triangle) {
  const poleIndexes = points.map((point, index) => Math.abs(point[2]) >= 1 - 1e-9 ? index : -1)
    .filter(index => index >= 0);
  if (poleIndexes.length) {
    const poleLatitude = points[poleIndexes[0]][2] > 0 ? 90 : -90;
    const poleSet = new Set(poleIndexes);
    const longitudes = {};
    let previous = null;
    let offset = 0;
    for (let index = 0; index < points.length; index++) {
      if (poleSet.has(index)) continue;
      let [lon, lat] = toLonLat(points[index]);
      lon += offset;
      if (previous !== null) {
        while (lon - previous > 180) { lon -= 360; offset -= 360; }
        while (lon - previous < -180) { lon += 360; offset += 360; }
      }
      longitudes[index] = [lon, lat];
      previous = lon;
    }
    const ring = [];
    const count = points.length;
    for (let index = 0; index < count; index++) {
      if (!poleSet.has(index)) {
        ring.push(longitudes[index]);
        continue;
      }
      let before = (index - 1 + count) % count;
      let after = (index + 1) % count;
      while (poleSet.has(before)) before = (before - 1 + count) % count;
      while (poleSet.has(after)) after = (after + 1) % count;
      ring.push([longitudes[before][0], poleLatitude], [longitudes[after][0], poleLatitude]);
    }
    return { ring: recenter(ring), pole: "vertex" };
  }
  if (containsPoint(triangle, NORTH) || containsPoint(triangle, SOUTH)) {
    const north = containsPoint(triangle, NORTH);
    const poleLatitude = north ? 90 : -90;
    const ring = points.map(toLonLat).sort((a, b) => a[0] - b[0]);
    ring.push([180, poleLatitude], [-180, poleLatitude]);
    return { ring, pole: "interior" };
  }
  return { ring: unwrap(points), pole: "" };
}

/** Return a closed cell boundary as continuous-longitude coordinates. */
export function cellRing(address, { depth = EXPORT_DEPTH, precision = 6 } = {}) {
  const identity = parseAddress(address);
  const triangle = cellTriangle(identity);
  const halvings = Math.max(0, depth - identity.digits.length);
  const points = [
    ...edgePoints(triangle[0], triangle[1], halvings),
    ...edgePoints(triangle[1], triangle[2], halvings),
    ...edgePoints(triangle[2], triangle[0], halvings),
  ];
  const exported = exportRing(points, triangle);
  const ring = exported.ring.map(([lon, lat]) => [
    Number(lon.toFixed(precision)),
    Number(lat.toFixed(precision)),
  ]);
  ring.push([...ring[0]]);
  return ring;
}

export function cellMetrics(address) {
  const identity = parseAddress(address);
  const value = encode64(identity.face, identity.digits);
  const triangle = cellTriangle(identity);
  return {
    id: toCompact(identity),
    path: toPath(identity),
    addr64: value,
    face: identity.face,
    level: identity.digits.length,
    edgeKm: edgeKm(triangle),
    areaKm2: areaKm2(triangle),
  };
}

/** Return a GeoJSON Feature for one address. */
export function cellFeature(address, { precision = 6 } = {}) {
  const identity = parseAddress(address);
  const value = encode64(identity.face, identity.digits);
  const triangle = cellTriangle(identity);
  const halvings = Math.max(0, EXPORT_DEPTH - identity.digits.length);
  const points = [
    ...edgePoints(triangle[0], triangle[1], halvings),
    ...edgePoints(triangle[1], triangle[2], halvings),
    ...edgePoints(triangle[2], triangle[0], halvings),
  ];
  const exported = exportRing(points, triangle);
  const ring = exported.ring.map(([lon, lat]) => [
    Number(lon.toFixed(precision)),
    Number(lat.toFixed(precision)),
  ]);
  ring.push([...ring[0]]);
  return {
    type: "Feature",
    properties: {
      id: toCompact(identity),
      path: toPath(identity),
      addr64: value.toString(),
      level: identity.digits.length,
      pole: exported.pole,
    },
    geometry: { type: "Polygon", coordinates: [ring] },
  };
}

/** Enumerate all cells on one face, or all faces, at a uniform level. */
export function levelFeatureCollection(level, { face = null, maxLevel = 5 } = {}) {
  if (!Number.isInteger(level) || level < 0 || level > maxLevel) {
    throw new RangeError(`level must be within 0..${maxLevel}`);
  }
  const faces = face === null ? [...Array(20).keys()] : [Number(face)];
  faces.forEach(value => validateIdentity(value, []));
  const features = [];
  const generate = (currentFace, digits) => {
    if (digits.length === level) {
      features.push(cellFeature({ face: currentFace, digits }));
      return;
    }
    for (let digit = 0; digit < 4; digit++) generate(currentFace, [...digits, digit]);
  };
  for (const currentFace of faces) generate(currentFace, []);
  return { type: "FeatureCollection", features };
}
