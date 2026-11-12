import numpy as np
import pandas as pd
import geopandas as gpd
import pytest
from shapely.geometry import Point

from pipeline.clean import clean_events, CleanResult

# Epoch milliseconds for a fixed, known instant (2020-01-01T00:00:00Z)
T0_MS = 1577836800000
T1_MS = T0_MS + 3600 * 1000  # one hour later


def _base_row(**overrides):
    """Build one valid input row (as produced by ingest.parse_usgs_geojson)."""
    row = {
        "id": "us1000abcd",
        "mag": 5.0,
        "place": "Somewhere",
        "time": T0_MS,
        "updated": T0_MS,
        "lon": 10.0,
        "lat": 20.0,
        "depth_km": 10.0,
        "event_type": "earthquake",
    }
    row.update(overrides)
    return row


def _frame(rows):
    """Build the input DataFrame with the expected column order."""
    columns = [
        "id", "mag", "place", "time", "updated",
        "lon", "lat", "depth_km", "event_type",
    ]
    return pd.DataFrame(rows, columns=columns)


def _valid_frame(n=3):
    """Return a DataFrame with n distinct valid events."""
    return _frame([_base_row(id=f"ev{n:04d}", lon=float(10 + n), lat=float(20 + n)) for n in range(n)])


# ---------------------------------------------------------------------------
# Return type / structure
# ---------------------------------------------------------------------------

def test_clean_events_returns_cleanresult_with_all_dropped_keys():
    """CleanResult exposes events, rows_in and all five dropped-rule keys."""
    result = clean_events(_valid_frame(3))
    assert isinstance(result, CleanResult)
    assert set(result.dropped.keys()) == {
        "null_magnitude",
        "invalid_coordinates",
        "duplicate_id",
        "non_earthquake",
        "below_min_magnitude",
    }
    assert result.rows_in == 3
    assert len(result.events) == 3


def test_clean_events_empty_input_returns_empty_geodataframe():
    """Empty input yields zero rows, rows_in == 0 and zero counts everywhere."""
    result = clean_events(_frame([]))
    assert result.rows_in == 0
    assert len(result.events) == 0
    assert all(v == 0 for v in result.dropped.values())
    assert isinstance(result.events, gpd.GeoDataFrame)


def test_clean_events_output_geometry_and_crs():
    """Output is EPSG:4326 with Point geometries matching input lon/lat, columns preserved."""
    result = clean_events(_frame([_base_row(lon=12.5, lat=-33.25)]))
    events = result.events
    assert events.crs is not None
    assert events.crs.to_epsg() == 4326
    assert "geometry" in events.columns
    geom = events.geometry.iloc[0]
    assert isinstance(geom, Point)
    assert geom.x == pytest.approx(12.5)
    assert geom.y == pytest.approx(-33.25)
    # Input columns preserved (plus geometry)
    for col in ["id", "mag", "place", "time", "updated", "lon", "lat", "depth_km", "event_type"]:
        assert col in events.columns


def test_clean_events_time_converted_to_utc():
    """'time' and 'updated' epoch-ms columns become UTC datetimes."""
    result = clean_events(_frame([_base_row(time=T0_MS, updated=T1_MS)]))
    row = result.events.iloc[0]
    time_val = pd.Timestamp(row["time"])
    updated_val = pd.Timestamp(row["updated"])
    # 1577836800000 ms == 2020-01-01T00:00:00Z
    assert time_val.tz is not None
    assert time_val.tz_convert("UTC") == pd.Timestamp("2020-01-01T00:00:00Z")
    assert updated_val.tz_convert("UTC") == pd.Timestamp("2020-01-01T01:00:00Z")


# ---------------------------------------------------------------------------
# Rule 1: null_magnitude
# ---------------------------------------------------------------------------

def test_clean_events_null_magnitude_dropped():
    """Rows with missing or non-numeric magnitude are counted under null_magnitude."""
    df = _frame([
        _base_row(id="ok", mag=5.0),
        _base_row(id="nan", mag=np.nan),
        _base_row(id="none", mag=None),
        _base_row(id="str", mag="not-a-number"),
    ])
    result = clean_events(df)
    assert result.dropped["null_magnitude"] == 3
    assert len(result.events) == 1
    assert result.events["id"].tolist() == ["ok"]


# ---------------------------------------------------------------------------
# Rule 2: invalid_coordinates
# ---------------------------------------------------------------------------

def test_clean_events_invalid_coordinates_dropped():
    """Out-of-range, missing and non-numeric lon/lat are dropped, not fixed."""
    df = _frame([
        _base_row(id="ok", lon=0.0, lat=0.0),
        _base_row(id="lon200", lon=200.0, lat=10.0),
        _base_row(id="lat91", lon=10.0, lat=91.0),
        _base_row(id="lat-91", lon=10.0, lat=-91.0),
        _base_row(id="lon_nan", lon=np.nan, lat=10.0),
        _base_row(id="lat_none", lon=10.0, lat=None),
        _base_row(id="lon_str", lon="east", lat=10.0),
    ])
    result = clean_events(df)
    assert result.dropped["invalid_coordinates"] == 6
    assert result.events["id"].tolist() == ["ok"]


# ---------------------------------------------------------------------------
# Rule 3: duplicate_id
# ---------------------------------------------------------------------------

def test_clean_events_duplicate_id_keeps_most_recent_update():
    """Duplicate ids collapse to the row with the latest 'updated' value."""
    df = _frame([
        _base_row(id="dup", updated=T0_MS, mag=5.0, place="old"),
        _base_row(id="dup", updated=T1_MS, mag=6.0, place="new"),
        _base_row(id="other", updated=T0_MS, mag=5.0),
    ])
    result = clean_events(df)
    assert result.dropped["duplicate_id"] == 1
    assert len(result.events) == 2
    kept = result.events[result.events["id"] == "dup"].iloc[0]
    assert kept["place"] == "new"
    assert kept["mag"] == pytest.approx(6.0)


def test_clean_events_three_duplicates_counts_each_extra_row():
    """Three rows sharing an id remove two rows and keep the newest."""
    df = _frame([
        _base_row(id="dup", updated=T0_MS, place="a"),
        _base_row(id="dup", updated=T1_MS, place="c"),
        _base_row(id="dup", updated=T0_MS - 1000, place="b"),
    ])
    result = clean_events(df)
    assert result.dropped["duplicate_id"] == 2
    assert len(result.events) == 1
    assert result.events.iloc[0]["place"] == "c"


# ---------------------------------------------------------------------------
# Rule 4: non_earthquake
# ---------------------------------------------------------------------------

def test_clean_events_non_earthquake_dropped_but_missing_type_kept():
    """Explicit non-'earthquake' types are dropped; missing type is kept."""
    df = _frame([
        _base_row(id="eq", event_type="earthquake"),
        _base_row(id="ls", event_type="landslide", mag=5.2),
        _base_row(id="ex", event_type="explosion"),
        _base_row(id="none", event_type=None),
        _base_row(id="nan", event_type=np.nan),
    ])
    result = clean_events(df)
    assert result.dropped["non_earthquake"] == 2
    assert set(result.events["id"]) == {"eq", "none", "nan"}


# ---------------------------------------------------------------------------
# Rule 5: below_min_magnitude (boundary inclusive)
# ---------------------------------------------------------------------------

def test_clean_events_magnitude_boundary_is_inclusive():
    """mag exactly equal to min_mag is kept; just below is dropped."""
    df = _frame([
        _base_row(id="below", mag=4.49),
        _base_row(id="at", mag=4.5),
        _base_row(id="above", mag=4.51),
    ])
    result = clean_events(df, min_mag=4.5)
    assert result.dropped["below_min_magnitude"] == 1
    assert set(result.events["id"]) == {"at", "above"}


def test_clean_events_default_min_mag_applied():
    """Default min_mag filters out magnitudes below the DEFAULT_MIN_MAG constant."""
    # Use two events, one clearly below and one at a typical default (4.5 or less).
    from pipeline.clean import DEFAULT_MIN_MAG
    below = DEFAULT_MIN_MAG - 0.1
    at = DEFAULT_MIN_MAG
    df = _frame([
        _base_row(id="below", mag=below),
        _base_row(id="at", mag=at),
    ])
    result = clean_events(df)
    assert result.dropped["below_min_magnitude"] == 1
    assert result.events["id"].tolist() == ["at"]


# ---------------------------------------------------------------------------
# Rule ordering
# ---------------------------------------------------------------------------

def test_clean_events_rules_are_attributed_in_order():
    """A row failing an earlier rule is counted only under that earlier rule."""
    df = _frame([
        # null magnitude and non-earthquake: counts under null_magnitude
        _base_row(id="null_mag", mag=np.nan, event_type="landslide"),
        # bad coordinates and non-earthquake: counts under invalid_coordinates
        _base_row(id="bad_coord", lon=500.0, event_type="explosion"),
    ])
    result = clean_events(df)
    assert result.dropped["null_magnitude"] == 1
    assert result.dropped["invalid_coordinates"] == 1
    assert result.dropped["non_earthquake"] == 0
    assert result.dropped["below_min_magnitude"] == 0
    assert len(result.events) == 0


def test_clean_events_no_drops_when_all_valid():
    """A fully valid input produces no drops and preserves all rows."""
    df = _valid_frame(4)
    result = clean_events(df)
    assert all(v == 0 for v in result.dropped.values())
    assert len(result.events) == 4
    assert result.rows_in == 4


# ---------------------------------------------------------------------------
# Coordinates preserved faithfully
# ---------------------------------------------------------------------------

def test_clean_events_geodetic_point_preserved():
    """Points constructed via pyproj.Geod.fwd round-trip to the expected lon/lat."""
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    start_lon, start_lat = 0.0, 0.0
    azimuth, distance_m = 45.0, 100_000.0
    end_lon, end_lat, _ = geod.fwd(start_lon, start_lat, azimuth, distance_m)

    result = clean_events(_frame([_base_row(lon=end_lon, lat=end_lat)]))
    geom = result.events.geometry.iloc[0]
    assert geom.x == pytest.approx(end_lon, abs=1e-9)
    assert geom.y == pytest.approx(end_lat, abs=1e-9)
    # Distance from origin matches by construction
    inv_az, _, inv_dist = geod.inv(start_lon, start_lat, geom.x, geom.y)
    assert inv_dist == pytest.approx(distance_m, rel=1e-6)
