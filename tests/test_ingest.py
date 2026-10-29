from pipeline.ingest import EVENT_COLUMNS, load_cities, load_events, parse_usgs_geojson


def test_fixture_loads_all_rows(events_path):
    df = load_events(events_path)
    assert len(df) == 100
    assert list(df.columns) == EVENT_COLUMNS


def test_empty_feature_collection():
    df = parse_usgs_geojson({"type": "FeatureCollection", "features": []})
    assert df.empty and list(df.columns) == EVENT_COLUMNS


def test_missing_features_key_is_empty_not_error():
    assert parse_usgs_geojson({}).empty


def test_null_geometry_and_missing_props_become_nan():
    df = parse_usgs_geojson({"features": [{"id": "x", "geometry": None, "properties": None}]})
    row = df.iloc[0]
    assert row["id"] == "x" and row["lon"] is None and row["mag"] is None


def test_load_cities_fixture(cities_path):
    cities = load_cities(cities_path)
    assert len(cities) == 200
    assert cities.crs.to_epsg() == 4326
    assert (cities.geometry.geom_type == "Point").all()
    assert "Labasa (Fiji)" in set(cities["label"])
