#!/usr/bin/env python
"""Generate the tiny cross-language TFDG fixture committed beside the tests."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "settlementcheck"))
sys.path.insert(0, str(ROOT / "settlementcheck" / "python"))
from build import NODATA_CODE, RunWriter, VALID_CODES, write_dataset  # noqa: E402
from _fastloc import index_to_triangle  # noqa: E402

LEVEL = 2
RASTER_SHA = "7dda69a104a5eaef6b5ac6038fcc00ca00122218c759ab34e95d338721d64a18"


def centre(index):
    vertices = index_to_triangle(index, LEVEL)
    x = sum(value[0] for value in vertices)
    y = sum(value[1] for value in vertices)
    z = sum(value[2] for value in vertices)
    norm = math.sqrt(x * x + y * y + z * z)
    return math.degrees(math.atan2(y, x)), math.degrees(math.asin(z / norm))


writer = RunWriter(LEVEL)
codes = (*VALID_CODES, NODATA_CODE)
points = []
for index in range(20 * 4 ** LEVEL):
    code = codes[index % len(codes)]
    mixed = index == 23
    writer.add(index, 1, code, mixed=mixed, share=0.6,
               water_mix=mixed, nodata_mix=False)
    if index < len(codes) or mixed:
        lon, lat = centre(index)
        points.append({"index": index, "lon": lon, "lat": lat,
                       "code": None if code == NODATA_CODE else code,
                       "mixed": mixed})

write_dataset(HERE / "fixture_L2.tfdg", writer, RASTER_SHA)
(HERE / "points.json").write_text(json.dumps(points, indent=2) + "\n")
