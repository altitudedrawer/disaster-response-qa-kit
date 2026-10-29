"""Step 5 (optional): publish the output GeoJSON as an ArcGIS Online hosted feature layer.

    python -m pipeline.publish output/m5_1yr.geojson --dry-run          # no login, no network
    python -m pipeline.publish output/m5_1yr.geojson --name drqa_m5_1yr  # real publish

Written against ArcGIS API for Python 2.4.4 (checked 2026-10-29):
    GIS(url, username, password)
    folder = gis.content.folders.get()                       # root folder
    item = folder.add(item_properties=ItemProperties(...), file=path).result()   # add() returns a Job
    layer_item = item.publish(publish_parameters={"name": ...})
    layer_item.sharing.sharing_level = SharingLevel.EVERYONE  # optional
Credentials come ONLY from environment variables (see .env.example) and are never printed.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

REQUIRED_FIELDS = ["id", "mag", "place", "time", "city_count", "city_names", "nearest_city", "nearest_km"]
CREDENTIAL_VARS = ("ARCGIS_URL", "ARCGIS_USERNAME", "ARCGIS_PASSWORD")
# Esri field names: start with a letter, then letters/digits/underscore. 64 is a safe upper bound.
FIELD_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
SERVICE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,97}$")
DATA_CREDITS = ("Earthquakes: USGS (public domain). Cities: Natural Earth (public domain). "
                "Processed by disaster-response-qa-kit.")


class PublishError(Exception):
    """Validation or configuration problem. Message never contains credential values."""


def validate_geojson(path: str | Path) -> dict:
    """Check the file is something ArcGIS can publish cleanly. Returns a small report.

    Raises PublishError listing every problem found (not just the first).
    """
    path = Path(path)
    if not path.is_file():
        raise PublishError(f"file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PublishError(f"not valid JSON: {e}") from None
    if data.get("type") != "FeatureCollection":
        raise PublishError("top-level 'type' must be 'FeatureCollection'")
    feats = data.get("features") or []
    if not feats:
        raise PublishError("FeatureCollection has no features; refusing to publish an empty layer")

    problems: list[str] = []
    fields: set[str] = set()
    xs, ys = [], []
    for i, f in enumerate(feats):
        g = f.get("geometry") or {}
        c = g.get("coordinates")
        if g.get("type") != "Point" or not isinstance(c, list) or len(c) < 2:
            problems.append(f"feature {i}: geometry must be a Point")
        else:
            x, y = c[0], c[1]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y)) \
                    or not (-180 <= x <= 180 and -90 <= y <= 90):
                problems.append(f"feature {i}: coordinates {c[:2]} are not valid WGS84 lon/lat")
            else:
                xs.append(x)
                ys.append(y)
        props = f.get("properties") or {}
        fields |= props.keys()
        missing = [k for k in REQUIRED_FIELDS if k not in props]
        if missing:
            problems.append(f"feature {i}: missing properties {missing}")
        nested = [k for k, v in props.items() if isinstance(v, (list, dict))]
        if nested:
            problems.append(f"feature {i}: list/dict values can't be stored in a feature layer: {nested}")
        if len(problems) > 20:
            problems.append("... (stopping after 20 problems)")
            break
    bad_names = sorted(k for k in fields if not FIELD_NAME_RE.match(k))
    if bad_names:
        problems.append(f"invalid field names for ArcGIS: {bad_names}")
    if problems:
        raise PublishError("GeoJSON failed validation:\n  - " + "\n  - ".join(problems))
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "features": len(feats),
        "fields": sorted(fields),
        "bbox": [min(xs), min(ys), max(xs), max(ys)],
    }


def build_item_properties(report: dict, title: str) -> dict:
    """Plain-dict item metadata (turned into arcgis ItemProperties at publish time)."""
    return {
        "title": title,
        "tags": ["earthquakes", "USGS", "disaster response", "geodesic buffer", "python"],
        "snippet": "Earthquake epicentres with the cities within 100 km (geodesic).",
        "description": (f"{report['features']} events. Fields: {', '.join(report['fields'])}. "
                        "city_names is a '; '-separated list, nearest first."),
        "license_info": DATA_CREDITS,
    }


def read_credentials(env=os.environ) -> dict:
    """Read ARCGIS_URL / ARCGIS_USERNAME / ARCGIS_PASSWORD. Error lists missing NAMES only."""
    missing = [k for k in CREDENTIAL_VARS if not env.get(k)]
    if missing:
        raise PublishError(f"missing environment variables: {', '.join(missing)} (see .env.example)")
    return {"url": env["ARCGIS_URL"], "username": env["ARCGIS_USERNAME"], "password": env["ARCGIS_PASSWORD"]}


def dry_run(path, title: str, service_name: str, env=os.environ) -> dict:
    """Validate and prepare everything WITHOUT importing arcgis or touching the network."""
    if not SERVICE_NAME_RE.match(service_name):
        raise PublishError(f"service name {service_name!r}: use letters, digits, underscore; start with a letter")
    report = validate_geojson(path)
    return {
        "mode": "dry-run",
        "validation": report,
        "item_properties": build_item_properties(report, title),
        "publish_parameters": {"name": service_name},
        "credentials_present": {k: bool(env.get(k)) for k in CREDENTIAL_VARS},  # booleans, never values
    }


def publish(path, title: str, service_name: str, share_public: bool = False, gis=None, env=os.environ) -> dict:
    """Real publish. `gis` can be injected (tests pass a fake); otherwise log in from env vars."""
    plan = dry_run(path, title, service_name, env)
    from arcgis.gis import ItemProperties, ItemTypeEnum, SharingLevel  # imported only for real publishing

    if gis is None:
        from arcgis.gis import GIS
        gis = GIS(**read_credentials(env))
    props = plan["item_properties"]
    folder = gis.content.folders.get()
    item = folder.add(
        item_properties=ItemProperties(item_type=ItemTypeEnum.GEOJSON, **props),
        file=str(path),
    ).result()
    layer_item = item.publish(publish_parameters=plan["publish_parameters"])
    if share_public:
        layer_item.sharing.sharing_level = SharingLevel.EVERYONE
    return {
        "mode": "published",
        "geojson_item_id": item.id,
        "layer_item_id": layer_item.id,
        "service_url": layer_item.url,
        "layer_url": layer_item.url.rstrip("/") + "/0",
        "shared_public": share_public,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Publish output GeoJSON as an ArcGIS hosted feature layer")
    p.add_argument("geojson")
    p.add_argument("--title", default="DisasterResponse QA Kit: cities within 100 km of M5+ earthquakes")
    p.add_argument("--name", default="drqa_m5_cities", help="service name; must be unique in your org")
    p.add_argument("--dry-run", action="store_true", help="validate + prepare only; no login, no network")
    p.add_argument("--share-public", action="store_true", help="share layer with everyone (needed for "
                   "contract tests without a token)")
    a = p.parse_args(argv)
    try:
        out = dry_run(a.geojson, a.title, a.name) if a.dry_run else \
            publish(a.geojson, a.title, a.name, share_public=a.share_public)
    except PublishError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
