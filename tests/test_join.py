import pandas as pd
import pytest

from pipeline.join import OUTPUT_COLUMNS, city_pairs, cities_near_events
from tests.conftest import make_cities, make_events, offset


@pytest.fixture
def tiny():
    """Hand-made example with distances known by construction."""
    events = make_events([("A", 0.0, 0.0, 6.0), ("B", 10.0, 50.0, 5.5), ("C", -140.0, -45.0, 5.2)])
    cities = make_cities([
        ("A50", *offset(0, 0, 90, 50)),      # 50 km east of A
        ("A99", *offset(0, 0, 0, 99)),       # 99 km north of A
        ("A101", *offset(0, 0, 200, 101)),   # just outside A
        ("B30", *offset(10, 50, 300, 30)),   # 30 km from B
        ("Far", 100.0, 0.0),
    ])
    return events, cities


def test_join_correctness_on_tiny_example(tiny):
    out = cities_near_events(*tiny, radius_km=100).set_index("id")
    assert out.loc["A", "city_count"] == 2
    assert out.loc["A", "city_names"] == "A50; A99"           # nearest first
    assert out.loc["A", "nearest_city"] == "A50"
    assert out.loc["A", "nearest_km"] == pytest.approx(50.0, abs=0.01)
    assert out.loc["B", "city_count"] == 1 and out.loc["B", "city_names"] == "B30"


def test_event_with_no_cities_is_kept_with_zero(tiny):
    out = cities_near_events(*tiny).set_index("id")
    assert out.loc["C", "city_count"] == 0 and out.loc["C", "city_names"] == ""
    assert pd.isna(out.loc["C", "nearest_city"])


def test_output_schema_and_geometry(tiny):
    out = cities_near_events(*tiny)
    assert list(out.columns) == OUTPUT_COLUMNS + ["geometry"]
    assert (out.geometry.geom_type == "Point").all() and out.crs.to_epsg() == 4326
    assert len(out) == 3


def test_city_near_two_events_counts_for_both():
    events = make_events([("E1", 0.0, 0.0, 5), ("E2", 1.0, 0.0, 5)])     # ~111 km apart
    cities = make_cities([("Mid", 0.5, 0.0)])                          # ~55 km from each
    out = cities_near_events(events, cities).set_index("id")
    assert out.loc["E1", "city_count"] == 1 and out.loc["E2", "city_count"] == 1


def test_join_across_antimeridian():
    events = make_events([("AM", 179.9, 0.0, 6.0)])
    cities = make_cities([("West", -179.9, 0.0), ("East", 179.5, 0.0), ("Opposite", 0.0, 0.0)])
    out = cities_near_events(events, cities).set_index("id")
    assert out.loc["AM", "city_count"] == 2
    assert out.loc["AM", "nearest_city"] in {"West", "East"}
    assert "Opposite" not in out.loc["AM", "city_names"]


def test_exact_distance_filter_removes_polygon_edge_false_positives():
    """Pre-filter polygon is padded, so a city at 100.5 km may be a candidate;
    the exact geodesic check must still reject it."""
    events = make_events([("E", 30.0, 40.0, 5)])
    cities = make_cities([("Edge", *offset(30, 40, 33, 100.5)), ("In", *offset(30, 40, 33, 99.9))])
    pairs = city_pairs(events, cities)
    assert list(pairs["city_name"]) == ["In"]


def test_empty_events():
    out = cities_near_events(make_events([]), make_cities([("X", 0, 0)]))
    assert out.empty and list(out.columns) == OUTPUT_COLUMNS + ["geometry"]


def test_empty_cities(tiny):
    events, _ = tiny
    out = cities_near_events(events, make_cities([]))
    assert len(out) == 3 and (out["city_count"] == 0).all()


@pytest.mark.parametrize("lat", [0.0, 60.0])
def test_city_just_inside_radius_between_polygon_vertices_is_found(lat):
    """Regression test found by mutation testing: with an *unpadded* (inscribed)
    buffer, a city at 99.95 km lying between two vertices falls outside the
    polygon (edge midpoint is only ~99.88 km out) and would be silently missed."""
    from pipeline.geo import N_VERTICES
    half_step = 360 / N_VERTICES / 2          # azimuth of an edge midpoint
    events = make_events([("E", 10.0, lat, 5)])
    cities = make_cities([("Edge", *offset(10.0, lat, half_step, 99.95))])
    assert cities_near_events(events, cities).iloc[0]["city_count"] == 1
