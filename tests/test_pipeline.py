"""End-to-end (offline): run the CLI on the committed fixtures and check the output
against an independent brute-force oracle (every event x every city)."""
import json

import numpy as np
import pytest

from pipeline.geo import geodesic_distance_m
from pipeline.ingest import load_cities
from pipeline.run import main, run


@pytest.fixture
def result(tmp_path, events_path, cities_path):
    out = tmp_path / "out.geojson"
    summary = run(events_path, cities_path, out, radius_km=100, min_mag=5.0)
    return summary, json.loads(out.read_text())


def test_output_is_valid_geojson_points(result):
    _, gj = result
    assert gj["type"] == "FeatureCollection" and gj["features"]
    for f in gj["features"]:
        assert f["geometry"]["type"] == "Point"
        assert {"id", "mag", "city_count", "city_names"} <= f["properties"].keys()
        assert f["properties"]["mag"] >= 5.0


def test_matches_brute_force_oracle(result, cities_path):
    _, gj = result
    cities = load_cities(cities_path)
    cx, cy = cities.geometry.x.to_numpy(), cities.geometry.y.to_numpy()
    for f in gj["features"]:
        lon, lat = f["geometry"]["coordinates"]
        d_km = geodesic_distance_m(np.full(cx.size, lon), np.full(cy.size, lat), cx, cy) / 1000
        expected = sorted(cities["name"][d_km <= 100])
        got = sorted(n for n in f["properties"]["city_names"].split("; ") if n)
        assert got == expected, f["properties"]["id"]
        assert f["properties"]["city_count"] == len(expected)


def test_synthetic_edge_cases_end_to_end(result, events_path):
    _, gj = result
    by_id = {f["properties"]["id"]: f["properties"] for f in gj["features"]}
    assert "Labasa" in by_id["synthetic_antimeridian"]["city_names"]
    assert by_id["synthetic_open_ocean"]["city_count"] == 0
    for bad in ("synthetic_null_mag", "synthetic_bad_lat", "synthetic_bad_lon",
                "synthetic_no_geometry", "synthetic_string_mag"):
        assert bad not in by_id
    assert len(by_id) == len(gj["features"])           # no duplicate ids in output
    assert all(p["mag"] != 1.0 for p in by_id.values())  # stale duplicate (mag 1.0) dropped


def test_summary_numbers_are_consistent(result):
    s, gj = result
    assert s["events_kept"] == len(gj["features"])
    assert s["events_in"] - sum(s["dropped"].values()) == s["events_kept"]
    assert s["event_city_pairs"] == sum(f["properties"]["city_count"] for f in gj["features"])


def test_cli_prints_json_summary(tmp_path, events_path, cities_path, capsys):
    main(["--events", str(events_path), "--cities", str(cities_path), "--out", str(tmp_path / "o.geojson")])
    assert json.loads(capsys.readouterr().out)["events_kept"] > 0
