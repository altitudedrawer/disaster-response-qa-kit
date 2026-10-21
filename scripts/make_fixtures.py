"""Build the small, committed test fixtures from real downloads (run once; output is committed).

    python scripts/make_fixtures.py

Inputs (gitignored, from scripts/download_data.py or the Phase 1 snapshot):
  data/raw/usgs_4.5_month.geojson
  data/raw/ne_10m_populated_places_simple.zip
Outputs:
  tests/fixtures/earthquakes_sample.geojson  (92 real USGS events + 8 synthetic edge cases)
  tests/fixtures/cities_sample.geojson       (200 Natural Earth populated places)
Deterministic: fixed random seed, so re-running on the same inputs gives the same files.
"""
import copy
import json
import random
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pipeline.geo import geodesic_distance_m  # noqa: E402

SEED = 42
N_REAL_EVENTS = 92
N_CITIES = 200
KEEP_PROPS = ["mag", "place", "time", "updated", "type"]


def synthetic(fid, lon, lat, mag, note, place="synthetic test case", time=1_760_000_000_000):
    geom = None if lon is None else {"type": "Point", "coordinates": [lon, lat, 10.0]}
    props = {"mag": mag, "place": place, "time": time, "updated": time, "type": "earthquake", "_note": note}
    return {"type": "Feature", "id": fid, "properties": props, "geometry": geom}


def main():
    rng = random.Random(SEED)
    feed = json.loads((ROOT / "data/raw/usgs_4.5_month.geojson").read_text())
    feats = sorted(feed["features"], key=lambda f: f["id"])
    real = rng.sample(feats, N_REAL_EVENTS)
    real = [{"type": "Feature", "id": f["id"], "geometry": f["geometry"],
             "properties": {k: f["properties"].get(k) for k in KEEP_PROPS}} for f in real]
    real.sort(key=lambda f: f["properties"]["time"])

    first_m5 = next(f for f in real if f["properties"]["mag"] >= 5)
    dup = copy.deepcopy(first_m5)
    dup["properties"]["updated"] -= 86_400_000          # older copy -> must be dropped
    dup["properties"]["mag"] = 1.0
    dup["properties"]["_note"] = "SYNTHETIC: stale duplicate of a real id (older 'updated', fake mag 1.0)"

    synth = [
        synthetic("synthetic_null_mag", 140.0, 36.0, None, "SYNTHETIC: mag is null"),
        synthetic("synthetic_bad_lat", 10.0, 95.0, 6.0, "SYNTHETIC: latitude out of range"),
        synthetic("synthetic_bad_lon", 200.0, 10.0, 6.0, "SYNTHETIC: longitude out of range"),
        synthetic("synthetic_no_geometry", None, None, 6.0, "SYNTHETIC: geometry is null"),
        synthetic("synthetic_string_mag", 120.0, 23.0, "big", "SYNTHETIC: non-numeric magnitude"),
        synthetic("synthetic_antimeridian", -179.95, -16.45, 5.6,
                  "SYNTHETIC: west of 180; Labasa (Fiji, lon +179.38) is ~71 km away across the antimeridian"),
        synthetic("synthetic_open_ocean", -140.0, -45.0, 5.2, "SYNTHETIC: valid M5+ with no city nearby"),
        dup,
    ]
    features = real + synth
    (ROOT / "tests/fixtures/earthquakes_sample.geojson").write_text(
        json.dumps({"type": "FeatureCollection",
                    "metadata": {"source": "USGS 4.5_month feed snapshot 2026-10-21 UTC + synthetic cases",
                                 "count": len(features)},
                    "features": features}, indent=1))

    cities = gpd.read_file("zip://" + str(ROOT / "data/raw/ne_10m_populated_places_simple.zip"))
    cities = cities[["name", "adm0name", "pop_max", "geometry"]].reset_index(drop=True)
    cx, cy = cities.geometry.x.to_numpy(), cities.geometry.y.to_numpy()
    pts = [f["geometry"]["coordinates"][:2] for f in features
           if f["geometry"] and -180 <= f["geometry"]["coordinates"][0] <= 180
           and -90 <= f["geometry"]["coordinates"][1] <= 90]
    near = np.full(len(cities), np.inf)
    for lon, lat in pts:
        d = geodesic_distance_m(np.full(len(cx), lon), np.full(len(cy), lat), cx, cy) / 1000
        near = np.minimum(near, d)
    # cities within 150 km of some event (gives real join hits AND near-misses 100-150 km)
    pick = list(np.argsort(near)[: int(min((near <= 150).sum(), 120))])
    pick += [i for i in np.where(np.abs(cx) > 177)[0] if i not in pick]  # antimeridian cities
    rest = [i for i in range(len(cities)) if i not in set(pick)]
    pick += rng.sample(rest, N_CITIES - len(pick))
    out = cities.iloc[sorted(int(i) for i in pick)].reset_index(drop=True)
    out.to_file(ROOT / "tests/fixtures/cities_sample.geojson", driver="GeoJSON")
    print(f"events: {len(features)} ({len(real)} real + {len(synth)} synthetic); "
          f"cities: {len(out)} ({int((near[pick] <= 100).sum())} within 100 km of some event)")


if __name__ == "__main__":
    main()
