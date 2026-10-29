"""Contract tests: does the PUBLISHED Feature Service behave the way consumers expect?

Unit tests check our code; these check a live service we don't control byte-for-byte.
They are SKIPPED unless FEATURE_SERVICE_URL is set, so `pytest` stays offline by default.

Environment variables:
  FEATURE_SERVICE_URL       layer URL, e.g. https://services.arcgis.com/<org>/arcgis/rest/services/drqa_m5_cities/FeatureServer/0
  ARCGIS_TOKEN              optional, for a layer that isn't shared publicly (never printed)
  CONTRACT_EXPECTED_FIELDS  optional comma list (default: our output schema)
  CONTRACT_MAX_SECONDS      optional response-time budget per query (default 5)
  CONTRACT_LOCAL_GEOJSON    optional path to the GeoJSON you published; enables count-match tests

Gotcha found while writing these: ArcGIS REST returns errors as HTTP 200 with an
{"error": ...} JSON body, so checking the status code alone is NOT enough.
"""
import json
import os
import statistics
import time
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.contract

URL = os.environ.get("FEATURE_SERVICE_URL", "").rstrip("/")
if not URL:
    pytest.skip("FEATURE_SERVICE_URL not set; skipping live contract tests", allow_module_level=True)

TOKEN = os.environ.get("ARCGIS_TOKEN")
EXPECTED_FIELDS = [f.strip() for f in os.environ.get(
    "CONTRACT_EXPECTED_FIELDS",
    "id,mag,place,time,city_count,city_names,nearest_city,nearest_km").split(",") if f.strip()]
MAX_SECONDS = float(os.environ.get("CONTRACT_MAX_SECONDS", "5"))
LOCAL = os.environ.get("CONTRACT_LOCAL_GEOJSON")


def rest(path="", **params):
    """GET <layer>/<path>?f=json&...; returns (json, seconds). Fails on HTTP *or* body errors."""
    params = {"f": "json", **params}
    if TOKEN:
        params["token"] = TOKEN
    t0 = time.perf_counter()
    r = requests.get(f"{URL}/{path}" if path else URL, params=params, timeout=30)
    elapsed = time.perf_counter() - t0
    r.raise_for_status()
    return r.json(), elapsed


def ok(body):
    assert "error" not in body, f"service returned an error payload: {body['error']}"
    return body


@pytest.fixture(scope="module")
def layer():
    return ok(rest()[0])


def test_layer_is_a_point_feature_layer(layer):
    assert layer.get("type") == "Feature Layer"
    assert layer.get("geometryType") == "esriGeometryPoint"


def test_expected_fields_present(layer):
    names = {f["name"].lower() for f in layer["fields"]}
    missing = [f for f in EXPECTED_FIELDS if f.lower() not in names]
    assert not missing, f"fields missing from service: {missing}; service has {sorted(names)}"


def test_record_count_positive():
    body = ok(rest("query", where="1=1", returnCountOnly="true")[0])
    assert body["count"] > 0


def test_response_time_under_budget():
    """Median of 3 count queries, to avoid failing on one slow network blip."""
    times = [rest("query", where="1=1", returnCountOnly="true")[1] for _ in range(3)]
    assert statistics.median(times) < MAX_SECONDS, f"query times {times}"


def test_invalid_query_is_reported_as_error_payload():
    """Pins the 'HTTP 200 + error body' behaviour that rest()/ok() rely on."""
    body, _ = rest("query", where="no_such_field_xyz=1", returnCountOnly="true")
    assert "error" in body


def test_geometry_can_be_returned_in_wgs84():
    """Hosted layers are usually stored in Web Mercator (wkid 102100/3857); asking for
    outSR=4326 must still give valid lon/lat."""
    body = ok(rest("query", where="1=1", outFields="*", returnGeometry="true",
                   outSR="4326", resultRecordCount="5")[0])
    assert body["features"]
    for f in body["features"]:
        x, y = f["geometry"]["x"], f["geometry"]["y"]
        assert -180 <= x <= 180 and -90 <= y <= 90


@pytest.mark.skipif(not LOCAL, reason="CONTRACT_LOCAL_GEOJSON not set")
def test_counts_match_local_output():
    feats = json.loads(Path(LOCAL).read_text())["features"]
    total = ok(rest("query", where="1=1", returnCountOnly="true")[0])["count"]
    with_city = ok(rest("query", where="city_count > 0", returnCountOnly="true")[0])["count"]
    assert total == len(feats)
    assert with_city == sum(1 for f in feats if f["properties"]["city_count"] > 0)


@pytest.mark.skipif(not LOCAL, reason="CONTRACT_LOCAL_GEOJSON not set")
def test_longest_city_names_not_truncated():
    """Our longest city_names is 307 chars (1-year M5+ run). If publishing gave the field
    a shorter default length, the service would hold a truncated string. Unknown until
    run against a real publish -- that's exactly what this test is for."""
    feats = json.loads(Path(LOCAL).read_text())["features"]
    longest = max(feats, key=lambda f: len(f["properties"]["city_names"]))["properties"]
    eid = longest["id"].replace("'", "''")
    body = ok(rest("query", where=f"id = '{eid}'", outFields="city_names", returnGeometry="false")[0])
    assert len(body["features"]) == 1
    assert body["features"][0]["attributes"]["city_names"] == longest["city_names"]
