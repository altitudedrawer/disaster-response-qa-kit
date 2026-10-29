"""Step 1: load raw inputs.

Earthquakes come from the USGS GeoJSON feed. We flatten each feature into one
row and do NOT validate here -- validation is clean.py's job. Keeping "read"
and "judge" separate makes each easier to test.
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

from . import WGS84

EVENT_COLUMNS = ["id", "mag", "place", "time", "updated", "lon", "lat", "depth_km", "event_type"]


def parse_usgs_geojson(data: dict) -> pd.DataFrame:
    """Flatten a USGS FeatureCollection dict into a DataFrame (one row per feature).

    Missing geometry or properties become NaN/None instead of raising, so that
    clean.py can count and report them.
    """
    rows = []
    for feat in data.get("features") or []:
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        coords = list(coords) + [None] * (3 - len(coords))
        rows.append(
            {
                "id": feat.get("id"),
                "mag": props.get("mag"),
                "place": props.get("place"),
                "time": props.get("time"),
                "updated": props.get("updated"),
                "lon": coords[0],
                "lat": coords[1],
                "depth_km": coords[2],
                "event_type": props.get("type"),
            }
        )
    return pd.DataFrame(rows, columns=EVENT_COLUMNS)


def load_events(path: str | Path) -> pd.DataFrame:
    """Read a USGS GeoJSON file from disk."""
    with open(path, encoding="utf-8") as f:
        return parse_usgs_geojson(json.load(f))


def download(url: str, dest: str | Path, timeout: float = 60.0) -> Path:
    """Download url to dest (used by scripts/download_data.py; tests never call this)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def load_cities(path: str | Path) -> gpd.GeoDataFrame:
    """Read city points (GeoJSON, shapefile, or zip://...). Must have a 'name' column."""
    gdf = gpd.read_file(path)
    if "name" not in gdf.columns:
        raise ValueError(f"cities file {path} has no 'name' column")
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    gdf = gdf[gdf.geometry.geom_type == "Point"]
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84)
    gdf = gdf.to_crs(WGS84).reset_index(drop=True)
    # Natural Earth has 242 repeated names (Aberdeen UK vs Aberdeen US), so add the country.
    # NOTE: we use the point geometry, not NE's 'latitude'/'longitude' columns, which
    # disagree with the geometry by up to 0.7 deg for 301 places (see README).
    if "adm0name" in gdf.columns:
        gdf["label"] = gdf["name"] + " (" + gdf["adm0name"].fillna("?") + ")"
    else:
        gdf["label"] = gdf["name"]
    return gdf
