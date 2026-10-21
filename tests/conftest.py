from pathlib import Path

import geopandas as gpd
import pytest
from pyproj import Geod
from shapely.geometry import Point

FIXTURES = Path(__file__).parent / "fixtures"
GEOD = Geod(ellps="WGS84")


@pytest.fixture
def events_path():
    return FIXTURES / "earthquakes_sample.geojson"


@pytest.fixture
def cities_path():
    return FIXTURES / "cities_sample.geojson"


def offset(lon, lat, azimuth_deg, km):
    """Point km away from (lon, lat) along the ellipsoid -- test helper with a known distance."""
    x, y, _ = GEOD.fwd(lon, lat, azimuth_deg, km * 1000)
    return x, y


def make_events(rows):
    """rows: [(id, lon, lat, mag)] -> cleaned-style events GeoDataFrame."""
    return gpd.GeoDataFrame(
        {"id": [r[0] for r in rows], "lon": [r[1] for r in rows], "lat": [r[2] for r in rows],
         "mag": [r[3] for r in rows], "place": "test", "time": 0, "depth_km": 10.0},
        geometry=[Point(r[1], r[2]) for r in rows], crs="EPSG:4326")


def make_cities(rows):
    """rows: [(name, lon, lat)] -> cities GeoDataFrame."""
    return gpd.GeoDataFrame({"name": [r[0] for r in rows]},
                            geometry=[Point(r[1], r[2]) for r in rows], crs="EPSG:4326")
