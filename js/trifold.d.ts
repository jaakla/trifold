export type CellIdentity = { face: number; digits: number[] };
export type AddressLike = bigint | number | string | CellIdentity | [number, number[]];
export type PolygonFeature = {
  type: "Feature";
  properties: Record<string, string | number | boolean>;
  geometry: { type: "Polygon"; coordinates: number[][][] };
};
export type PolygonFeatureCollection = {
  type: "FeatureCollection";
  features: PolygonFeature[];
};

export const EARTH_RADIUS_KM: number;
export const MAX_LEVEL: number;
export const EXPORT_DEPTH: number;

export function icosahedron(): { vertices: number[][]; faces: number[][] };
export function subdivide(triangle: number[][]): number[][][];
export function containsPoint(triangle: number[][], point: number[]): boolean;
export function encode64(face: number, digits: number[]): bigint;
export function decode64(address: bigint | number | string): CellIdentity;
export function parseAddress(address: AddressLike): CellIdentity;
export function toCompact(address: AddressLike): string;
export function toCompact(face: number, digits: number[]): string;
export function fromCompact(address: string): bigint;
export function toPath(address: AddressLike): string;
export function toPath(face: number, digits: number[]): string;
export function fromPath(address: string): bigint;
export function parent64(address: bigint | number | string): bigint;
export function children64(address: bigint | number | string): bigint[];
export function isAncestor(ancestor: bigint | number | string, descendant: bigint | number | string): boolean;
export function descendantRange(address: bigint | number | string): [bigint, bigint];
export function bboxCover(
  minLon: number,
  minLat: number,
  maxLon: number,
  maxLat: number,
  level: number,
  options?: { mode?: "intersects" | "centroid" },
): bigint[];
export function polyfill(
  geometry: Record<string, unknown>,
  level: number,
  options?: { mode?: "intersects" | "centroid" },
): bigint[];
export function coverRanges(cells: Iterable<bigint | number | string>): [bigint, bigint][];
export function hilbertRanges(cells: Iterable<bigint | number | string>): [bigint, bigint][];
export function latticeTriangle(address: AddressLike): number[][];
export function latticeTriangle(face: number, digits: number[]): number[][];
export function rhombusCoords(address: AddressLike): {
  diamond: number; level: number; x: number; y: number; orientation: number;
};
export function rhombusId(address: AddressLike): string;
export function rhombus64(address: AddressLike): bigint;
export function decodeRhombus64(address: bigint | number | string): {
  diamond: number; level: number; x: number; y: number;
};
export function hexId(address: AddressLike): string;
export function cellTriangle(address: AddressLike): number[][];
export function cellTriangle(face: number, digits: number[]): number[][];
export function locate(lon: number, lat: number, level: number): CellIdentity;
export function locateAddress(lon: number, lat: number, level: number): bigint;
export function edgeKm(triangle: number[][]): number;
export function areaKm2(triangle: number[][]): number;
export function cellRing(address: AddressLike, options?: { depth?: number; precision?: number }): number[][];
export function cellMetrics(address: AddressLike): {
  id: string; path: string; addr64: bigint; face: number; level: number;
  rhombusId: string; rhombusHilbert: bigint; hexId: string;
  edgeKm: number; areaKm2: number;
};
export function cellFeature(address: AddressLike, options?: { precision?: number }): PolygonFeature;
export function levelFeatureCollection(
  level: number,
  options?: { face?: number | null; maxLevel?: number },
): PolygonFeatureCollection;
