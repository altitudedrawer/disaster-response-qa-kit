import pandas as pd
import pytest

from pipeline.clean import clean_events
from pipeline.ingest import EVENT_COLUMNS, load_events


def frame(rows):
    """rows of dicts with any subset of EVENT_COLUMNS."""
    base = {"id": None, "mag": 5.5, "place": "p", "time": 0, "updated": 0, "lon": 0.0, "lat": 0.0, "depth_km": 10}
    return pd.DataFrame([{**base, **r} for r in rows], columns=EVENT_COLUMNS)


def test_empty_input():
    res = clean_events(pd.DataFrame(columns=EVENT_COLUMNS))
    assert res.events.empty and res.rows_in == 0
    assert res.events.crs.to_epsg() == 4326
    assert set(res.dropped.values()) == {0}


@pytest.mark.parametrize("bad_mag", [None, float("nan"), "big", ""])
def test_missing_or_null_magnitude_dropped(bad_mag):
    res = clean_events(frame([{"id": "a", "mag": bad_mag}, {"id": "b"}]))
    assert list(res.events["id"]) == ["b"]
    assert res.dropped["null_magnitude"] == 1


@pytest.mark.parametrize("lon,lat", [(0, 90.0001), (0, -91), (180.5, 0), (-200, 0), (None, 0), (0, None), ("x", 0)])
def test_invalid_coordinates_dropped(lon, lat):
    res = clean_events(frame([{"id": "bad", "lon": lon, "lat": lat}, {"id": "ok"}]))
    assert list(res.events["id"]) == ["ok"]
    assert res.dropped["invalid_coordinates"] == 1


@pytest.mark.parametrize("lon,lat", [(180, 0), (-180, 0), (0, 90), (0, -90)])
def test_boundary_coordinates_kept(lon, lat):
    assert len(clean_events(frame([{"id": "edge", "lon": lon, "lat": lat}])).events) == 1


def test_duplicate_ids_keep_most_recently_updated():
    res = clean_events(frame([
        {"id": "q", "mag": 5.1, "updated": 100},
        {"id": "q", "mag": 6.3, "updated": 200},   # newer revision wins
        {"id": "q", "mag": 5.0, "updated": 50},
    ]))
    assert len(res.events) == 1 and res.events.iloc[0]["mag"] == 6.3
    assert res.dropped["duplicate_id"] == 2


def test_rows_without_id_are_not_deduplicated():
    res = clean_events(frame([{"id": None, "lon": 1}, {"id": None, "lon": 2}]))
    assert len(res.events) == 2


def test_min_magnitude_is_inclusive():
    res = clean_events(frame([{"id": "a", "mag": 5.0}, {"id": "b", "mag": 4.99}]), min_mag=5.0)
    assert list(res.events["id"]) == ["a"]
    assert res.dropped["below_min_magnitude"] == 1


def test_output_is_point_geodataframe_with_utc_times():
    ev = clean_events(frame([{"id": "a", "lon": 12.5, "lat": -3.0, "time": 1_700_000_000_000}])).events
    assert ev.geometry.iloc[0].x == 12.5 and ev.geometry.iloc[0].y == -3.0
    assert str(ev["time"].dt.tz) == "UTC"


def test_fixture_drop_report_matches_synthetic_cases(events_path):
    """The fixture has known synthetic bad rows (see tests/fixtures/README.md)."""
    res = clean_events(load_events(events_path), min_mag=5.0)
    assert res.dropped["null_magnitude"] == 2        # null + "big"
    assert res.dropped["invalid_coordinates"] == 3   # lat 95, lon 200, no geometry
    assert res.dropped["duplicate_id"] == 1
    assert res.rows_in - sum(res.dropped.values()) == len(res.events)
    assert (res.events["mag"] >= 5.0).all()
