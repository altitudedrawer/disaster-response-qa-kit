"""Independent correctness check on REAL data: brute-force every (event, city) geodesic
distance and compare with the pipeline output. Slow on purpose (no spatial index).

    python scripts/oracle_check.py output/m5_1yr.geojson zip://data/raw/ne_10m_populated_places_simple.zip
Exit code 1 if any event's city list differs.
"""
import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pipeline.geo import geodesic_distance_m  # noqa: E402


def main(result_path, cities_path, radius_km=100.0):
    feats = json.loads(Path(result_path).read_text())["features"]
    c = gpd.read_file(cities_path)
    labels = (c["name"] + " (" + c["adm0name"] + ")").to_numpy() if "adm0name" in c else c["name"].to_numpy()
    cx, cy = c.geometry.x.to_numpy(), c.geometry.y.to_numpy()
    t0, bad = time.perf_counter(), []
    for f in feats:
        lon, lat = f["geometry"]["coordinates"]
        d = geodesic_distance_m(np.full(cx.size, lon), np.full(cy.size, lat), cx, cy) / 1000
        expected = sorted(labels[d <= radius_km])
        got = sorted(x for x in f["properties"]["city_names"].split("; ") if x)
        if expected != got:
            bad.append(f["properties"]["id"])
    print(f"{len(feats)} events x {len(c)} cities checked in {time.perf_counter() - t0:.1f}s; mismatches: {len(bad)}")
    for i in bad[:10]:
        print("  MISMATCH", i)
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2], *(float(x) for x in sys.argv[3:4])))
