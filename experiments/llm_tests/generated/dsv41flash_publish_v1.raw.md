```python
import json
import math
from pathlib import Path

import pytest

from pipeline.publish import PublishError, validate_geojson


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _feature(fid, lon, lat, **overrides):
    """Build a minimal valid Point feature; overrides patch properties."""
    props = {
        "id": fid,
        "mag": 5.0,
        "place": "Somewhere",
        "time": 1700000000000,
        "city_count": 1,
        "city_names": "Somecity",
        "nearest_city": "Somecity",
        "nearest_km": 1.0,
    }
    props.update(overrides)
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


def _collection(features):
    return {"type": "FeatureCollection", "features": features}


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _valid_feature():
    return _feature("a", -122.0, 37.0)


# ---------------------------------------------------------------------------
# normal / report
# ---------------------------------------------------------------------------

def test_validate_geojson_returns_report_for_valid_file(tmp_path):
    """Report contains path, bytes, features, sorted fields and bbox."""
    fc = _collection([_feature("a", -122.0, 37.0), _feature("b", -121.0, 38.0)])
    p = _write(tmp_path, "ok.geojson", fc)

    report = validate_geojson(p)

    assert set(report) == {"path", "bytes", "features", "fields", "bbox"}
    assert Path(report["path"]) == p
    assert report["bytes"] == p.stat().st_size
    assert report["features"] == 2
    assert report["fields"] == sorted(
        ["id", "mag", "place", "time", "city_count", "city_names",
         "nearest_city", "nearest_km"]
    )
    assert report["bbox"] == [-122.0, 37.0, -121.0, 38.0]


def test_validate_geojson_accepts_str_path(tmp_path):
    """A plain string path works like a Path."""
    p = _write(tmp_path, "ok.geojson", _collection([_valid_feature()]))
    report = validate_geojson(str(p))
    assert report["features"] == 1


def test_validate_geojson_bbox_covers_single_point(tmp_path):
    """A single point yields a degenerate bbox equal to that point."""
    p = _write(tmp_path, "one.geojson", _collection([_feature("a", 10.0, 20.0)]))
    report = validate_geojson(p)
    assert report["bbox"] == [10.0, 20.0, 10.0, 20.0]


def test_validate_geojson_fields_are_sorted(tmp_path):
    """Fields list is sorted regardless of property insertion order."""
    p = _write(tmp_path, "ok.geojson", _collection([_valid_feature()]))
    report = validate_geojson(p)
    assert report["fields"] == sorted(report["fields"])


# ---------------------------------------------------------------------------
# boundaries
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "lon,lat",
    [(-180.0, -90.0), (180.0, 90.0), (0.0, 0.0), (-180.0, 90.0), (180.0, -90.0)],
)
def test_validate_geojson_accepts_coordinate_boundaries(tmp_path, lon, lat):
    """Lon +/-180 and lat +/-90 are inclusive."""
    p = _write(tmp_path, "b.geojson", _collection([_feature("a", lon, lat)]))
    report = validate_geojson(p)
    assert report["features"] == 1


@pytest.mark.parametrize(
    "lon,lat",
    [(180.0001, 0.0), (-180.0001, 0.0), (0.0, 90.0001), (0.0, -90.0001)],
)
def test_validate_geojson_rejects_out_of_range_coordinates(tmp_path, lon, lat):
    """Coordinates just outside the inclusive bounds raise PublishError."""
    p = _write(tmp_path, "bad.geojson", _collection([_feature("a", lon, lat)]))
    with pytest.raises(PublishError):
        validate_geojson(p)


def test_validate_geojson_rejects_non_finite_coordinates(tmp_path):
    """NaN / infinity coordinates are rejected (JSON allows NaN via Python)."""
    fc = _collection([_feature("a", 0.0, 0.0)])
    fc["features"][0]["geometry"]["coordinates"] = [float("nan"), 0.0]
    p = tmp_path / "nan.geojson"
    p.write_text(json.dumps(fc), encoding="utf-8")  # json emits NaN
    with pytest.raises(PublishError):
        validate_geojson(p)


# ---------------------------------------------------------------------------
# empty / missing / structural
# ---------------------------------------------------------------------------

def test_validate_geojson_missing_file_raises(tmp_path):
    """A nonexistent path raises PublishError."""
    with pytest.raises(PublishError):
        validate_geojson(tmp_path / "nope.geojson")


def test_validate_geojson_invalid_json_raises(tmp_path):
    """Malformed JSON raises PublishError."""
    p = tmp_path / "broken.geojson"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(PublishError):
        validate_geojson(p)


def test_validate_geojson_wrong_top_level_type_raises(tmp_path):
    """A Feature (not FeatureCollection) at top level raises PublishError."""
    p = _write(tmp_path, "f.geojson", _feature("a", 0.0, 0.0))
    with pytest.raises(PublishError):
        validate_geojson(p)


def test_validate_geojson_empty_features_raises(tmp_path):
    """A FeatureCollection with zero features raises PublishError."""
    p = _write(tmp_path, "empty.geojson", _collection([]))
    with pytest.raises(PublishError):
        validate_geojson(p)


# ---------------------------------------------------------------------------
# geometry / property checks
# ---------------------------------------------------------------------------

def test_validate_geojson_rejects_non_point_geometry(tmp_path):
    """A LineString geometry raises PublishError."""
    fc = _collection([_valid_feature()])
    fc["features"][0]["geometry"] = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
    p = _write(tmp_path, "line.geojson", fc)
    with pytest.raises(PublishError):
        validate_geojson(p)


def test_validate_geojson_rejects_missing_required_property(tmp_path):
    """Dropping a required property raises PublishError."""
    fc = _collection([_valid_feature()])
    del fc["features"][0]["properties"]["nearest_km"]
    p = _write(tmp_path, "missing.geojson", fc)
    with pytest.raises(PublishError):
        validate_geojson(p)


def test_validate_geojson_rejects_list_property_value(tmp_path):
    """A list-valued property raises PublishError."""
    p = _write(
        tmp_path, "list.geojson",
        _collection([_feature("a", 0.0, 0.0, city_names=["X", "Y"])]),
    )
    with pytest.raises(PublishError):
        validate_geojson(p)


def test_validate_geojson_rejects_dict_property_value(tmp_path):
    """A dict-valued property raises PublishError."""
    p = _write(
        tmp_path, "dict.geojson",
        _collection([_feature("a", 0.0, 0.0, place={"name": "x"})]),
    )
    with pytest.raises(PublishError):
        validate_geojson(p)


@pytest.mark.parametrize("bad_name", ["1id", "has space", "has-dash", "_leading"])
def test_validate_geojson_rejects_invalid_field_name(tmp_path, bad_name):
    """Field names must start with a letter and use only [A-Za-z0-9_]."""
    fc = _collection([_valid_feature()])
    fc["features"][0]["properties"][bad_name] = "v"
    p = _write(tmp_path, "f.geojson", fc)
    with pytest.raises(PublishError):
        validate_geojson(p)


# ---------------------------------------------------------------------------
# "list every problem" behaviour
# ---------------------------------------------------------------------------

def test_validate_geojson_reports_all_problems_in_message(tmp_path):
    """Message lists multiple distinct problems, not just the first."""
    fc = _collection([_valid_feature(), _valid_feature()])
    fc["features"][0]["geometry"]["coordinates"] = [999.0, 0.0]
    fc["features"][1]["properties"]["mag"] = [1.0]
    p = _write(tmp_path, "multi.geojson", fc)

    with pytest.raises(PublishError) as excinfo:
        validate_geojson(p)

    msg = str(excinfo.value).lower()
    # at least two independent problems referenced
    assert "mag" in msg or "list" in msg
    assert "coordinate" in msg or "lon" in msg or "range" in msg


def test_validate_geojson_error_message_has_no_credential_values(tmp_path):
    """PublishError message never echoes property values (credentials)."""
    secret = "SUPER_SECRET_TOKEN_VALUE"
    fc = _collection([_valid_feature()])
    fc["features"][0]["properties"]["place"] = secret
    fc["features"][0]["properties"]["city_names"] = [secret]  # invalid type
    p = _write(tmp_path, "secret.geojson", fc)

    with pytest.raises(PublishError) as excinfo:
        validate_geojson(p)

    assert secret not in str(excinfo.value)
```