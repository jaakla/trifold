#!/usr/bin/env python
"""Build the bundled countrycheck datasets from coastal-extended country polygons.

Reads ``osm-vector/countries_coastal.geojson`` (GADM-derived country
MultiPolygons extended with coastal waters), classifies the Trifold grid
against it by hierarchical descent (interior cells emitted at the coarsest
wholly-inside level, border cells at level L), and writes:

  * the main run-length dataset (TFCS) that the Python and JavaScript
    lookup libraries bundle, and
  * the optional border-refinement dataset (TFCR) with exact clipped
    country polygons for every border cell.

Canonical index
---------------
Identical to landcheck: for a level-l cell the canonical level-L index of
its first descendant is ``((face << 2l) | path) << 2(L - l)`` and the cell
covers ``4**(L-l)`` consecutive indices.  The whole Earth is ``20 * 4**L``.

TFCS v1 layout (little-endian)
------------------------------
  magic       4s   b"TFCS"
  version     u8   1
  level       u8   grid level L (10)
  flags       u8   bit0 = border call confidences present
  reserved    u8   0
  n_runs      u32  number of runs
  n_border    u32  total border cells (sum of border run lengths)
  n_countries u16  country table size
  reserved    u16  0
  payload  zlib-deflated stream of:
      country table: per country, three varint-length-prefixed UTF-8
                 strings: code (gid_0), iso2 ('' if none), name
      runs:      per run, varint(gap from previous run end), then
                 varint((length << 1) | border); non-border runs are
                 followed by varint(country_id)
      calls:     per border cell in run order, varint(call);
                 0 = no country (water), else country_id + 1
      shares:    if flags bit0, ceil(n_border/2) bytes, one 4-bit value
                 per border cell; the call's area share = (q + 0.5) / 16

Gaps between runs are international waters (no country).  A non-border
run is wholly inside one country; a border run holds mixed cells whose
best call and its area share are stored per cell.

TFCR v1 layout (little-endian)
------------------------------
  magic    4s   b"TFCR"
  version  u8   1
  level    u8   grid level L (10)
  flags    u8   0
  reserved u8   0
  n_cells  u32
  payload  zlib-deflated stream, cells in ascending canonical index order:
      varint(index - previous index)        (first: index - 0)
      varint(n_zones)
      per zone (sorted by area, largest first):
          varint(country_id)
          varint(n_rings)   0 = the whole cell is this country
          per ring: varint(n_points), then n_points pairs of
                    zigzag-varint deltas in the cell-local u16 grid
                    (cell bbox of the unwrapped 3-vertex triangle)

Zone rings combine by even-odd rule; the first zone containing the point
wins, no zone means no country.

Usage:
  python countrycheck/build.py [--countries osm-vector/countries_coastal.geojson]
        [--out countrycheck/data/countries_L10.tfcs]
        [--refine-out countrycheck/data/borders_L10.tfcr] [--no-refine]
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from _fastloc import index_to_lonlat_ring  # noqa: E402
from trifold.core import (icosahedron, subdivide, densified_ring_xyz,  # noqa: E402
                          unwrap_ring_lonlat, xyz_to_lonlat,
                          contains_point, NORTH, SOUTH)

MAGIC = b"TFCS"
MAGIC_REFINE = b"TFCR"
VERSION = 1
FULL = 0.999999      # area ratio considered "whole cell"
EMPTY = 1.0 - FULL   # area ratio considered "nothing"
MAX_PRED_UNION = 64  # same-country union containment attempted below this
CLIP_MAX_VERTS = 2000  # split pieces for the clipping tree


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def zigzag(value: int) -> int:
    return (value << 1) ^ (value >> 63)


# ------------------------------------------------------------------ source
def load_countries(path: Path):
    """Country table (sorted by code) and flat (polygon, country_id) pieces."""
    from shapely.geometry import shape

    print(f"reading {path} ...", flush=True)
    with open(path) as f:
        collection = json.load(f)
    features = sorted(collection["features"],
                      key=lambda f: f["properties"]["gid_0"])
    countries = []
    pieces = []     # shapely Polygons
    piece_cids = []
    for cid, feature in enumerate(features):
        props = feature["properties"]
        countries.append({
            "code": props["gid_0"],
            "iso2": props.get("iso2") or "",
            "name": props.get("name_en") or props.get("name_0") or "",
        })
        geom = shape(feature["geometry"])
        polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        for poly in polys:
            if not poly.is_valid:
                poly = poly.buffer(0)
            for p in (poly.geoms if poly.geom_type == "MultiPolygon" else [poly]):
                if not p.is_empty:
                    pieces.append(p)
                    piece_cids.append(cid)
    if len(countries) > 0xFFFF:
        raise ValueError("country table exceeds u16")
    print(f"  {len(countries)} countries, {len(pieces)} polygon pieces")
    return countries, pieces, piece_cids


def split_for_clipping(pieces, piece_cids, max_verts=CLIP_MAX_VERTS):
    """Bbox-halve large pieces so border-cell overlays stay local and cheap."""
    from shapely.geometry import box

    def n_verts(poly):
        return len(poly.exterior.coords) + sum(len(r.coords) for r in poly.interiors)

    out_polys, out_cids = [], []
    for poly, cid in zip(pieces, piece_cids):
        stack = [poly]
        while stack:
            p = stack.pop()
            if p.is_empty:
                continue
            if p.geom_type != "Polygon":
                stack.extend(g for g in p.geoms if g.geom_type == "Polygon")
                continue
            if n_verts(p) <= max_verts:
                out_polys.append(p)
                out_cids.append(cid)
                continue
            minx, miny, maxx, maxy = p.bounds
            if maxx - minx >= maxy - miny:
                mid = (minx + maxx) / 2.0
                halves = (box(minx, miny, mid, maxy), box(mid, miny, maxx, maxy))
            else:
                mid = (miny + maxy) / 2.0
                halves = (box(minx, miny, maxx, mid), box(minx, mid, maxx, maxy))
            for h in halves:
                stack.append(p.intersection(h))
    print(f"  clip tree: {len(out_polys)} pieces (max {max_verts} vertices each)")
    return out_polys, out_cids


# -------------------------------------------------------------- classifier
class CountryClassifier:
    """'none' / ('interior', cid) / 'mixed' classification of spherical
    triangles against country polygons (modeled on trifold.classify)."""

    def __init__(self, pieces, piece_cids, polar_lat=86.0):
        from shapely.strtree import STRtree
        from shapely import affinity

        self.polar_lat = polar_lat
        ext, ext_cids = [], []
        for dx in (-360.0, 0.0, 360.0):
            for p, cid in zip(pieces, piece_cids):
                ext.append(affinity.translate(p, xoff=dx) if dx else p)
                ext_cids.append(cid)
        self.ext_geoms = ext
        self.ext_cids = ext_cids
        self.ext_tree = STRtree(ext)
        self.ext_prep = {}

        import pyproj
        self.aeqd = {}
        for pole, lat0 in (("N", 90), ("S", -90)):
            tr = pyproj.Transformer.from_crs(
                "EPSG:4326", f"+proj=aeqd +lat_0={lat0} +lon_0=0 +R=6371008.8",
                always_xy=True)
            sel, sel_cids = [], []
            for p, cid in zip(pieces, piece_cids):
                miny, maxy = p.bounds[1], p.bounds[3]
                if (pole == "N" and maxy > 55) or (pole == "S" and miny < -55):
                    q = self._project_poly(p, tr)
                    if q is not None:
                        sel.append(q)
                        sel_cids.append(cid)
            self.aeqd[pole] = {"tr": tr, "geoms": sel, "cids": sel_cids,
                               "tree": STRtree(sel) if sel else None, "prep": {}}

    @staticmethod
    def _project_poly(poly, tr):
        from shapely.geometry import Polygon
        try:
            ext = [tr.transform(x, y) for x, y in poly.exterior.coords]
            ints = [[tr.transform(x, y) for x, y in r.coords]
                    for r in poly.interiors]
            q = Polygon(ext, ints)
            return q if q.is_valid else q.buffer(0)
        except Exception:
            return None

    def _prep(self, frame, idx):
        cache = self.ext_prep if frame == "ext" else self.aeqd[frame]["prep"]
        if idx not in cache:
            from shapely.prepared import prep
            geoms = self.ext_geoms if frame == "ext" else self.aeqd[frame]["geoms"]
            cache[idx] = prep(geoms[idx])
        return cache[idx]

    def classify(self, tri):
        """('none', None) | ('interior', cid) | ('mixed', None)."""
        from shapely.geometry import Polygon

        pts = densified_ring_xyz(tri)
        has_n = contains_point(tri, NORTH)
        has_s = contains_point(tri, SOUTH)
        lats = [xyz_to_lonlat(p)[1] for p in pts]
        if has_n or has_s or max(abs(l) for l in lats) >= self.polar_lat:
            pole = "N" if (max(lats) >= -min(lats)) else "S"
            if has_n:
                pole = "N"
            if has_s:
                pole = "S"
            d = self.aeqd[pole]
            if d["tree"] is None:
                return "none", None
            tr = d["tr"]
            ring = [tr.transform(*xyz_to_lonlat(p)) for p in pts]
            return self._classify_frame(Polygon(ring), pole,
                                        d["tree"], d["geoms"], d["cids"])

        ring = unwrap_ring_lonlat(pts)
        return self._classify_frame(Polygon(ring), "ext", self.ext_tree,
                                    self.ext_geoms, self.ext_cids)

    def _classify_frame(self, poly, frame, tree, geoms, cids):
        if not poly.is_valid:
            poly = poly.buffer(0)
        hits = []
        for i in tree.query(poly):
            i = int(i)
            pg = self._prep(frame, i)
            if pg.contains(poly):
                return "interior", cids[i]
            if pg.intersects(poly):
                hits.append(i)
        if not hits:
            return "none", None
        hit_cids = {cids[i] for i in hits}
        if len(hit_cids) == 1 and len(hits) <= MAX_PRED_UNION:
            # cell may straddle pieces of the same country
            from shapely.ops import unary_union
            from shapely.prepared import prep
            union = unary_union([geoms[i] for i in hits])
            if prep(union).contains(poly):
                return "interior", hit_cids.pop()
        return "mixed", None

    def polar_areas(self, tri, index, level):
        """Per-country area shares of a polar cell in the AEQD frame."""
        from shapely.geometry import Polygon

        pts = densified_ring_xyz(tri)
        lats = [xyz_to_lonlat(p)[1] for p in pts]
        pole = "S" if (-min(lats) > max(lats) or contains_point(tri, SOUTH)) else "N"
        d = self.aeqd[pole]
        tr = d["tr"]
        poly = Polygon([tr.transform(*xyz_to_lonlat(p)) for p in pts])
        if not poly.is_valid:
            poly = poly.buffer(0)
        areas = {}
        if d["tree"] is not None:
            for i in d["tree"].query(poly):
                i = int(i)
                inter = poly.intersection(d["geoms"][i])
                if not inter.is_empty and inter.area > 0.0:
                    cid = d["cids"][i]
                    areas[cid] = areas.get(cid, 0.0) + inter.area
        return poly.area, areas


# ------------------------------------------------------------ border cells
def encode_zone_rings(geoms, bbox):
    """Quantize one zone's rings to the cell-local u16 grid; None if degenerate."""
    minx, miny, maxx, maxy = bbox
    sx = 65535.0 / (maxx - minx)
    sy = 65535.0 / (maxy - miny)
    rings = []
    for geom in geoms:
        polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        for poly in polys:
            if poly.geom_type != "Polygon":
                continue
            for ring in (poly.exterior, *poly.interiors):
                pts = []
                for x, y in ring.coords[:-1]:
                    qx = min(65535, max(0, round((x - minx) * sx)))
                    qy = min(65535, max(0, round((y - miny) * sy)))
                    if not pts or pts[-1] != (qx, qy):
                        pts.append((qx, qy))
                if len(pts) >= 3:
                    rings.append(pts)
    if not rings:
        return None
    body = bytearray()
    body += varint(len(rings))
    for pts in rings:
        body += varint(len(pts))
        px = py = 0
        for qx, qy in pts:
            body += varint(zigzag(qx - px))
            body += varint(zigzag(qy - py))
            px, py = qx, qy
    return bytes(body)


class BorderClipper:
    """Exact per-country clipping of level-L cells (plate-carree frame,
    consistent with the lookup libraries' cell-local quantization)."""

    def __init__(self, pieces, piece_cids):
        from shapely.strtree import STRtree
        from shapely import affinity

        clip_polys, clip_cids = split_for_clipping(pieces, piece_cids)
        geoms, cids = [], []
        for dx in (0.0, 360.0):  # rings are unwrapped east: lons in [-180, 360]
            for p, cid in zip(clip_polys, clip_cids):
                geoms.append(affinity.translate(p, xoff=dx) if dx else p)
                cids.append(cid)
        self.geoms = geoms
        self.cids = cids
        self.tree = STRtree(geoms)

    def clip(self, index, level):
        """(cell_area, {cid: (area, [clipped geoms])}, bbox) of one cell."""
        from shapely.geometry import Polygon

        ring = index_to_lonlat_ring(index, level)
        tri = Polygon(ring)
        zones = {}
        for i in self.tree.query(tri):
            i = int(i)
            inter = tri.intersection(self.geoms[i])
            if not inter.is_empty and inter.area > 0.0:
                cid = self.cids[i]
                if cid in zones:
                    zones[cid][0] += inter.area
                    zones[cid][1].append(inter)
                else:
                    zones[cid] = [inter.area, [inter]]
        return tri.area, zones, tri.bounds


# ----------------------------------------------------------------- builder
def build_cells(classifier, clipper, level):
    """Hierarchical descent.  Returns (cells, refine_records) where cells is
    a list of (base, span, kind, payload) sorted by base index:
      kind 'i' -> payload = cid
      kind 'b' -> payload = (call, q)        call: 0 = none, else cid + 1
    and refine_records maps border base index -> encoded TFCR zone bytes."""
    verts, faces = icosahedron()
    cells = []
    refine = {}
    stats = {"classify": 0, "clip": 0, "polar_border": 0}
    t0 = time.time()

    def emit_border(index, tri):
        stats["clip"] += 1
        ring = index_to_lonlat_ring(index, level)
        if max(lat for _, lat in ring) > 89.9 or min(lat for _, lat in ring) < -89.9:
            # pole-adjacent: areas from the AEQD frame, no lookup rings
            stats["polar_border"] += 1
            cell_area, areas = classifier.polar_areas(tri, index, level)
            zones = {cid: (a, None) for cid, a in areas.items()}
            bbox = None
        else:
            cell_area, zones, bbox = clipper.clip(index, level)

        total = sum(a for a, _ in zones.values())
        if cell_area <= 0.0 or total <= EMPTY * cell_area:
            return  # nothing of any country in the cell: open water gap
        best_cid, (best_area, _) = max(zones.items(), key=lambda kv: kv[1][0])
        if best_area >= FULL * cell_area:
            cells.append((index, 1, "i", best_cid))
            return

        shares = [(max(0.0, 1.0 - total / cell_area), 0)]
        shares += [(a / cell_area, cid + 1) for cid, (a, _) in zones.items()]
        share, call = max(shares, key=lambda t: (t[0], t[1] > 0))
        q = min(15, int(share * 16.0))
        cells.append((index, 1, "b", (call, q)))

        if bbox is not None:
            record = bytearray()
            encoded = []
            for cid, (area, geoms) in sorted(zones.items(),
                                             key=lambda kv: -kv[1][0]):
                if area >= FULL * cell_area:
                    encoded.append(varint(cid) + varint(0))  # whole cell
                    break
                rings = encode_zone_rings(geoms, bbox)
                if rings is not None:
                    encoded.append(varint(cid) + rings)
            record += varint(len(encoded))
            for z in encoded:
                record += z
            refine[index] = bytes(record)

    def recurse(tri, face, path, depth):
        if depth == level:
            emit_border((face << (2 * level)) | path, tri)
            return
        stats["classify"] += 1
        state, cid = classifier.classify(tri)
        base = ((face << (2 * depth)) | path) << (2 * (level - depth))
        if state == "none":
            return
        if state == "interior":
            cells.append((base, 4 ** (level - depth), "i", cid))
            return
        for digit, child in enumerate(subdivide(tri)):
            recurse(child, face, (path << 2) | digit, depth + 1)

    for f, idx in enumerate(faces):
        recurse(tuple(verts[i] for i in idx), f, 0, 0)
        print(f"  face {f + 1}/20: {len(cells)} cells, "
              f"{stats['clip']} border clips, {time.time() - t0:.0f}s",
              flush=True)
    if stats["polar_border"]:
        print(f"  note: {stats['polar_border']} polar border cells "
              f"(no refinement rings)")
    return cells, refine


def build_runs(cells):
    """Merge adjacent same-state cells: [start, length, border, cid_or_None]
    plus flat per-border-cell (call, q) lists in index order."""
    runs = []
    calls, qs = [], []
    for base, span, kind, payload in cells:
        border = kind == "b"
        cid = None if border else payload
        if border:
            calls.append(payload[0])
            qs.append(payload[1])
        if (runs and runs[-1][2] == border and runs[-1][3] == cid
                and runs[-1][0] + runs[-1][1] == base):
            runs[-1][1] += span
        else:
            runs.append([base, span, border, cid])
    return runs, calls, qs


def write_tfcs(out_path: Path, level: int, countries, runs, calls, qs):
    body = bytearray()
    for c in countries:
        for key in ("code", "iso2", "name"):
            raw = c[key].encode("utf-8")
            body += varint(len(raw))
            body += raw
    prev_end = 0
    for start, length, border, cid in runs:
        body += varint(start - prev_end)
        body += varint((length << 1) | int(border))
        if not border:
            body += varint(cid)
        prev_end = start + length
    for call in calls:
        body += varint(call)
    nibbles = bytearray(math.ceil(len(qs) / 2))
    for pos, q in enumerate(qs):
        if pos & 1:
            nibbles[pos >> 1] |= q << 4
        else:
            nibbles[pos >> 1] = q
    body += nibbles

    payload = zlib.compress(bytes(body), 9)
    header = struct.pack("<4sBBBBIIHH", MAGIC, VERSION, level, 1, 0,
                         len(runs), len(calls), len(countries), 0)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(header + payload)
    print(f"wrote {out_path}: {len(countries)} countries, {len(runs)} runs, "
          f"{len(calls)} border cells, "
          f"{len(body)} B raw -> {len(header) + len(payload)} B file")


def write_tfcr(out_path: Path, level: int, refine):
    body = bytearray()
    prev = 0
    for index in sorted(refine):
        body += varint(index - prev)
        body += refine[index]
        prev = index
    payload = zlib.compress(bytes(body), 9)
    header = struct.pack("<4sBBBBI", MAGIC_REFINE, VERSION, level, 0, 0,
                         len(refine))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(header + payload)
    print(f"wrote {out_path}: {len(refine)} border cells, "
          f"{len(body)} B raw -> {len(header) + len(payload)} B file")


def main():
    repo = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--countries",
                    default=repo / "osm-vector/countries_coastal.geojson",
                    type=Path)
    ap.add_argument("--out", default=repo / "countrycheck/data/countries_L10.tfcs",
                    type=Path)
    ap.add_argument("--refine-out",
                    default=repo / "countrycheck/data/borders_L10.tfcr",
                    type=Path)
    ap.add_argument("--no-refine", action="store_true",
                    help="skip the TFCR border-refinement dataset")
    ap.add_argument("--level", type=int, default=10)
    args = ap.parse_args()

    countries, pieces, piece_cids = load_countries(args.countries)
    classifier = CountryClassifier(pieces, piece_cids)
    clipper = BorderClipper(pieces, piece_cids)

    print(f"descending to level {args.level} ...", flush=True)
    cells, refine = build_cells(classifier, clipper, args.level)
    n_interior = sum(s for _, s, k, _ in cells if k == "i")
    n_border = sum(1 for _, _, k, _ in cells if k == "b")
    print(f"  {len(cells)} cells: {n_interior} interior level-{args.level} "
          f"equivalents, {n_border} border")

    runs, calls, qs = build_runs(cells)
    print(f"  {len(runs)} runs after merging")
    write_tfcs(args.out, args.level, countries, runs, calls, qs)
    if not args.no_refine:
        write_tfcr(args.refine_out, args.level, refine)


if __name__ == "__main__":
    main()
