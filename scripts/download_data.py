"""Download the real public datasets into data/raw/ (gitignored) and write a manifest.

    python scripts/download_data.py                                   # last 365 days, M5+
    python scripts/download_data.py --start 2025-10-20 --end 2026-10-20 --min-mag 5
    python scripts/download_data.py --geonames                        # also fetch GeoNames cities15000

No API keys needed. data/raw/MANIFEST.json records URL, UTC download time, size and
SHA-256 of every file, so a run can be traced back to the exact inputs.
"""
import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pipeline.ingest import download  # noqa: E402

FEED_30D = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson"
QUERY = ("https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
         "&starttime={start}&endtime={end}&minmagnitude={mag}&orderby=time-asc")
NE_PLACES = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places_simple.zip"
GEONAMES = "https://download.geonames.org/export/dump/cities15000.zip"


def main(argv=None):
    today = dt.date.today()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--start", default=str(today - dt.timedelta(days=365)))
    p.add_argument("--end", default=str(today))
    p.add_argument("--min-mag", type=float, default=5.0)
    p.add_argument("--out", default=str(ROOT / "data/raw"))
    p.add_argument("--geonames", action="store_true", help="also download GeoNames cities15000 (CC BY 4.0)")
    a = p.parse_args(argv)

    out = Path(a.out)
    jobs = {
        "usgs_4.5_month.geojson": FEED_30D,
        f"usgs_m{a.min_mag:g}_{a.start}_{a.end}.geojson": QUERY.format(start=a.start, end=a.end, mag=a.min_mag),
        "ne_10m_populated_places_simple.zip": NE_PLACES,
    }
    if a.geonames:
        jobs["geonames_cities15000.zip"] = GEONAMES

    manifest_path = out / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for name, url in jobs.items():
        path = download(url, out / name, timeout=120)
        data = path.read_bytes()
        entry = {
            "url": url,
            "downloaded_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        if name.endswith(".geojson"):
            entry["features"] = len(json.loads(data)["features"])
        manifest[name] = entry
        print(f"{name}: {len(data):,} bytes" + (f", {entry['features']} features" if "features" in entry else ""))
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"manifest -> {manifest_path}")


if __name__ == "__main__":
    main()
