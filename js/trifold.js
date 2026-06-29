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
const COVER_EPS = 1e-12;
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
const DIAMONDS = [
  [0, 1, [0, 5]], [2, 3, [0, 7]], [4, 7, [10, 11]],
  [5, 15, [5, 9]], [6, 16, [4, 11]], [8, 17, [6, 10]],
  [9, 18, [7, 8]], [10, 11, [3, 4]], [12, 13, [3, 6]],
  [14, 19, [8, 9]],
];
const FACE_DIAMOND = Array(20);
DIAMONDS.forEach(([faceA, faceB, edge], diamond) => {
  FACE_DIAMOND[faceA] = { diamond, half: 0, edge };
  FACE_DIAMOND[faceB] = { diamond, half: 1, edge };
});

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

/** Return exact integer barycentric vertices for one triangle. */
export function latticeTriangle(addressOrFace, digits) {
  const identity = identityFromArgs(addressOrFace, digits);
  let vertices = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  for (const digit of identity.digits) {
    const [v0, v1, v2] = vertices;
    const doubled = vertices.map(vertex => vertex.map(value => 2 * value));
    const midpoint = (a, b) => a.map((value, index) => value + b[index]);
    const m01 = midpoint(v0, v1);
    const m12 = midpoint(v1, v2);
    const m20 = midpoint(v2, v0);
    vertices = [
      [doubled[0], m01, m20],
      [m01, doubled[1], m12],
      [m20, m12, doubled[2]],
      [m01, m12, m20],
    ][digit];
  }
  return vertices;
}

function hilbertXYToIndex(level, inputX, inputY) {
  let x = inputX;
  let y = inputY;
  let index = 0n;
  for (let scale = Math.floor((2 ** level) / 2); scale > 0; scale = Math.floor(scale / 2)) {
    const rx = x & scale ? 1 : 0;
    const ry = y & scale ? 1 : 0;
    index += BigInt(scale) * BigInt(scale) * BigInt((3 * rx) ^ ry);
    if (ry === 0) {
      if (rx === 1) {
        x = scale - 1 - x;
        y = scale - 1 - y;
      }
      [x, y] = [y, x];
    }
  }
  return index;
}

function hilbertIndexToXY(level, inputIndex) {
  const size = 2 ** level;
  let x = 0;
  let y = 0;
  let value = inputIndex;
  for (let scale = 1; scale < size; scale *= 2) {
    const rx = Number(1n & (value >> 1n));
    const ry = Number(1n & (value ^ BigInt(rx)));
    if (ry === 0) {
      if (rx === 1) {
        x = scale - 1 - x;
        y = scale - 1 - y;
      }
      [x, y] = [y, x];
    }
    x += scale * rx;
    y += scale * ry;
    value >>= 2n;
  }
  return [x, y];
}

/** Map a triangle to `{diamond, level, x, y, orientation}`. */
export function rhombusCoords(address) {
  const identity = parseAddress(address);
  const size = 2 ** identity.digits.length;
  const { diamond, half, edge } = FACE_DIAMOND[identity.face];
  const faceVertices = ICO.faces[identity.face];
  const edgeIndexes = edge.map(vertex => faceVertices.indexOf(vertex));
  const points = latticeTriangle(identity).map(barycentric => {
    let x = barycentric[edgeIndexes[0]];
    let y = barycentric[edgeIndexes[1]];
    if (half) [x, y] = [size - y, size - x];
    return [x, y];
  });
  const x = Math.min(...points.map(point => point[0]));
  const y = Math.min(...points.map(point => point[1]));
  const orientation = points.some(point => point[0] === x && point[1] === y) ? 0 : 1;
  return { diamond, level: identity.digits.length, x, y, orientation };
}

/** Return the human-readable ID shared by an exact triangle pair. */
export function rhombusId(address) {
  const { diamond, level, x, y } = rhombusCoords(address);
  return `R${String(diamond).padStart(2, "0")}-${String(level).padStart(2, "0")}-${x}-${y}`;
}

/** Return the Hilbert-linearized BigInt key shared by an exact triangle pair. */
export function rhombus64(address) {
  const { diamond, level, x, y } = rhombusCoords(address);
  const hilbert = hilbertXYToIndex(level, x, y) << BigInt(2 * (MAX_LEVEL - level));
  return (BigInt(diamond) << 59n) | (hilbert << LEVEL_BITS) | BigInt(level);
}

/** Decode a rhombus64 key to `{diamond, level, x, y}`. */
export function decodeRhombus64(address) {
  const value = typeof address === "bigint" ? address : BigInt(address);
  if (value < 0n || value >= (1n << 63n)) throw new RangeError("rhombus64 is outside its 63-bit range");
  const diamond = Number((value >> 59n) & 15n);
  const level = Number(value & 31n);
  if (diamond >= DIAMONDS.length || level > MAX_LEVEL) throw new RangeError("invalid rhombus64 value");
  const hilbert = ((value >> LEVEL_BITS) & PATH_MASK) >> BigInt(2 * (MAX_LEVEL - level));
  const [x, y] = hilbertIndexToXY(level, hilbert);
  return { diamond, level, x, y };
}

function canonicalVertexId(face, level, barycentric) {
  const faceVertices = ICO.faces[face];
  const nonzero = barycentric.map((value, index) => value ? index : -1)
    .filter(index => index >= 0);
  if (nonzero.length === 1) {
    return `HV${String(faceVertices[nonzero[0]]).padStart(2, "0")}-${String(level).padStart(2, "0")}`;
  }
  if (nonzero.length === 2) {
    const [first, second] = nonzero;
    const vertexA = faceVertices[first];
    const vertexB = faceVertices[second];
    const [low, high] = [vertexA, vertexB].sort((a, b) => a - b);
    const highIndex = vertexA === high ? first : second;
    return `HE${String(low).padStart(2, "0")}${String(high).padStart(2, "0")}-${String(level).padStart(2, "0")}-${barycentric[highIndex]}`;
  }
  return `HF${String(face).padStart(2, "0")}-${String(level).padStart(2, "0")}-${barycentric.join("-")}`;
}

/** Return a per-level display-group key with six-triangle face interiors. */
export function hexId(address) {
  const identity = parseAddress(address);
  const centers = latticeTriangle(identity)
    .filter(vertex => (vertex[1] + 2 * vertex[2]) % 3 === 0);
  if (centers.length !== 1) throw new Error("triangle lattice coloring must select one vertex");
  return canonicalVertexId(identity.face, identity.digits.length, centers[0]);
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
    rhombusId: rhombusId(identity),
    rhombusHilbert: rhombus64(identity),
    hexId: hexId(identity),
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
      rhombus_id: rhombusId(identity),
      rhombus_hilbert: rhombus64(identity).toString(),
      hex_id: hexId(identity),
      level: identity.digits.length,
      pole: exported.pole,
    },
    geometry: { type: "Polygon", coordinates: [ring] },
  };
}

/** Return fixed-level cells intersecting a WGS84 bounding box. */
export function bboxCover(minLon, minLat, maxLon, maxLat, level, { mode = "intersects" } = {}) {
  validateCoverLevel(level);
  validateCoverMode(mode);
  const rects = splitBbox(minLon, minLat, maxLon, maxLat);
  return coverCells(
    level,
    ring => rects.some(rect => ringBBoxOverlapsBBox(ring, rect)),
    (ring, triangle) => {
      if (mode === "centroid") {
        const center = triangleCenterLonLat(triangle);
        return rects.some(rect => pointInRect(center, rect));
      }
      return rects.some(rect => cellIntersectsRect(ring, triangle, rect));
    },
  );
}

/** Return fixed-level cells intersecting a GeoJSON Polygon or MultiPolygon. */
export function polyfill(geometry, level, { mode = "intersects" } = {}) {
  validateCoverLevel(level);
  validateCoverMode(mode);
  const polygons = polygonsFromGeoJSON(geometry);
  if (!polygons.length) return [];
  const bboxes = polygons.map(polygonBBox);
  return coverCells(
    level,
    ring => bboxes.some(bbox => ringBBoxOverlapsBBox(ring, bbox)),
    (ring, triangle) => {
      if (mode === "centroid") {
        const center = triangleCenterLonLat(triangle);
        return polygons.some(polygon => pointInPolygonAnyShift(center, polygon));
      }
      return polygons.some(polygon => cellIntersectsPolygon(ring, triangle, polygon));
    },
  );
}

/** Return sorted, coalesced descendant ranges for covered cells. */
export function coverRanges(cells) {
  const ranges = [...cells].map(cell => descendantRange(cell)).sort(compareRanges);
  if (!ranges.length) return [];
  const merged = [ranges[0]];
  for (const [low, high] of ranges.slice(1)) {
    const previous = merged[merged.length - 1];
    if (low <= previous[1] + 1n) previous[1] = high > previous[1] ? high : previous[1];
    else merged.push([low, high]);
  }
  return merged;
}

function coverCells(level, overlapsQuery, accepts) {
  const out = new Set();
  const recurse = (face, digits, triangle) => {
    const ring = cellOpenRing(triangle, digits.length);
    if (!overlapsQuery(ring)) return;
    if (digits.length === level) {
      if (accepts(ring, triangle)) out.add(encode64(face, digits));
      return;
    }
    subdivide(triangle).forEach((child, digit) => recurse(face, [...digits, digit], child));
  };
  ICO.faces.forEach(([i, j, k], face) => recurse(face, [], [ICO.vertices[i], ICO.vertices[j], ICO.vertices[k]]));
  return [...out].sort(compareBigInt);
}

function cellOpenRing(triangle, level) {
  const halvings = Math.max(0, EXPORT_DEPTH - level);
  const points = [
    ...edgePoints(triangle[0], triangle[1], halvings),
    ...edgePoints(triangle[1], triangle[2], halvings),
    ...edgePoints(triangle[2], triangle[0], halvings),
  ];
  return exportRing(points, triangle).ring.map(([lon, lat]) => [Number(lon), Number(lat)]);
}

function validateCoverLevel(level) {
  if (!Number.isInteger(level) || level < 0 || level > MAX_LEVEL) {
    throw new RangeError(`level must be within 0..${MAX_LEVEL}`);
  }
}

function validateCoverMode(mode) {
  if (mode !== "intersects" && mode !== "centroid") {
    throw new RangeError("mode must be 'intersects' or 'centroid'");
  }
}

function splitBbox(minLon, minLat, maxLon, maxLat) {
  const values = [minLon, minLat, maxLon, maxLat].map(Number);
  if (!values.every(Number.isFinite)) throw new TypeError("bbox coordinates must be numbers");
  const [a, b, c, d] = values;
  if (a < -180 || a > 180 || c < -180 || c > 180) {
    throw new RangeError("bbox longitudes must be within [-180, 180]");
  }
  if (b < -90 || b > 90 || d < -90 || d > 90) {
    throw new RangeError("bbox latitudes must be within [-90, 90]");
  }
  if (b > d) throw new RangeError("minLat must be <= maxLat");
  if (a <= c) return [[a, b, c, d]];
  return [[a, b, 180, d], [-180, b, c, d]];
}

function triangleCenterLonLat(triangle) {
  return toLonLat(norm(add(add(triangle[0], triangle[1]), triangle[2])));
}

function lonLatToXYZ(lon, lat) {
  const lambda = lon * Math.PI / 180;
  const phi = lat * Math.PI / 180;
  return [Math.cos(phi) * Math.cos(lambda), Math.cos(phi) * Math.sin(lambda), Math.sin(phi)];
}

function ringBBox(ring) {
  const lons = ring.map(point => point[0]);
  const lats = ring.map(point => point[1]);
  return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
}

function bboxOverlap(a, b) {
  return !(a[2] < b[0] - COVER_EPS || b[2] < a[0] - COVER_EPS ||
    a[3] < b[1] - COVER_EPS || b[3] < a[1] - COVER_EPS);
}

function shiftRing(ring, shift) {
  return shift === 0 ? ring : ring.map(([lon, lat]) => [lon + shift, lat]);
}

function ringBBoxOverlapsBBox(ring, bbox) {
  return [-360, 0, 360].some(shift => bboxOverlap(ringBBox(shiftRing(ring, shift)), bbox));
}

function pointInRect([lon, lat], [minLon, minLat, maxLon, maxLat]) {
  return lon >= minLon - COVER_EPS && lon <= maxLon + COVER_EPS &&
    lat >= minLat - COVER_EPS && lat <= maxLat + COVER_EPS;
}

function rectCorners([minLon, minLat, maxLon, maxLat]) {
  return [[minLon, minLat], [maxLon, minLat], [maxLon, maxLat], [minLon, maxLat]];
}

function rectEdges(rect) {
  const corners = rectCorners(rect);
  return segments(corners);
}

function segments(ring) {
  return ring.map((point, index) => [point, ring[(index + 1) % ring.length]]);
}

function cellIntersectsRect(ring, triangle, rect) {
  const edges = rectEdges(rect);
  for (const shift of [-360, 0, 360]) {
    const shifted = shiftRing(ring, shift);
    if (!bboxOverlap(ringBBox(shifted), rect)) continue;
    if (shifted.some(point => pointInRect(point, rect))) return true;
    if (rectCorners(rect).some(([lon, lat]) => containsPoint(triangle, lonLatToXYZ(lon, lat)))) return true;
    for (const edge of segments(shifted)) {
      if (edges.some(rectEdge => segmentsIntersect(edge[0], edge[1], rectEdge[0], rectEdge[1]))) return true;
    }
  }
  return false;
}

function polygonsFromGeoJSON(geometry) {
  if (!geometry || typeof geometry !== "object") throw new TypeError("geometry must be a GeoJSON object");
  if (geometry.type === "Feature") return polygonsFromGeoJSON(geometry.geometry);
  if (geometry.type === "FeatureCollection") {
    return (geometry.features || []).flatMap(feature => polygonsFromGeoJSON(feature));
  }
  if (geometry.type === "Polygon") return [normalizePolygon(geometry.coordinates)];
  if (geometry.type === "MultiPolygon") return (geometry.coordinates || []).map(normalizePolygon);
  throw new Error("geometry must be Polygon, MultiPolygon, Feature, or FeatureCollection");
}

function normalizePolygon(coords) {
  if (!Array.isArray(coords) || !coords.length) throw new Error("polygon coordinates must contain rings");
  return coords.map(normalizeRing);
}

function normalizeRing(ring) {
  if (!Array.isArray(ring) || ring.length < 4) throw new Error("linear rings must contain at least four positions");
  const points = [];
  let previous = null;
  let offset = 0;
  for (const raw of ring) {
    if (!Array.isArray(raw) || raw.length < 2) throw new Error("positions must be [lon, lat] pairs");
    let lon = Number(raw[0]) + offset;
    const lat = Number(raw[1]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) throw new Error("positions must be finite numbers");
    if (lat < -90 || lat > 90) throw new RangeError("polygon latitudes must be within [-90, 90]");
    if (previous !== null) {
      while (lon - previous > 180) { lon -= 360; offset -= 360; }
      while (lon - previous < -180) { lon += 360; offset += 360; }
    }
    points.push([lon, lat]);
    previous = lon;
  }
  if (samePoint(points[0], points[points.length - 1])) points.pop();
  if (points.length < 3) throw new Error("linear rings must contain at least three unique positions");
  return points;
}

function samePoint(a, b) {
  return Math.abs(a[0] - b[0]) <= COVER_EPS && Math.abs(a[1] - b[1]) <= COVER_EPS;
}

function polygonBBox(polygon) {
  return ringBBox(polygon[0]);
}

function pointInPolygon(point, polygon) {
  if (!pointInRing(point, polygon[0])) return false;
  return !polygon.slice(1).some(hole => pointInRing(point, hole));
}

function pointInPolygonAnyShift(point, polygon) {
  return [-360, 0, 360].some(shift => pointInPolygon([point[0] + shift, point[1]], polygon));
}

function pointInRing([x, y], ring) {
  let inside = false;
  for (let index = 0; index < ring.length; index++) {
    const [x0, y0] = ring[index];
    const [x1, y1] = ring[(index + 1) % ring.length];
    if (pointOnSegment([x, y], [x0, y0], [x1, y1])) return true;
    if ((y0 > y) !== (y1 > y)) {
      const xAtY = (x1 - x0) * (y - y0) / (y1 - y0) + x0;
      if (x <= xAtY + COVER_EPS) inside = !inside;
    }
  }
  return inside;
}

function cellIntersectsPolygon(ring, triangle, polygon) {
  const bbox = polygonBBox(polygon);
  for (const shift of [-360, 0, 360]) {
    const shifted = shiftRing(ring, shift);
    if (!bboxOverlap(ringBBox(shifted), bbox)) continue;
    if (shifted.some(point => pointInPolygon(point, polygon))) return true;
    if (polygon[0].some(([lon, lat]) => containsPoint(triangle, lonLatToXYZ(lon, lat)))) return true;
    const cellEdges = segments(shifted);
    for (const polyRing of polygon) {
      const polyEdges = segments(polyRing);
      for (const edge of cellEdges) {
        if (polyEdges.some(polyEdge => segmentsIntersect(edge[0], edge[1], polyEdge[0], polyEdge[1]))) {
          return true;
        }
      }
    }
  }
  return false;
}

function pointOnSegment([px, py], [ax, ay], [bx, by]) {
  const crossValue = (px - ax) * (by - ay) - (py - ay) * (bx - ax);
  if (Math.abs(crossValue) > COVER_EPS) return false;
  return px >= Math.min(ax, bx) - COVER_EPS && px <= Math.max(ax, bx) + COVER_EPS &&
    py >= Math.min(ay, by) - COVER_EPS && py <= Math.max(ay, by) + COVER_EPS;
}

function orientation(a, b, c) {
  return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
}

function segmentsIntersect(a, b, c, d) {
  const bboxAB = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
  const bboxCD = [Math.min(c[0], d[0]), Math.min(c[1], d[1]), Math.max(c[0], d[0]), Math.max(c[1], d[1])];
  if (!bboxOverlap(bboxAB, bboxCD)) return false;
  const o1 = orientation(a, b, c);
  const o2 = orientation(a, b, d);
  const o3 = orientation(c, d, a);
  const o4 = orientation(c, d, b);
  if (((o1 > COVER_EPS && o2 < -COVER_EPS) || (o1 < -COVER_EPS && o2 > COVER_EPS)) &&
      ((o3 > COVER_EPS && o4 < -COVER_EPS) || (o3 < -COVER_EPS && o4 > COVER_EPS))) {
    return true;
  }
  return pointOnSegment(c, a, b) || pointOnSegment(d, a, b) ||
    pointOnSegment(a, c, d) || pointOnSegment(b, c, d);
}

function compareBigInt(a, b) {
  return a < b ? -1 : (a > b ? 1 : 0);
}

function compareRanges(a, b) {
  return compareBigInt(a[0], b[0]) || compareBigInt(a[1], b[1]);
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
