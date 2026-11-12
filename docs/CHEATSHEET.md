# Cheat sheet (15-minute read)

**One line:** which cities are within 100 km of M5+ earthquakes? A simple spatial question,
wrapped in heavy testing and DevOps.

## Pipeline flow

| Step | File | What happens | Key number (real run) |
|---|---|---|---|
| 1. Ingest | `ingest.py` | USGS GeoJSON → one row per event; no judging yet | 1,979 events (1 year, M5+) |
| 2. Clean | `clean.py` | drop: null magnitude, bad coordinates, duplicate IDs (keep newest), non-earthquakes, < M5. Every drop is counted | 1 dropped (a landslide) |
| 3. Buffer | `geo.py` | 100 km **geodesic** polygon around each epicentre; split at ±180° | vertices within 1 m of 100 km |
| 4. Join | `join.py` | R-tree finds candidate cities in a slightly padded polygon → exact distance ≤ 100 km → per-event count, names, nearest | 563 of 1,978 quakes have ≥1 city; 0.19 s |
| 5. Output | `run.py` | GeoJSON, one point per quake (left join: 0-city quakes stay) | — |
| 6. Publish (optional) | `publish.py` | ArcGIS hosted feature layer; `--dry-run` without login | not run yet (no account) |
| ✓ Verify | `oracle_check.py` | brute-force all 14.5 M pairs | **0 mismatches** (5.5 s) |

## Five core concepts

1. **Geodesic buffer.** Distance measured on the Earth's (ellipsoidal) surface, not in degrees.
   A degree circle is 2× too wide at 60°N. Build the 100 km shape by walking 100 km in 64
   directions, then confirm each candidate with an exact distance.
2. **Antimeridian handling.** At ±180° longitude, coordinates jump from +179.x to −179.x and a
   naive polygon wraps the wrong way round the world. Build the ring with continuous longitudes,
   cut it at ±180, shift the overflow 360° → `MultiPolygon`. Test: no area lost.
3. **Spatial join.** A join on location instead of a key ("city inside buffer"). The spatial
   index avoids comparing every pair. A **left** join keeps quakes with no city.
4. **Feature Layer vs Feature Service.** Service = the web endpoint (`…/FeatureServer`); layer
   = one table of features in it (`…/FeatureServer/0`, where `fields` and `query` live); a hosted
   feature layer *item* is the catalogue entry. Stored in Web Mercator; ask for `outSR=4326` to
   get lon/lat back.
5. **Contract vs unit vs E2E tests.** Unit = one function; E2E = whole CLI on fixtures vs an
   oracle; contract = a live service we don't control (fields, count, speed, error format).
   Contract tests auto-skip without `FEATURE_SERVICE_URL`. Bonus: **mutation testing** tests the
   tests (our suite kills 13/13 injected bugs).

## Three real problems we hit

1. **A green test suite that missed a bug.** All tests passed on the first run. Injecting 7
   bugs on purpose showed that one survived: using the plain 64-gon as the pre-filter misses
   cities at ~99.9 km between two vertices. *Fix:* pad the polygon so it contains the true
   circle, plus a test at exactly that spot. *Lesson:* prove a test can fail.
2. **Docker bugs only a real container shows.** Host files with mode `0600` + `COPY` → the
   non-root user couldn't read `entrypoint.sh`; a mounted `output/` wasn't writable for another
   UID. *Fix:* explicit `--chown/--chmod`, sticky world-writable dirs, run as the host user.
   *Lesson:* run the artifact, not just the code.
3. **An LLM's tests found 2 bugs in my code, and missed the subtle one.** DeepSeek, given only
   docstrings, wrote 62 tests. They exposed a "scalars or arrays" function that crashed on mixed
   input, and numpy rounding 12.345 → 12.34. But they missed mutant M03 (problem 1 above).
   *Lesson:* use LLM tests as a second reviewer, not a replacement.

## Numbers to remember (fill the brackets only from real results)

1,979 events → 1,978 kept → 563 with cities · 7,342 cities · 0.19 s join vs 5.5 s brute force ·
0 mismatches · 131 test cases + 8 contract · CI #1 green in 1m 0s · mutation: ours 13/13,
LLM 12/13 · LLM acceptance **[X]%** · hours spent **[N]**
