```python
import math

import numpy as np
import pytest
from pyproj import Geod

from pipeline.geo import N_VERTICES, geodesic_buffer, geodesic_distance_m

GEOD = Geod(ellps="WGS84")


def _fwd(lon, lat, azimuth, distance_m):
    """Return (lon, lat) reached from (lon, lat) by travelling distance_m along the ellipsoid."""
    out_lon, out_lat, _ = GEOD.fwd(lon, lat, azimuth, distance_m)
    return out_lon, out_lat


def test_geodesic_distance_m_scalar_zero_for_same_point():
    """Distance between a point and itself is exactly zero."""
    d = geodesic_distance_m(12.5, 41.9, 12.5, 41.9)
    assert float(np.asarray(d)) == pytest.approx(0.0, abs=1e-6)


def test_geodesic_distance_m_matches_fwd_construction():
    """Distance matches the radius used to construct the second point with Geod.fwd."""
    lon1, lat1 = 10.0, 45.0
    target_dist = 50_000.0
    lon2, lat2 = _fwd(lon1, lat1, 45.0, target_dist)
    d = geodesic_distance_m(lon1, lat1, lon2, lat2)
    assert float(np.asarray(d)) == pytest.approx(target_dist, rel=1e-6)


def test_geodesic_distance_m_symmetric():
    """Distance is symmetric in its endpoints."""
    lon1, lat1, lon2, lat2 = -3.2, 51.5, 7.1, 43.7
    d_ab = float(np.asarray(geodesic_distance_m(lon1, lat1, lon2, lat2)))
    d_ba = float(np.asarray(geodesic_distance_m(lon2, lat2, lon1, lat1)))
    assert d_ab == pytest.approx(d_ba, rel=1e-9)


def test_geodesic_distance_m_accepts_arrays():
    """Array inputs produce an array of elementwise distances of the right shape."""
    lons1 = np.array([0.0, 1.0, 2.0])
    lats1 = np.array([0.0, 0.0, 0.0])
    lons2 = np.array([0.0, 2.0, 4.0])
    lats2 = np.array([1.0, 0.0, 0.0])
    out = geodesic_distance_m(lons1, lats1, lons2, lats2)
    out = np.asarray(out)
    assert out.shape == (3,)
    expected = [
        float(np.asarray(geodesic_distance_m(lons1[i], lats1[i], lons2[i], lats2[i])))
        for i in range(3)
    ]
    np.testing.assert_allclose(out, expected, rtol=1e-9)
    # element 1 is (1,0)->(2,0), strictly positive
    assert out[1] > 0


def test_geodesic_distance_m_broadcasts_scalar_against_array():
    """A scalar endpoint broadcasts against an array endpoint."""
    lons2 = np.array([0.0, 1.0, 2.0])
    lats2 = np.zeros(3)
    out = np.asarray(geodesic_distance_m(0.0, 0.0, lons2, lats2))
    assert out.shape == (3,)
    expected = [float(np.asarray(geodesic_distance_m(0.0, 0.0, lo, 0.0))) for lo in lons2]
    np.testing.assert_allclose(out, expected, rtol=1e-9)


def test_geodesic_distance_m_empty_array_input():
    """Empty array inputs yield an empty result rather than raising."""
    empty = np.array([])
    out = np.asarray(geodesic_distance_m(empty, empty, empty, empty))
    assert out.shape == (0,)


def test_geodesic_buffer_returns_polygon_with_default_vertex_count():
    """Default buffer is a polygon with N_VERTICES coordinates (plus closing point)."""
    from shapely.geometry import Polygon

    poly = geodesic_buffer(10.0, 45.0, 10_000.0)
    assert isinstance(poly, Polygon)
    coords = list(poly.exterior.coords)
    # closed ring: N_VERTICES distinct vertices plus a repeated first vertex
    assert len(coords) == N_VERTICES + 1
    assert coords[0] == coords[-1]


def test_geodesic_buffer_custom_n_vertices():
    """A custom n_vertices controls the number of ring coordinates."""
    from shapely.geometry import Polygon

    poly = geodesic_buffer(0.0, 0.0, 5_000.0, n_vertices=16)
    assert isinstance(poly, Polygon)
    coords = list(poly.exterior.coords)
    assert len(coords) == 17


def test_geodesic_buffer_vertices_are_radius_away():
    """Every returned ring vertex is radius_m from the centre along the ellipsoid."""
    lon, lat, radius = 20.0, 30.0, 25_000.0
    poly = geodesic_buffer(lon, lat, radius)
    for vx, vy in list(poly.exterior.coords)[:-1]:
        d = float(np.asarray(geodesic_distance_m(lon, lat, vx, vy)))
        assert d == pytest.approx(radius, rel=1e-6)


def test_geodesic_buffer_coordinates_within_bounds():
    """Every returned coordinate lies within lon [-180, 180] and lat [-90, 90]."""
    poly = geodesic_buffer(179.5, 10.0, 100_000.0)
    geoms = poly.geoms if hasattr(poly, "geoms") else [poly]
    for geom in geoms:
        for vx, vy in geom.exterior.coords:
            assert -180.0 <= vx <= 180.0
            assert -90.0 <= vy <= 90.0


def test_geodesic_buffer_crossing_antimeridian_is_multipolygon():
    """A buffer straddling +/-180 is returned as a MultiPolygon."""
    from shapely.geometry import MultiPolygon

    poly = geodesic_buffer(179.99, 0.0, 100_000.0)
    assert isinstance(poly, MultiPolygon)
    assert len(poly.geoms) >= 2


def test_geodesic_buffer_zero_radius_raises():
    """radius_m == 0 raises ValueError (limit is exclusive)."""
    with pytest.raises(ValueError):
        geodesic_buffer(0.0, 0.0, 0.0)


def test_geodesic_buffer_negative_radius_raises():
    """Negative radius_m raises ValueError."""
    with pytest.raises(ValueError):
        geodesic_buffer(0.0, 0.0, -1.0)


def test_geodesic_buffer_containing_pole_raises():
    """A buffer whose radius reaches a pole raises ValueError."""
    # 89.9 N, radius well over the ~11 km to the pole along the meridian
    with pytest.raises(ValueError):
        geodesic_buffer(0.0, 89.9, 50_000.0)


def test_geodesic_buffer_near_pole_but_not_containing_pole_ok():
    """A buffer that stops short of the pole does not raise."""
    # ~11 km to the pole; 1 km radius stays clear
    poly = geodesic_buffer(0.0, 89.9, 1_000.0)
    assert poly.is_valid
```