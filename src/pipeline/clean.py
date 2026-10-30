"""Step 2: validate and filter earthquake rows.

Every rule that drops rows is counted in a report, so real-data problems are
visible instead of silently disappearing.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import pandas as pd

from . import DEFAULT_MIN_MAG, WGS84
from .ingest import EVENT_COLUMNS


@dataclass
class CleanResult:
    """Output of clean_events.

    events:  valid events as a GeoDataFrame (EPSG:4326, Point geometry, same columns as the input
             plus geometry; 'time'/'updated' converted to UTC datetimes)
    dropped: rule name -> number of rows that rule removed (all five keys always present)
    rows_in: number of input rows
    """
    events: gpd.GeoDataFrame
    dropped: dict[str, int] = field(default_factory=dict)
    rows_in: int = 0


def _empty_events() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {c: pd.Series(dtype="object") for c in EVENT_COLUMNS}, geometry=[], crs=WGS84
    )


def clean_events(df: pd.DataFrame, min_mag: float = DEFAULT_MIN_MAG) -> CleanResult:
    """Return valid events with magnitude >= min_mag as a point GeoDataFrame (WGS84).

    `df` is the output of ingest.parse_usgs_geojson, with columns
    id, mag, place, time, updated, lon, lat, depth_km, event_type
    (time/updated are epoch milliseconds, as in the USGS feed).

    Rules, applied in this order:
      1. null_magnitude       - mag missing or not a number
      2. invalid_coordinates  - lon/lat missing, non-numeric, lat outside [-90, 90],
                                or lon outside [-180, 180]. We do NOT try to "fix"
                                e.g. lon=200, because guessing could move a quake.
      3. duplicate_id         - same id seen twice; keep the most recently updated row
      4. non_earthquake       - USGS 'type' is set and isn't "earthquake" (the real
                                M5+ year query contained a magnitude-5.2 *landslide*).
                                Missing type is kept: absence isn't evidence.
      5. below_min_magnitude  - mag < min_mag
    """
    rows_in = len(df)
    dropped = {k: 0 for k in ("null_magnitude", "invalid_coordinates", "duplicate_id", "non_earthquake", "below_min_magnitude")}
    if rows_in == 0:
        return CleanResult(_empty_events(), dropped, 0)

    df = df.copy()
    for col in ("mag", "lon", "lat", "depth_km", "time", "updated"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    bad_mag = df["mag"].isna()
    dropped["null_magnitude"] = int(bad_mag.sum())
    df = df[~bad_mag]

    bad_xy = (
        df["lon"].isna() | df["lat"].isna()
        | ~df["lat"].between(-90, 90) | ~df["lon"].between(-180, 180)
    )
    dropped["invalid_coordinates"] = int(bad_xy.sum())
    df = df[~bad_xy]

    before = len(df)
    has_id = df["id"].notna()  # rows without an id can't be matched, so never dedupe them
    deduped = (
        df[has_id]
        .sort_values("updated", ascending=False, na_position="last", kind="stable")
        .drop_duplicates(subset="id", keep="first")
    )
    df = pd.concat([deduped, df[~has_id]])
    dropped["duplicate_id"] = before - len(df)

    not_eq = df["event_type"].notna() & (df["event_type"] != "earthquake")
    dropped["non_earthquake"] = int(not_eq.sum())
    df = df[~not_eq]

    low = df["mag"] < min_mag
    dropped["below_min_magnitude"] = int(low.sum())
    df = df[~low]

    if df.empty:
        return CleanResult(_empty_events(), dropped, rows_in)

    df = df.sort_values("time", kind="stable").reset_index(drop=True)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df["updated"] = pd.to_datetime(df["updated"], unit="ms", utc=True)
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs=WGS84)
    return CleanResult(gdf, dropped, rows_in)
