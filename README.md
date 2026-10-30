# DisasterResponse QA Kit

[![CI](https://github.com/altitudedrawer/disaster-response-qa-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/altitudedrawer/disaster-response-qa-kit/actions/workflows/ci.yml)

**Question:** which cities are within 100 km of M5+ earthquakes?

USGS earthquakes → clean → geodesic 100 km buffer → spatial join with city points → GeoJSON
→ (optional) ArcGIS hosted feature layer. The analysis is deliberately simple; the point of
the project is the testing and DevOps around it.

> Full README (architecture diagram, test strategy, trade-offs) lands in Phase 6.

## Quick start

```bash
uv venv --python 3.11 .venv && source .venv/bin/activate && uv pip install -r requirements.txt
python -m pytest                                   # offline, uses tests/fixtures/
python scripts/download_data.py --start 2025-10-20 --end 2026-10-20 --min-mag 5
PYTHONPATH=src python -m pipeline.run \
  --events data/raw/usgs_m5_2025-10-20_2026-10-20.geojson \
  --cities zip://data/raw/ne_10m_populated_places_simple.zip \
  --out output/m5_1yr.geojson
python scripts/oracle_check.py output/m5_1yr.geojson zip://data/raw/ne_10m_populated_places_simple.zip
```

## Data sources

Downloaded 2026-10-21 04:10 UTC with `scripts/download_data.py`; URLs, sizes and SHA-256
hashes are in `data/raw/MANIFEST.json` (gitignored with the data).

| Dataset | URL | Rows | License |
|---|---|---|---|
| USGS M5+ custom query, 2025-10-20 → 2026-10-20 | `earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2025-10-20&endtime=2026-10-20&minmagnitude=5` | 1,979 | US Government work, public domain |
| USGS M4.5+ past 30 days feed | `earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson` | 655 | US Government work, public domain |
| Natural Earth 10m Populated Places (simple) | `naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places_simple.zip` | 7,342 | Public domain |
| GeoNames cities15000 (optional, `--geonames`; not used in results below) | `download.geonames.org/export/dump/cities15000.zip` | not downloaded | CC BY 4.0, attribution required |

Test fixtures (`tests/fixtures/`) are a 100-event / 200-city sample of the above plus labelled
synthetic edge cases; see `tests/fixtures/README.md`.

## Results (real data)

Measured 2026-10-21 in the project's Linux VM (arm64, Python 3.11.17). Your numbers will differ
if you download on another date, since the USGS feeds change.

| Run | Events in | Kept (M5+, valid) | Events with ≥1 city | Event–city pairs | Pipeline runtime |
|---|---|---|---|---|---|
| 1 year, M5+ | 1,979 | 1,978 | 563 | 1,118 | 0.19 s (3 runs: 0.191 / 0.188 / 0.187 s) |
| 30 days, M4.5+ feed filtered to M5+ | 655 | 176 | 56 | 112 | 0.09 s |

- 504 distinct cities lie within 100 km of at least one M5+ quake in the year.
- **Independent check:** `scripts/oracle_check.py` brute-forces all 1,978 × 7,342 geodesic
  distances (5.5 s, no spatial index) and found **0 mismatches** with the pipeline output.
- Runtime is `pipeline.run`'s internal timer (load → clean → join → write), excluding Python start-up.

## Problems encountered

Found by profiling the real downloads before running the pipeline:

1. **A "M5.2 earthquake" that is a landslide.** The USGS M5+ query returned `us7000tbwb`
   (type `landslide`, Nepal). *Fix:* `clean.py` drops rows whose USGS `type` isn't
   `earthquake` (counted as `non_earthquake`); test `test_non_earthquake_types_dropped_but_missing_type_kept`.
2. **Ambiguous city names.** Natural Earth has 242 repeated names (Aberdeen UK vs Aberdeen US).
   *Fix:* output uses `"name (country)"` labels, e.g. `Labasa (Fiji)`.
3. **Natural Earth lat/lon columns disagree with the geometry** by >0.01° for 301 of 7,342 places
   (up to 0.73°, e.g. Juina, Brazil). Spot checks showed the geometry is right. *Decision:* the
   pipeline only ever uses the point geometry; noted in `ingest.load_cities`.
4. **Possible double-counting of one quake under two IDs, investigated and NOT deduplicated.**
   19 pairs of events occur < 60 s and < 0.5° apart, but they have different magnitudes and are
   2–18 km apart (e.g. M5.4 then M7.3 six seconds later near Luganville, Vanuatu). These look
   like foreshock/mainshock sub-events, so merging them would be a guess. Limitation: a
   per-*city* risk summary would count such a city twice.
5. **What did *not* happen:** no null magnitudes, null/invalid coordinates or duplicate IDs in
   these USGS downloads. The cleaning rules for those are still tested with synthetic fixtures,
   because other date ranges or sources could contain them.
6. **Antimeridian on real data:** 29 events have |lon| > 179°; 1 of them has a city in range.
   All are covered by the oracle check above.
7. **Mixed magnitude types** (`mww` 1,127, `mb` 823, `ml` 15, others 13): "M5" means slightly
   different things across scales. Not corrected; noted as a limitation.
8. **Docker: `entrypoint.sh: Permission denied`.** Source files on the host were mode 0600,
   `COPY` preserves modes, and `chmod +x` adds execute but not *read*, so the non-root user
   couldn't run the script. *Fix:* `COPY --chown/--chmod` explicitly.
9. **Docker: can't write a mounted `output/` on Linux.** The container's uid 10001 doesn't own
   the host folder. *Fix:* `data/` and `output/` are mode 1777 in the image, and the docs (and the
   Ansible playbook) run the container as the host user. Verified with an arbitrary uid.
10. **Jenkins: `/build` returns HTTP 400 after the first run,** because the job is now
    parameterized. Use `/buildWithParameters`.

## Publishing to ArcGIS (Phase 3)

`python -m pipeline.publish <geojson> --dry-run` validates and prepares without logging in.
The real publish uses ArcGIS API for Python 2.4.4 with credentials from environment variables
only. Live contract tests in `tests/contract/` auto-skip unless `FEATURE_SERVICE_URL` is set.
Steps: `docs/RUN_ON_YOUR_MACHINE.md`. Concepts: `docs/CONCEPTS.md`.

Status: dry-run and the publish call sequence (against fake `arcgis` objects, plus a
signature check against the real 2.4.4 package) are tested. The real publish to ArcGIS Online
has **not been run yet** (TODO: run it and record the result here).

## DevOps (Phase 4)

| File | What it does | Status |
|---|---|---|
| `Dockerfile`, `docker/entrypoint.sh`, `.dockerignore` | One image; `test` (default), `demo`, `pipeline` | **VERIFIED**: built and ran all 3 commands (sandbox, x86_64); `test` also verified on the author's Mac with Docker Desktop (81 passed, 3 skipped). Image is 615 MB on disk, 142 MB compressed. Runs as non-root; a fake `.env` in the build context is absent from the image |
| `.github/workflows/ci.yml` | pytest on 3.11 + 3.13, JUnit artifacts, Docker build + tests in image | **VERIFIED** on GitHub: run CI #1 (commit `8826824`, 2026-10-29) passed in 1m 0s. Also lint-clean with actionlint 1.7.12 |
| `Jenkinsfile`, `jenkins/Dockerfile`, `docs/JENKINS.md` | checkout → install → test → (contract) → build image → test in image | **VERIFIED** in Jenkins LTS in Docker: a green build (81 tests in the report) and a red build (failing test blocks the image build). Contract stage UNTESTED |
| `ansible/deploy.yml` | Get image, run the container once, assert success | **VERIFIED** with a local image, as a non-root user. `drqa_pull=true` (registry) path UNTESTED |

## Honest limitations (so far)

- Buffers containing a pole raise an error (no M5+ quake was within 100 km of a pole in this data).
- Distance is to the epicentre; it ignores depth, fault extent and actual shaking intensity.
- City points, not city areas or population exposure.
