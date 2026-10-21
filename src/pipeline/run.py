"""Command-line entry point.

    python -m pipeline.run --events EVENTS.geojson --cities CITIES.geojson --out output/results.geojson
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import DEFAULT_MIN_MAG, DEFAULT_RADIUS_KM
from .clean import clean_events
from .ingest import load_cities, load_events
from .join import cities_near_events


def run(events_path, cities_path, out_path, radius_km=DEFAULT_RADIUS_KM, min_mag=DEFAULT_MIN_MAG) -> dict:
    t0 = time.perf_counter()
    raw = load_events(events_path)
    cleaned = clean_events(raw, min_mag=min_mag)
    cities = load_cities(cities_path)
    result = cities_near_events(cleaned.events, cities, radius_km)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = result.assign(time=result["time"].astype(str))  # ISO strings for GeoJSON
    out_path.write_text(result.to_json(drop_id=True), encoding="utf-8")

    summary = {
        "events_in": cleaned.rows_in,
        "dropped": cleaned.dropped,
        "events_kept": len(cleaned.events),
        "cities": len(cities),
        "events_with_cities": int((result["city_count"] > 0).sum()),
        "event_city_pairs": int(result["city_count"].sum()),
        "radius_km": radius_km,
        "min_mag": min_mag,
        "output": str(out_path),
        "runtime_s": round(time.perf_counter() - t0, 3),
    }
    return summary


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Cities within R km of M>=X earthquakes")
    p.add_argument("--events", required=True)
    p.add_argument("--cities", required=True)
    p.add_argument("--out", default="output/events_with_cities.geojson")
    p.add_argument("--radius-km", type=float, default=DEFAULT_RADIUS_KM)
    p.add_argument("--min-mag", type=float, default=DEFAULT_MIN_MAG)
    a = p.parse_args(argv)
    print(json.dumps(run(a.events, a.cities, a.out, a.radius_km, a.min_mag), indent=2))


if __name__ == "__main__":
    main()
