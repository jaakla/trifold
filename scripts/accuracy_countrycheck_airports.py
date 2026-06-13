#!/usr/bin/env python3
"""Accuracy of Trifold countrycheck against a real-world point set.

Ground truth is the OurAirports dump (``osm-vector/airports.geojson``); every
feature carries an ISO 3166-1 alpha-2 ``iso_country``. For each airport we ask
countrycheck which country the point falls in, with and without the optional
border refinement loaded, and compare the answer to ``iso_country``.

This is an *independent* check: countrycheck is built from GADM-derived country
polygons (extended with coastal waters), while the airport country codes come
from an unrelated source. Residual disagreement is therefore a mix of genuine
source/boundary differences (disputed territories, dependencies coded to a
parent state, airports just offshore of a polygon) and countrycheck's own
border-cell approximation. The refinement only touches border cells, so the
headline it moves is the border-cell agreement.

Run from the repository root:

    .venv/bin/python scripts/accuracy_countrycheck_airports.py
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "countrycheck" / "python"))

from countrycheck import CountryCheck  # noqa: E402

# countrycheck carries the seven X-coded GADM territories with an empty iso2.
# Map the ones an alpha-2 ground truth can express back to the code the airport
# file uses, so they are scored fairly rather than as automatic misses.
X_ALPHA2 = {"XKO": "XK"}  # Kosovo (OurAirports uses the user-assigned XK)


def predicted_alpha2(result) -> str | None:
    """Normalize a countrycheck answer to an alpha-2 code for comparison."""
    if result.country is None:
        return None
    if result.iso2:
        return result.iso2
    return X_ALPHA2.get(result.country)  # may stay None for XCA/XNC/...


def load_airports(path: Path) -> list[tuple[float, float, str]]:
    data = json.loads(path.read_text())
    points = []
    for feature in data["features"]:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        lon, lat = geometry["coordinates"][:2]
        iso = (feature["properties"].get("iso_country") or "").strip().upper()
        if not iso:
            continue
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            continue
        points.append((float(lon), float(lat), iso))
    return points


def evaluate(checker: CountryCheck, points) -> dict:
    agree = 0
    by_kind = Counter()
    by_kind_agree = Counter()
    none_count = 0
    per_point = []  # (kind, agreed) keyed by airport order, for cross-tabs
    disagreements = []
    for lon, lat, truth in points:
        result = checker.check(lon, lat)
        pred = predicted_alpha2(result)
        agreed = pred == truth
        agree += agreed
        by_kind[result.kind] += 1
        by_kind_agree[result.kind] += agreed
        if result.kind == "none":
            none_count += 1
        per_point.append((result.kind, agreed, pred))
        if not agreed and len(disagreements) < 40:
            disagreements.append(
                {"lon": round(lon, 4), "lat": round(lat, 4),
                 "truth": truth, "predicted": pred,
                 "kind": result.kind, "country": result.country})
    return {
        "agree": agree,
        "by_kind": dict(by_kind),
        "by_kind_agree": dict(by_kind_agree),
        "none_count": none_count,
        "per_point": per_point,
        "disagreements": disagreements,
    }


def pct(n: int, d: int) -> float:
    return 100.0 * n / d if d else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--airports", type=Path,
                        default=REPO / "osm-vector" / "airports.geojson")
    parser.add_argument("--refine", type=Path,
                        default=REPO / "countrycheck" / "data" / "borders_L10.tfcr")
    parser.add_argument("--output", type=Path,
                        default=Path("/private/tmp/trifold-countrycheck-benchmark/"
                                     "airports_accuracy.json"))
    args = parser.parse_args()

    points = load_airports(args.airports)
    total = len(points)
    print(f"airports with a usable point and iso_country: {total:,}")

    base = CountryCheck()
    base_eval = evaluate(base, points)
    refined = CountryCheck(refine_path=args.refine)
    refined_eval = evaluate(refined, points)

    # cross-tab on airports that land in a *border* cell in basic mode: this is
    # the only population the refinement can change.
    border_idx = [i for i, (k, _, _) in enumerate(base_eval["per_point"])
                  if k == "border"]
    border_n = len(border_idx)
    border_base_agree = sum(base_eval["per_point"][i][1] for i in border_idx)
    border_refined_agree = sum(refined_eval["per_point"][i][1] for i in border_idx)

    report = {
        "airports_tested": total,
        "ground_truth": "OurAirports iso_country (ISO 3166-1 alpha-2)",
        "comparison": "countrycheck iso2 (XKO->XK), else no-country",
        "base": {
            "agreements": base_eval["agree"],
            "agreement_pct": pct(base_eval["agree"], total),
            "by_kind": base_eval["by_kind"],
            "by_kind_agreement_pct": {
                k: pct(base_eval["by_kind_agree"][k], base_eval["by_kind"][k])
                for k in base_eval["by_kind"]},
            "no_country_answers": base_eval["none_count"],
        },
        "refined": {
            "agreements": refined_eval["agree"],
            "agreement_pct": pct(refined_eval["agree"], total),
            "by_kind": refined_eval["by_kind"],
            "by_kind_agreement_pct": {
                k: pct(refined_eval["by_kind_agree"][k], refined_eval["by_kind"][k])
                for k in refined_eval["by_kind"]},
            "no_country_answers": refined_eval["none_count"],
        },
        "border_cell_airports": {
            "count": border_n,
            "base_agreement_pct": pct(border_base_agree, border_n),
            "refined_agreement_pct": pct(border_refined_agree, border_n),
            "answers_changed_by_refinement": int(border_refined_agree
                                                 - border_base_agree),
        },
        "sample_disagreements_refined": refined_eval["disagreements"][:25],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")

    print()
    print(f"{'mode':<16}{'agree':>10}{'of total':>12}{'no-country':>12}")
    for name, ev in (("base", base_eval), ("refined", refined_eval)):
        print(f"{name:<16}{ev['agree']:>10,}{pct(ev['agree'], total):>11.3f}%"
              f"{ev['none_count']:>12,}")
    print()
    print(f"border-cell airports: {border_n:,}")
    print(f"  base    agreement: {pct(border_base_agree, border_n):6.2f}%")
    print(f"  refined agreement: {pct(border_refined_agree, border_n):6.2f}%")
    print(f"  refinement fixed a net {border_refined_agree - border_base_agree:,} "
          f"of them")
    print(f"\nfull report -> {args.output}")


if __name__ == "__main__":
    main()
