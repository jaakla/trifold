"""trifold.classify — exact land/sea classification of cells."""
import numpy as np
from shapely.geometry import Polygon
from shapely.prepared import prep
from shapely.strtree import STRtree
from shapely import affinity
from .core import (densified_ring_xyz, unwrap_ring_lonlat,
                   xyz_to_lonlat, contains_point, NORTH, SOUTH)

# ---------------------------------------------------------------- classifier
class LandClassifier:
    """
    Exact 'sea' / 'interior' / 'mixed' classification of spherical
    triangles against a set of land polygons (lon/lat, already split at
    the antimeridian, as Natural Earth is).
    """
    def __init__(self, land_gdf, polar_lat=86.0):
        import pyproj
        pieces = []
        for geom in land_gdf.geometry:
            if geom.geom_type == 'Polygon':
                pieces.append(geom)
            else:
                pieces.extend(geom.geoms)
        self.pieces = pieces
        self.polar_lat = polar_lat

        # Frame A: standard + translated copies for antimeridian work.
        ext = []
        self.ext_src = []
        for dx in (-360.0, 0.0, 360.0):
            for p in pieces:
                ext.append(affinity.translate(p, xoff=dx) if dx else p)
                self.ext_src.append(p)
        self.ext_geoms = ext
        self.ext_tree = STRtree(ext)
        self.ext_prep = {}  # lazy prepared geoms

        # Frame B: polar AEQD (north and south), pieces pre-projected once.
        self.aeqd = {}
        for pole, lat0 in (('N', 90), ('S', -90)):
            tr = pyproj.Transformer.from_crs(
                'EPSG:4326', f'+proj=aeqd +lat_0={lat0} +lon_0=0 +R=6371008.8',
                always_xy=True)
            sel = []
            for p in pieces:
                miny, maxy = p.bounds[1], p.bounds[3]
                if (pole == 'N' and maxy > 55) or (pole == 'S' and miny < -55):
                    q = self._project_poly(p, tr)
                    if q is not None:
                        sel.append(q)
            self.aeqd[pole] = {
                'tr': tr,
                'tree': STRtree(sel) if sel else None,
                'geoms': sel,
                'prep': {},
            }

    @staticmethod
    def _project_poly(poly, tr):
        try:
            ext = [tr.transform(x, y) for x, y in poly.exterior.coords]
            ints = [[tr.transform(x, y) for x, y in r.coords]
                    for r in poly.interiors]
            q = Polygon(ext, ints)
            return q if q.is_valid else q.buffer(0)
        except Exception:
            return None

    def _prep_ext(self, idx):
        if idx not in self.ext_prep:
            self.ext_prep[idx] = prep(self.ext_geoms[idx])
        return self.ext_prep[idx]

    def _prep_aeqd(self, pole, idx):
        d = self.aeqd[pole]
        if idx not in d['prep']:
            d['prep'][idx] = prep(d['geoms'][idx])
        return d['prep'][idx]

    def classify(self, tri):
        """Returns ('sea'|'interior'|'mixed', meta dict)."""
        pts = densified_ring_xyz(tri)
        has_n = contains_point(tri, NORTH)
        has_s = contains_point(tri, SOUTH)
        lats = [xyz_to_lonlat(p)[1] for p in pts]
        meta = {'pole': 'N' if has_n else ('S' if has_s else ''),
                'pts': pts}

        if has_n or has_s or max(abs(l) for l in lats) >= self.polar_lat:
            pole = 'N' if (has_n or max(lats) > 0 and not has_s) else 'S'
            # safer: choose by which pole is closer
            pole = 'N' if (max(lats) >= -min(lats)) else 'S'
            if has_n: pole = 'N'
            if has_s: pole = 'S'
            return self._classify_aeqd(pts, pole, meta)

        ring = unwrap_ring_lonlat(pts)
        meta['ring'] = ring
        lons = [p[0] for p in ring]
        meta['xam'] = max(lons) > 180 or min(lons) < -180
        return self._classify_ext(ring, meta)

    def _classify_ext(self, ring, meta):
        poly = Polygon(ring)
        if not poly.is_valid:
            poly = poly.buffer(0)
        cand = self.ext_tree.query(poly)
        hit = False
        for i in cand:
            pg = self._prep_ext(int(i))
            if pg.contains(poly):
                return 'interior', meta
            if not hit and pg.intersects(poly):
                hit = True
        # containment may still hold across one piece queried later; the
        # loop above already checked contains for every candidate.
        return ('mixed' if hit else 'sea'), meta

    def _classify_aeqd(self, pts_xyz, pole, meta):
        d = self.aeqd[pole]
        meta['aeqd'] = pole
        tr = d['tr']
        ring = [tr.transform(*xyz_to_lonlat(p)) for p in pts_xyz]
        poly = Polygon(ring)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if d['tree'] is None:
            return 'sea', meta
        cand = d['tree'].query(poly)
        hit = False
        for i in cand:
            pg = self._prep_aeqd(pole, int(i))
            if pg.contains(poly):
                return 'interior', meta
            if not hit and pg.intersects(poly):
                hit = True
        return ('mixed' if hit else 'sea'), meta


