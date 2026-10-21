"""Step 3: geodesic buffers.

Why not `point.buffer(1.0)` in lon/lat? One degree of longitude is ~111 km at
the equator but ~56 km at 60 deg N and 0 km at the poles, so a "circle" drawn in
raw degrees is really an ellipse on the ground. Instead we walk 100 km along the
WGS84 ellipsoid in N directions (pyproj.Geod.fwd) and connect the endpoints.

Antimeridian: a buffer around lon=179.5 reaches past 180. We first build the
ring with *continuous* longitudes (e.g. 180.4 instead of -179.6), then cut it at
+/-180 and shift the overflow back by 360 deg -> a valid MultiPolygon.
"""
from __future__ import annotations

import math

import geopandas as gpd
import numpy as np
from pyproj import Geod
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from . import WGS84

GEOD = Geod(ellps="WGS84")
N_VERTICES = 64
_WORLD = box(-180, -90, 180, 90)
_EAST_OVERFLOW = box(180, -90, 540, 90)
_WEST_OVERFLOW = box(-540, -90, -180, 90)


def geodesic_distance_m(lon1, lat1, lon2, lat2) -> np.ndarray:
    """Ellipsoidal (WGS84) distance in metres. Accepts scalars or arrays."""
    _, _, dist = GEOD.inv(lon1, lat1, lon2, lat2)
    return np.asarray(dist, dtype=float)


def geodesic_buffer(lon: float, lat: float, radius_m: float, n_vertices: int = N_VERTICES):
    """Polygon (or MultiPolygon if it crosses +/-180) whose vertices are exactly
    radius_m from (lon, lat) along the ellipsoid.

    Raises ValueError if the buffer would contain a pole (out of scope; would need
    a polar-cap polygon). Nearest-pole check: any epicentre within radius of 90 deg.
    """
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    pole_lat = 90.0 if lat >= 0 else -90.0
    if float(geodesic_distance_m(lon, lat, lon, pole_lat)) <= radius_m:
        raise ValueError(f"buffer around ({lon}, {lat}) would contain a pole; not supported")

    az = np.linspace(0.0, 360.0, n_vertices, endpoint=False)
    lons, lats, _ = GEOD.fwd(np.full(n_vertices, lon), np.full(n_vertices, lat), az, np.full(n_vertices, radius_m))
    lons = np.asarray(lons)
    # unwrap so the ring is continuous around the centre (no 360-degree jumps)
    lons = np.where(lons - lon > 180, lons - 360, lons)
    lons = np.where(lons - lon < -180, lons + 360, lons)
    ring = Polygon(zip(lons, lats))

    if ring.bounds[0] >= -180 and ring.bounds[2] <= 180:
        return ring
    parts = [
        ring.intersection(_WORLD),
        affinity.translate(ring.intersection(_EAST_OVERFLOW), xoff=-360),
        affinity.translate(ring.intersection(_WEST_OVERFLOW), xoff=360),
    ]
    merged = unary_union([p for p in parts if not p.is_empty])
    return merged


def prefilter_radius_m(radius_m: float, n_vertices: int = N_VERTICES, margin: float = 0.01) -> float:
    """Radius for a buffer that fully *contains* the true circle.

    A polygon with vertices on the circle is inscribed: its edge midpoints are only
    r*cos(pi/n) from the centre, so it would miss cities at e.g. 99.95 km. Pushing
    the vertices out by 1/cos(pi/n) (+1% for lon/lat edge curvature) makes the
    polygon a safe pre-filter; join.py then applies the exact distance test.
    """
    return radius_m / math.cos(math.pi / n_vertices) * (1.0 + margin)


def buffer_events(events: gpd.GeoDataFrame, radius_m: float, n_vertices: int = N_VERTICES) -> gpd.GeoDataFrame:
    """Replace each event's point geometry with its geodesic buffer (same columns, WGS84)."""
    geoms = [geodesic_buffer(x, y, radius_m, n_vertices) for x, y in zip(events["lon"], events["lat"])]
    return gpd.GeoDataFrame(events.drop(columns="geometry"), geometry=geoms, crs=WGS84)
