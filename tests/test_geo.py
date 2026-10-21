import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon

from pipeline.geo import (GEOD, N_VERTICES, geodesic_buffer, geodesic_distance_m,
                          prefilter_radius_m)
from tests.conftest import offset

R = 100_000.0  # 100 km


def test_known_distance_one_degree_of_latitude_at_equator():
    # WGS84 meridian arc from 0 to 1 deg N is 110,574 m (standard geodesy value);
    # a sphere model would say ~111,195 m.
    assert geodesic_distance_m(0, 0, 0, 1) == pytest.approx(110_574, abs=1)


@pytest.mark.parametrize("lat", [0, 35, 60, 75, -45, -70])
def test_buffer_vertices_are_exactly_radius_away(lat):
    poly = geodesic_buffer(20.0, lat, R)
    xs, ys = np.array(poly.exterior.coords).T[:, :-1]
    d = geodesic_distance_m(np.full(len(xs), 20.0), np.full(len(ys), lat), xs, ys)
    assert len(xs) == N_VERTICES
    assert np.allclose(d, R, atol=1.0)  # within 1 metre


def test_buffer_is_not_a_circle_in_degrees_at_high_latitude():
    # At 60 deg N a longitude degree is ~half as long as at the equator, so a true
    # 100 km circle spans ~2x as many degrees east-west as north-south.
    minx, miny, maxx, maxy = geodesic_buffer(0.0, 60.0, R).bounds
    assert (maxx - minx) / (maxy - miny) == pytest.approx(2.0, rel=0.05)


@pytest.mark.parametrize("km,inside", [(99.0, True), (101.0, False)])
def test_buffer_contains_99km_but_not_101km(km, inside):
    poly = geodesic_buffer(-118.24, 34.05, R)
    for az in (0, 45, 90, 180, 270):
        assert poly.contains(Point(offset(-118.24, 34.05, az, km))) is inside


@pytest.mark.parametrize("center_lon", [179.5, -179.5, 180.0, -180.0])
def test_antimeridian_buffer_is_split_and_valid(center_lon):
    geom = geodesic_buffer(center_lon, -17.0, R)
    assert isinstance(geom, MultiPolygon) and geom.is_valid
    minx, _, maxx, _ = geom.bounds
    assert minx >= -180 and maxx <= 180
    # it must not become a band wrapping the whole globe
    assert not geom.contains(Point(0, -17))
    # both sides of the line are covered
    assert geom.contains(Point(179.8, -17.0)) and geom.contains(Point(-179.8, -17.0))


def test_antimeridian_split_loses_no_area():
    """Cutting at 180 deg must not lose any piece: same planar area as the identical buffer at lon 0."""
    split = geodesic_buffer(179.5, -17.0, R)
    reference = geodesic_buffer(-0.5, -17.0, R)
    assert split.area == pytest.approx(reference.area, rel=1e-6)


def test_non_crossing_buffer_is_simple_polygon():
    assert isinstance(geodesic_buffer(178.0, -17.0, R), Polygon)


def test_buffer_containing_pole_is_rejected():
    with pytest.raises(ValueError, match="pole"):
        geodesic_buffer(0.0, 89.5, R)


def test_non_positive_radius_rejected():
    with pytest.raises(ValueError):
        geodesic_buffer(0, 0, 0)


@pytest.mark.parametrize("lat", [0, 45, 70, -75])
def test_prefilter_buffer_has_no_false_negatives_at_the_edge(lat):
    """A city at 99.99 km in ANY direction must be inside the pre-filter polygon."""
    poly = geodesic_buffer(10.0, lat, prefilter_radius_m(R))
    az = np.arange(0, 360, 1.0)
    xs, ys, _ = GEOD.fwd(np.full(az.size, 10.0), np.full(az.size, lat), az, np.full(az.size, R - 10))
    assert all(poly.contains(Point(x, y)) for x, y in zip(xs, ys))
