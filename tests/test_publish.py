"""publish.py: dry-run validation (offline) + the real publish flow against FAKE arcgis objects.

The fake-GIS tests check that we call the ArcGIS API in the documented 2.4.4 shape
(folder.add(...).result() -> item.publish(...)) without any account or network.
"""
import builtins
import inspect
import json

import pytest

from pipeline import publish as pub
from pipeline.run import run

SECRET = "hunter2-not-a-real-password"


@pytest.fixture
def good_geojson(tmp_path, events_path, cities_path):
    out = tmp_path / "out.geojson"
    run(events_path, cities_path, out)
    return out


def write(tmp_path, obj):
    p = tmp_path / "x.geojson"
    p.write_text(json.dumps(obj))
    return p


def feature(**overrides):
    props = {k: 1 for k in pub.REQUIRED_FIELDS}
    f = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [10.0, 20.0]}, "properties": props}
    f.update(overrides)
    return f


def test_dry_run_passes_on_real_pipeline_output(good_geojson):
    plan = pub.dry_run(good_geojson, "t", "drqa_test", env={})
    assert plan["mode"] == "dry-run" and plan["validation"]["features"] > 0
    assert set(pub.REQUIRED_FIELDS) <= set(plan["validation"]["fields"])


def test_dry_run_never_imports_arcgis(good_geojson, monkeypatch):
    real_import = builtins.__import__

    def guard(name, *a, **k):
        if name.startswith("arcgis"):
            raise AssertionError("dry-run must not import arcgis")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", guard)
    pub.dry_run(good_geojson, "t", "drqa_test", env={})


def test_dry_run_reports_credentials_as_booleans_only(good_geojson):
    env = {"ARCGIS_URL": "https://x", "ARCGIS_USERNAME": "me", "ARCGIS_PASSWORD": SECRET}
    plan = pub.dry_run(good_geojson, "t", "drqa_test", env=env)
    assert plan["credentials_present"] == {k: True for k in pub.CREDENTIAL_VARS}
    assert SECRET not in json.dumps(plan)


def test_missing_credentials_error_names_vars_not_values():
    with pytest.raises(pub.PublishError) as e:
        pub.read_credentials({"ARCGIS_URL": "https://x", "ARCGIS_PASSWORD": SECRET})
    assert "ARCGIS_USERNAME" in str(e.value) and SECRET not in str(e.value)


@pytest.mark.parametrize("obj,msg", [
    ({"type": "FeatureCollection", "features": []}, "no features"),
    ({"type": "Feature"}, "FeatureCollection"),
    ({"type": "FeatureCollection", "features": [feature(geometry={"type": "Polygon", "coordinates": []})]}, "Point"),
    ({"type": "FeatureCollection", "features": [feature(geometry={"type": "Point", "coordinates": [200, 0]})]}, "WGS84"),
    ({"type": "FeatureCollection", "features": [feature(properties={"mag": 5})]}, "missing properties"),
    ({"type": "FeatureCollection", "features": [feature(properties={**{k: 1 for k in pub.REQUIRED_FIELDS},
                                                                    "city_names": ["a", "b"]})]}, "list/dict"),
    ({"type": "FeatureCollection", "features": [feature(properties={**{k: 1 for k in pub.REQUIRED_FIELDS},
                                                                    "2bad name": 1})]}, "invalid field names"),
])
def test_validation_rejects_bad_geojson(tmp_path, obj, msg):
    with pytest.raises(pub.PublishError, match=msg):
        pub.validate_geojson(write(tmp_path, obj))


def test_validation_rejects_missing_file_and_bad_json(tmp_path):
    with pytest.raises(pub.PublishError, match="not found"):
        pub.validate_geojson(tmp_path / "nope.geojson")
    bad = tmp_path / "bad.geojson"
    bad.write_text("{not json")
    with pytest.raises(pub.PublishError, match="not valid JSON"):
        pub.validate_geojson(bad)


@pytest.mark.parametrize("name", ["1abc", "has space", "dash-name", ""])
def test_bad_service_names_rejected(good_geojson, name):
    with pytest.raises(pub.PublishError, match="service name"):
        pub.dry_run(good_geojson, "t", name, env={})


def test_cli_dry_run_exit_codes(good_geojson, tmp_path, capsys):
    assert pub.main([str(good_geojson), "--dry-run"]) == 0
    assert pub.main([str(tmp_path / "missing.geojson"), "--dry-run"]) == 2
    assert "ERROR" in capsys.readouterr().err


# ---------- real-publish flow with fake arcgis objects (needs the arcgis package) ----------

class FakeItem:
    def __init__(self, id_, url=None):
        self.id, self.url, self.published_with = id_, url, None
        self.sharing = type("S", (), {"sharing_level": None})()

    def publish(self, publish_parameters=None, **kw):
        self.published_with = publish_parameters
        self.layer = FakeItem("layer123", "https://services.example/arcgis/rest/services/drqa_test/FeatureServer")
        return self.layer


class FakeJob:
    def __init__(self, item):
        self._item = item

    def result(self):
        return self._item


class FakeFolder:
    def __init__(self):
        self.calls = []

    def add(self, item_properties=None, file=None, **kw):
        self.calls.append((item_properties, file))
        self.item = FakeItem("geojson123")
        return FakeJob(self.item)


class FakeGIS:
    def __init__(self):
        self.folder = FakeFolder()
        self.content = type("C", (), {"folders": type("F", (), {"get": lambda _self, *a, **k: self.folder})()})()


def test_publish_flow_with_fake_gis(good_geojson):
    arcgis_gis = pytest.importorskip("arcgis.gis")
    gis = FakeGIS()
    out = pub.publish(good_geojson, "My title", "drqa_test", share_public=True, gis=gis, env={})
    (props, file), = gis.folder.calls
    assert isinstance(props, arcgis_gis.ItemProperties) and file == str(good_geojson)
    assert gis.folder.item.published_with == {"name": "drqa_test"}
    assert gis.folder.item.layer.sharing.sharing_level == arcgis_gis.SharingLevel.EVERYONE
    assert out["layer_url"].endswith("/FeatureServer/0") and out["layer_item_id"] == "layer123"


def test_our_calls_match_installed_arcgis_signatures():
    """API-drift guard: if a future arcgis release renames these parameters, this fails
    in CI instead of during a live publish."""
    pytest.importorskip("arcgis")
    from arcgis.gis import GIS, Item, ItemProperties, ItemTypeEnum
    from arcgis.gis._impl._content_manager import Folder
    inspect.signature(Folder.add).bind(None, item_properties=None, file="x.geojson")
    inspect.signature(Item.publish).bind(None, publish_parameters={"name": "x"})
    inspect.signature(GIS.__init__).bind(None, url="u", username="n", password="p")
    ItemProperties(item_type=ItemTypeEnum.GEOJSON, title="t", tags=["a"], snippet="s",
                   description="d", license_info="l")
