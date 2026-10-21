# Test fixtures

Built by `python scripts/make_fixtures.py` (fixed seed 42) and committed so tests run offline.

| File | Rows | Source |
|---|---|---|
| `earthquakes_sample.geojson` | 100 | 92 real events randomly sampled from the USGS M4.5+ 30-day feed (snapshot 2026-10-21 03:33 UTC) + 8 synthetic edge cases |
| `cities_sample.geojson` | 200 | Natural Earth 10m populated places (simple), public domain: cities within 150 km of a fixture event, all cities with abs(lon) > 177, then a random fill |

Synthetic events have ids starting with `synthetic_` (except the stale duplicate,
which reuses a real id on purpose) and a `_note` property explaining them:
null magnitude, non-numeric magnitude, lat 95, lon 200, null geometry,
an antimeridian event at lon -179.95 near Labasa, Fiji (lon +179.38), an open-ocean
M5.2 with no nearby city, and an older duplicate of a real event with fake mag 1.0.
