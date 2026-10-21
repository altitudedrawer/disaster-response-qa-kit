"""Step 4: spatial join -- which cities fall inside each event's buffer?

Two stages:
  1. Fast pre-filter: geopandas.sjoin(cities, padded buffers) uses a spatial
     index (R-tree), so we don't compare every city with every quake.
  2. Exact test: geodesic distance <= radius for each candidate pair. This
     removes the polygon's approximation error at the edge.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from . import DEFAULT_RADIUS_KM, WGS84
from .geo import buffer_events, geodesic_distance_m, prefilter_radius_m

OUTPUT_COLUMNS = ["id", "mag", "place", "time", "lon", "lat", "depth_km",
                  "city_count", "city_names", "nearest_city", "nearest_km"]


def city_pairs(events: gpd.GeoDataFrame, cities: gpd.GeoDataFrame,
               radius_km: float = DEFAULT_RADIUS_KM) -> pd.DataFrame:
    """Long table: one row per (event, city) within radius_km, with distance_km."""
    cols = ["id", "city_name", "distance_km"]
    if events.empty or cities.empty:
        return pd.DataFrame(columns=cols)
    radius_m = radius_km * 1000.0
    buffers = buffer_events(events[["id", "lon", "lat", "geometry"]], prefilter_radius_m(radius_m))
    cand = gpd.sjoin(
        cities[["name", "geometry"]].rename(columns={"name": "city_name"}),
        buffers, how="inner", predicate="intersects",
    )
    if cand.empty:
        return pd.DataFrame(columns=cols)
    cand["distance_km"] = geodesic_distance_m(
        cand["lon"].to_numpy(), cand["lat"].to_numpy(),
        cand.geometry.x.to_numpy(), cand.geometry.y.to_numpy(),
    ) / 1000.0
    hits = cand[cand["distance_km"] <= radius_km]
    return hits[cols].sort_values(["id", "distance_km"], kind="stable").reset_index(drop=True)


def cities_near_events(events: gpd.GeoDataFrame, cities: gpd.GeoDataFrame,
                       radius_km: float = DEFAULT_RADIUS_KM) -> gpd.GeoDataFrame:
    """One row per event (epicentre point) with city_count, city_names ("; "-joined,
    nearest first), nearest_city and nearest_km. Events with no cities keep
    city_count = 0 -- a LEFT join, so no quake silently disappears.

    city_names is a string, not a list, because ArcGIS feature layers and
    shapefiles can't store list-valued fields.
    """
    pairs = city_pairs(events, cities, radius_km)
    if events.empty:
        return gpd.GeoDataFrame(columns=OUTPUT_COLUMNS + ["geometry"], geometry="geometry", crs=WGS84)
    agg = (
        pairs.groupby("id", sort=False)
        .agg(city_count=("city_name", "size"),
             city_names=("city_name", lambda s: "; ".join(s)),
             nearest_city=("city_name", "first"),
             nearest_km=("distance_km", "first"))
        .reset_index()
    ) if not pairs.empty else pd.DataFrame(columns=["id", "city_count", "city_names", "nearest_city", "nearest_km"])
    out = events.merge(agg, on="id", how="left")
    out["city_count"] = out["city_count"].fillna(0).astype(int)
    out["city_names"] = out["city_names"].fillna("")
    out["nearest_km"] = pd.to_numeric(out["nearest_km"]).round(2)
    return gpd.GeoDataFrame(out[OUTPUT_COLUMNS], geometry=out.geometry, crs=WGS84)
