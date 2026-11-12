import math

import geopandas as gpd
import pandas as pd
import pytest
from pyproj import Geod
from shapely.geometry import Point

from pipeline.join import cities_near_events

GEOD = Geod(ellps="WGS84")
LON0, LAT0 = 0.0, 0.0


def _point_at(lon, lat, bearing_deg, distance_km):
    """Return (lon, lat) reached from (lon, lat) going bearing_deg for distance_km."""
    lon2, lat2, _ = GEOD.fwd(lon, lat, bearing_deg, distance_km * 1000.0)
    return lon2, lat2


def _make_events(rows):
    """rows: list of dicts with id, mag, place, time, lon, lat, depth_km."""
    records = []
    for r in rows:
        rec = dict(r)
        rec["geometry"] = Point(rec["lon"], rec["lat"])
        records.append(rec)
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


def _make_cities(names_with_points, labels=None):
    records = []
    for i, (name, (lon, lat)) in enumerate(names_with_points):
        rec = {"name": name, "geometry": Point(lon, lat)}
        if labels is not None:
            rec["label"] = labels[i]
        records.append(rec)
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


def _single_event(lon=LON0, lat=LAT0, event_id="e1"):
    return _make_events(
        [
            dict(
                id=event_id,
                mag=5.0,
                place="test place",
                time="2020-01-01T00:00:00",
                lon=lon,
                lat=lat,
                depth_km=10.0,
            )
        ]
    )


def test_cities_near_events_output_columns_and_order():
    """Check the exact output columns appear in the documented order."""
    events = _single_event()
    cities = _make_cities([("A", _point_at(LON0, LAT0, 0, 10.0))])
    out = cities_near_events(events, cities)
    expected = [
        "id",
        "mag",
        "place",
        "time",
        "lon",
        "lat",
        "depth_km",
        "city_count",
        "city_names",
        "nearest_city",
        "nearest_km",
        "geometry",
    ]
    assert list(out.columns) == expected


def test_cities_near_events_left_join_preserves_all_events():
    """Every input event must appear in the output, even with no nearby cities."""
    events = _make_events(
        [
            dict(id="e1", mag=5.0, place="p", time="t", lon=0.0, lat=0.0, depth_km=1.0),
            dict(id="e2", mag=6.0, place="q", time="t", lon=50.0, lat=50.0, depth_km=2.0),
        ]
    )
    cities = _make_cities([("A", _point_at(0.0, 0.0, 0, 10.0))])
    out = cities_near_events(events, cities)
    assert len(out) == 2
    assert set(out["id"]) == {"e1", "e2"}


def test_cities_near_events_no_city_in_radius():
    """Events with no city within radius get city_count 0, empty names, NaN nearest."""
    events = _single_event()
    cities = _make_cities([("Far", _point_at(LON0, LAT0, 0, 500.0))])
    out = cities_near_events(events, cities, radius_km=100.0)
    row = out.iloc[0]
    assert row["city_count"] == 0
    assert row["city_names"] == ""
    assert pd.isna(row["nearest_city"])
    assert pd.isna(row["nearest_km"])


def test_cities_near_events_counts_cities_within_radius():
    """All cities within the radius are counted."""
    events = _single_event()
    cities = _make_cities(
        [
            ("A", _point_at(LON0, LAT0, 0, 10.0)),
            ("B", _point_at(LON0, LAT0, 90, 20.0)),
            ("C", _point_at(LON0, LAT0, 180, 30.0)),
        ]
    )
    out = cities_near_events(events, cities, radius_km=50.0)
    assert out.iloc[0]["city_count"] == 3


def test_cities_near_events_excludes_city_beyond_radius():
    """A city just outside the radius is not counted."""
    events = _single_event()
    cities = _make_cities(
        [
            ("In", _point_at(LON0, LAT0, 0, 50.0)),
            ("Out", _point_at(LON0, LAT0, 0, 150.0)),
        ]
    )
    out = cities_near_events(events, cities, radius_km=100.0)
    row = out.iloc[0]
    assert row["city_count"] == 1
    assert row["nearest_city"] == "In"


def test_cities_near_events_radius_boundary_inclusive():
    """A city exactly at the radius is counted (docstring says <=)."""
    events = _single_event()
    cities = _make_cities([("Edge", _point_at(LON0, LAT0, 0, 100.0))])
    out = cities_near_events(events, cities, radius_km=100.0)
    assert out.iloc[0]["city_count"] == 1


def test_cities_near_events_default_radius_is_100():
    """The default radius is 100 km: a city at 99 km counts, one at 101 km does not."""
    events = _single_event()
    cities = _make_cities(
        [
            ("In", _point_at(LON0, LAT0, 0, 99.0)),
            ("Out", _point_at(LON0, LAT0, 180, 101.0)),
        ]
    )
    out = cities_near_events(events, cities)
    row = out.iloc[0]
    assert row["city_count"] == 1
    assert row["nearest_city"] == "In"


def test_cities_near_events_nearest_city_and_km():
    """nearest_city and nearest_km reflect the closest city, km rounded to 0.01."""
    events = _single_event()
    cities = _make_cities(
        [
            ("Far", _point_at(LON0, LAT0, 0, 80.0)),
            ("Near", _point_at(LON0, LAT0, 90, 12.345)),
        ]
    )
    out = cities_near_events(events, cities, radius_km=100.0)
    row = out.iloc[0]
    assert row["nearest_city"] == "Near"
    assert row["nearest_km"] == pytest.approx(12.35, abs=1e-9)


def test_cities_near_events_city_names_sorted_nearest_first():
    """city_names lists names joined by '; ' ordered nearest first."""
    events = _single_event()
    cities = _make_cities(
        [
            ("Third", _point_at(LON0, LAT0, 0, 30.0)),
            ("First", _point_at(LON0, LAT0, 0, 10.0)),
            ("Second", _point_at(LON0, LAT0, 0, 20.0)),
        ]
    )
    out = cities_near_events(events, cities, radius_km=100.0)
    assert out.iloc[0]["city_names"] == "First; Second; Third"


def test_cities_near_events_uses_label_when_present():
    """When a 'label' column exists, city_names uses labels instead of names."""
    events = _single_event()
    cities = _make_cities(
        [
            ("Aberdeen", _point_at(LON0, LAT0, 0, 10.0)),
            ("Dundee", _point_at(LON0, LAT0, 0, 20.0)),
        ],
        labels=["Aberdeen (United Kingdom)", "Dundee (United Kingdom)"],
    )
    out = cities_near_events(events, cities, radius_km=100.0)
    row = out.iloc[0]
    assert row["city_names"] == "Aberdeen (United Kingdom); Dundee (United Kingdom)"
    assert row["nearest_city"] == "Aberdeen (United Kingdom)"


def test_cities_near_events_per_event_nearest():
    """Each event computes its own nearest city independently."""
    events = _make_events(
        [
            dict(id="e1", mag=5.0, place="p", time="t", lon=0.0, lat=0.0, depth_km=1.0),
            dict(id="e2", mag=6.0, place="q", time="t", lon=10.0, lat=0.0, depth_km=2.0),
        ]
    )
    cities = _make_cities(
        [
            ("NearZero", _point_at(0.0, 0.0, 0, 5.0)),
            ("NearTen", _point_at(10.0, 0.0, 0, 5.0)),
        ]
    )
    out = cities_near_events(events, cities, radius_km=100.0)
    by_id = out.set_index("id")
    assert by_id.loc["e1", "nearest_city"] == "NearZero"
    assert by_id.loc["e2", "nearest_city"] == "NearTen"


def test_cities_near_events_empty_events_returns_empty():
    """Empty events input yields an empty output (left join of nothing)."""
    events = _single_event().iloc[0:0]
    cities = _make_cities([("A", _point_at(LON0, LAT0, 0, 10.0))])
    out = cities_near_events(events, cities)
    assert len(out) == 0


def test_cities_near_events_empty_cities_all_zero():
    """With no cities, every event gets city_count 0 and NaN nearest."""
    events = _make_events(
        [
            dict(id="e1", mag=5.0, place="p", time="t", lon=0.0, lat=0.0, depth_km=1.0),
            dict(id="e2", mag=6.0, place="q", time="t", lon=10.0, lat=0.0, depth_km=2.0),
        ]
    )
    cities = _make_cities([])
    out = cities_near_events(events, cities)
    assert len(out) == 2
    assert (out["city_count"] == 0).all()
    assert (out["city_names"] == "").all()
    assert out["nearest_city"].isna().all()
    assert out["nearest_km"].isna().all()


def test_cities_near_events_inputs_not_mutated():
    """Input GeoDataFrames are not modified by the join."""
    events = _single_event()
    cities = _make_cities([("A", _point_at(LON0, LAT0, 0, 10.0))])
    events_before = events.copy(deep=True)
    cities_before = cities.copy(deep=True)
    cities_near_events(events, cities, radius_km=100.0)
    pd.testing.assert_frame_equal(events, events_before)
    pd.testing.assert_frame_equal(cities, cities_before)


def test_cities_near_events_negative_radius_raises():
    """A negative radius is invalid and should raise."""
    events = _single_event()
    cities = _make_cities([("A", _point_at(LON0, LAT0, 0, 10.0))])
    with pytest.raises((ValueError, AssertionError)):
        cities_near_events(events, cities, radius_km=-1.0)
