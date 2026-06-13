#!/usr/bin/env python
"""Regenerate the shared cross-language test fixtures (points.json,
refined_points.json).

Records the Python library's answers for a deterministic point sample;
the Python and JS test suites both assert against it, so any divergence
between the two implementations or a dataset change shows up as a diff.
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
from countrycheck import CountryCheck  # noqa: E402

NAMED = [
    ("Tallinn", 24.7536, 59.4370),
    ("London", -0.1276, 51.5072),
    ("Tokyo", 139.6917, 35.6895),
    ("Sao Paulo", -46.6333, -23.5505),
    ("Mid-Atlantic", -30.0, 30.0),
    ("South Pacific", -150.0, -30.0),
    ("Sahara", 10.0, 25.0),
    ("Himalaya", 86.92, 27.99),
    ("North Pole", 0.0, 89.99),
    ("South Pole vicinity", 0.0, -89.99),
    ("Antimeridian east", 179.95, -16.6),
    ("Antimeridian west", -179.95, 65.5),
    ("Dover strait", 1.4, 51.0),
    ("Gibraltar", -5.35, 36.14),
    ("Maldives", 73.5, 4.2),
    ("Lake Victoria", 33.0, -1.0),
    ("Kosovo", 20.9, 42.6),
    ("Caspian Sea", 51.0, 41.5),
    ("Baltic Estonian waters", 24.3, 59.6),
    ("US-Canada 49th", -110.0, 49.001),
]


def main():
    cc = CountryCheck()
    rng = random.Random(20260612)
    points = [{"name": n, "lon": lon, "lat": lat} for n, lon, lat in NAMED]
    for i in range(2000):
        points.append({"name": f"rand{i}",
                       "lon": round(rng.uniform(-180.0, 180.0), 6),
                       "lat": round(rng.uniform(-90.0, 90.0), 6)})
    for p in points:
        r = cc.check(p["lon"], p["lat"])
        p["country"] = r.country
        p["iso2"] = r.iso2
        p["kind"] = r.kind
        p["confidence"] = round(r.confidence, 6)
        p["share"] = None if r.share is None else round(r.share, 6)
        p["cell"] = r.cell
    out = Path(__file__).parent / "points.json"
    out.write_text(json.dumps(points, indent=1))
    kinds = {}
    for p in points:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    print(f"wrote {out}: {len(points)} points, kinds={kinds}")

    # refined fixture: deterministic points inside border cells, answers
    # with the border refinement loaded (skipped if the TFCR is not built)
    tfcr = Path(__file__).resolve().parent.parent / "data" / "borders_L10.tfcr"
    if not tfcr.exists():
        print(f"no {tfcr.name}; skipping refined fixture")
        return
    from _fastloc import index_to_lonlat_ring
    cc = CountryCheck(refine_path=tfcr)
    border = [i for s, e, b in zip(cc._starts, cc._ends, cc._border)
              if b for i in range(s, e)]
    rng = random.Random(424242)
    refined_points = []
    for _ in range(500):
        idx = border[rng.randrange(len(border))]
        ring = index_to_lonlat_ring(idx, 10)
        a, b = rng.random(), rng.random()
        if a + b > 1.0:
            a, b = 1.0 - a, 1.0 - b
        lon = ring[0][0] + a * (ring[1][0] - ring[0][0]) + b * (ring[2][0] - ring[0][0])
        lat = ring[0][1] + a * (ring[1][1] - ring[0][1]) + b * (ring[2][1] - ring[0][1])
        if lon > 180.0:
            lon -= 360.0
        r = cc.check(lon, lat)
        refined_points.append({
            "lon": round(lon, 8), "lat": round(lat, 8),
            "country": r.country, "kind": r.kind, "refined": r.refined,
            "confidence": round(r.confidence, 6), "cell": r.cell,
        })
    out2 = Path(__file__).parent / "refined_points.json"
    out2.write_text(json.dumps(refined_points, indent=1))
    n_ref = sum(p["refined"] for p in refined_points)
    print(f"wrote {out2}: {len(refined_points)} border points, {n_ref} refined")


if __name__ == "__main__":
    main()
