# Concepts (for someone with no GIS background)

The five core concepts of this project are **geodesic buffers**, **antimeridian handling**,
**spatial joins**, **Feature Layer vs Feature Service**, and **contract vs unit vs E2E tests**.
WGS84 vs Web Mercator is included because the other sections depend on it.

## Feature Service vs Feature Layer

A **feature** is one real-world thing stored as a geometry (point, line or polygon) plus
attributes. One earthquake epicentre with `mag`, `place` and `city_count` is one feature.

A **Feature Layer** is a table of features that share one geometry type and one schema
(the same columns). Our output is one point layer: one row per earthquake.

A **Feature Service** is the web service that hosts one or more layers (and plain tables)
and answers HTTP requests about them. The URLs show the hierarchy:

```
https://services.arcgis.com/<org>/arcgis/rest/services/drqa_m5_cities/FeatureServer      <- service
https://services.arcgis.com/<org>/arcgis/rest/services/drqa_m5_cities/FeatureServer/0    <- layer 0
https://.../FeatureServer/0/query?where=city_count>0&returnCountOnly=true&f=json            <- a query
```

In ArcGIS Online, publishing creates a **hosted feature layer** *item*: the catalogue entry
you see in "My Content". It points to the feature service that ArcGIS hosts for you.
Analogy: the service is a database server with a REST API, a layer is one table in it,
and the item is the listing in the app store.

Our contract tests talk to **layer 0** directly, because that's where `fields` and
`query` live.

## WGS84 vs Web Mercator

Both are *coordinate reference systems* (CRS), i.e. rules for turning numbers into places.

- **WGS84 (EPSG:4326)** is *geographic*: longitude/latitude in degrees on an ellipsoid that
  approximates the Earth. GPS and USGS use it, and so does our whole pipeline. Degrees are
  not a fixed distance: one degree of longitude is ~111 km at the equator, ~56 km at 60°N,
  and 0 km at the poles.
- **Web Mercator (EPSG:3857, which Esri calls wkid 102100)** is *projected*: it flattens the
  globe onto a square, with x/y in metres. Almost every web basemap uses it. It looks nice
  for tiles but stretches things away from the equator by a factor of 1/cos(latitude): 2×
  at 60°N, which is why Greenland looks as big as Africa.

Rule of thumb: **store and exchange in WGS84, display in Web Mercator, and never measure
distances in Web Mercator.** "100 km" in Web Mercator metres at 60°N is only about 50 km on
the ground. ArcGIS usually stores hosted layers in Web Mercator. That's why a contract
test asks for `outSR=4326` and checks that it gets valid lon/lat back.

## Buffer

A **buffer** is the area within a given distance of a geometry. Around a point it's a
"circle", but *which* circle depends on how distance is measured:

- **Planar buffer**: draw a circle in the coordinate numbers. `Point(lon, lat).buffer(0.9)`
  makes a circle of radius 0.9 *degrees*, which is roughly 100 km north–south but only
  50 km east–west at 60°N. Wrong for us.
- **Geodesic buffer** (what `geo.py` does): from the epicentre, walk exactly 100 km along
  the ellipsoid in 64 directions (`pyproj.Geod.fwd`) and join the end points. At high
  latitudes this shape is *wider in degrees* than it is tall, which is correct
  (`test_buffer_is_not_a_circle_in_degrees_at_high_latitude`).

Two edge cases we handle:

- A buffer near longitude ±180 is cut into two pieces (next section).
- A polygon with 64 corners sits slightly *inside* the true circle, so we push the corners
  out a little for the search and then do an exact distance check.

## Antimeridian handling

The **antimeridian** is the line at longitude ±180°, in the Pacific. It crosses Fiji and runs
past the Tonga–Kermadec subduction zone, one of the most seismically active places on Earth.
On the globe nothing special happens there: 179.9°E and 179.9°W are about 22 km apart at the
equator. **In the numbers, though, they are 359.8 apart**, and that breaks naive geometry code:

- A 100 km buffer around an epicentre at 179.5°E reaches 180.4°E, which doesn't exist; the
  correct coordinate is −179.6°. Written naively, the polygon's points jump from +179.x to
  −179.x, and the polygon connecting them stretches **the wrong way round the world**: a band
  ~359° wide that "contains" almost everything.
- So a quake near Fiji would match cities in Africa, or (with other naive fixes) miss the city
  right across the line.

What `geo.py` does:

1. Build the ring of points with **continuous** longitudes around the centre (allow 180.4
   instead of −179.6), so the polygon is the right small shape.
2. **Cut** it at ±180, and shift the overflowing piece back by 360° → a `MultiPolygon` with
   one piece on each side, all coordinates valid.

Tests check it's split, valid, within ±180, that it covers both sides but not longitude 0, and
that cutting **loses no area** (same area as an identical buffer at longitude 0). In the real
1-year data, 29 epicentres are within 1° of ±180. One of the fixture events is a synthetic
quake at −179.95° whose nearest city, Labasa in Fiji, is at +179.38°, about 71 km away
across the line.

## Spatial join

A normal (SQL) join matches rows on equal keys: `orders.customer_id = customers.id`.
A **spatial join** matches rows on a *spatial relationship* between their geometries,
such as *intersects*, *within*, *contains* or *within distance d*.

Here: "join each city to every earthquake buffer it falls inside".
`geopandas.sjoin(cities, buffers, predicate="intersects")` does this using a spatial index
(an R-tree), so it only compares a city with buffers whose bounding boxes overlap it,
instead of checking every city against every quake.

Then we:

1. check the exact geodesic distance for each candidate pair and keep those ≤ 100 km,
2. group by earthquake to get `city_count`, `city_names` and the nearest city, and
3. **left-join** back onto the earthquakes, so quakes with zero nearby cities stay in the
   output with `city_count = 0` instead of silently disappearing.

On the real 1-year data, the indexed join took 0.19 s. A brute-force check of all
14.5 million pairs took 5.5 s and agreed with the join on every event.

## Contract vs unit vs E2E tests

Tests differ in **how much of the real system they include**, and therefore in speed,
reliability and what a failure tells you.

| | Unit | End-to-end (E2E) | Contract |
|---|---|---|---|
| **Tests** | one function in isolation | the whole program, input file → output file | a boundary with a system **we don't control** (the ArcGIS Feature Service) |
| **Example here** | `test_min_magnitude_is_inclusive`: M5.0 kept, M4.99 dropped | `test_matches_brute_force_oracle`: CLI on fixtures, every event checked against an independent calculation | `test_expected_fields_present`, `test_response_time_under_budget`, `test_invalid_query_is_reported_as_error_payload` |
| **Data** | tiny hand-built inputs | committed fixtures (100 events, 200 cities) | a live service over the network |
| **Speed / reliability** | milliseconds, deterministic | well under a second here, deterministic | seconds; can fail because of the network |
| **A failure means** | this function is wrong | something in the chain is wrong | the service changed, or our assumptions about it are wrong |
| **When it runs** | every push | every push | only when `FEATURE_SERVICE_URL` is set (auto-skip otherwise) |

Why have all three:

- **Unit tests** pinpoint *where* a bug is, but every unit can pass while the pieces don't fit together.
- **E2E tests** catch wiring mistakes, but tell you less about *which* part broke.
- **Contract tests** check things neither can: the published layer is a different system, with
  its own field types, Web Mercator storage, and a habit of reporting errors as **HTTP 200 with
  an error body**. A contract test pins those expectations, so if the provider changes, a
  specific test fails instead of downstream code misbehaving silently.

A fourth idea used here, **mutation testing**, tests the *tests*: inject a deliberate bug (e.g.
skip the antimeridian cut) and check that some test fails. Our suite catches 13 of 13 injected
bugs; a passing test that catches none of them may not be checking much.
