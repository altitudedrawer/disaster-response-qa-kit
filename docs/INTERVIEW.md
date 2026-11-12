# Interview prep

Answer points, not scripts. Say them in your own words. Every number below comes from a run
recorded in `README.md` or `docs/DEVLOG.md`; `[N]` / `[X]%` are placeholders to fill **only**
from results you actually produce.

---

## Part A: deep-dive questions

### 1. Why geodesic buffers instead of buffering in degrees?
- A degree of longitude shrinks with latitude (≈111 km at the equator, ≈56 km at 60°N), so a
  "circle" in degrees is an ellipse on the ground: about 2× too wide east–west at 60°N.
- I walk 100 km along the WGS84 ellipsoid in 64 directions (`pyproj.Geod.fwd`); a test checks
  every vertex is within **1 m** of 100 km, and another that at 60°N the shape is ~2× wider in degrees.
- The polygon is only a fast pre-filter; the final yes/no is an exact geodesic distance.

### 2. How do you handle the antimeridian?
- Near ±180°, points jump from +179.x to −179.x and a naive polygon wraps the wrong way round the world.
- Build the ring with continuous longitudes (180.4 instead of −179.6), cut at ±180, shift the
  overflow by 360° → valid `MultiPolygon`.
- Tests: split, valid, within ±180, covers both sides but not longitude 0, **no area lost**; an
  E2E fixture case finds Labasa (Fiji, +179.38°) 71 km from a quake at −179.95°. 29 real events
  in the 1-year data are within 1° of the line.

### 3. How do you know the output is correct?
- Independent oracle: brute-force geodesic distance for **every** event–city pair, no spatial index.
- Real 1-year run: 1,978 × 7,342 pairs (5.5 s) → **0 mismatches** with the pipeline (0.19 s).
- The same oracle runs as an E2E test on the fixtures in every CI run.

### 4. Why commit fixtures instead of downloading data in tests?
- Tests must be fast, offline and deterministic; USGS feeds change hourly.
- Fixtures are **real** data sampled with a fixed seed (92 events, 200 cities), plus 8 clearly
  labelled synthetic edge cases the real data didn't contain (null magnitude, lon 200, a stale
  duplicate, an antimeridian quake…).
- Real data is still exercised, separately, by `download_data.py` + `oracle_check.py`.

### 5. What's the difference between unit, E2E and contract tests, and why do you need contract tests?
- Unit: one function, tiny inputs, pinpoints the bug. E2E: whole CLI on fixtures, catches wiring.
- Contract: a boundary with a system I don't control (the ArcGIS Feature Service): fields
  present, record count > 0, response time under budget, valid lon/lat in WGS84.
- Real example: ArcGIS returns **errors as HTTP 200** with an `{"error":…}` body. A test pins
  that, and the client checks the body, not just the status code.
- They auto-skip without `FEATURE_SERVICE_URL`, so CI stays green offline. Verified against
  Esri's public Living Atlas layer, and shown to fail when they should.

### 6. Your tests passed on the first run. How did you know they were any good?
- I didn't. Green on the first run can mean "can't fail". So I injected bugs on purpose (mutation testing).
- Phase 1: 7 hand-made mutants, **1 survived**: using the plain 64-gon as the pre-filter
  silently misses cities at ~99.9 km between two vertices. Added a test at exactly that spot.
- Now automated: `mutation_check.py`, 13 mutants; our suite kills **13/13**.

### 7. What problems did the real data cause?
- A **landslide** labelled "M5.2" in an earthquake query → filter on USGS `type`.
- 242 duplicate city names (Aberdeen UK/US) → "name (country)" labels.
- Natural Earth's lat/lon columns disagree with the geometry for 301 places (up to 0.73°) → geometry only.
- 19 near-simultaneous event pairs → investigated, look like foreshock/mainshock pairs → kept and
  documented, because merging would be a guess.
- Profiling **before** running the pipeline is what surfaced these.

### 8. Jenkins vs GitHub Actions: why both, and when would you pick each?
- GitHub Actions: zero infrastructure, lives next to the code, great for open-source and PR checks.
  Here: pytest on 3.11 + 3.13, then Docker build + tests in the image. First run green in 1m 0s.
- Jenkins: self-hosted, so it fits companies with on-prem networks, internal artifact stores,
  long-running or hardware-specific jobs, and lots of existing plugins/pipelines.
- Same stages in both. I ran Jenkins for real: a green build, and a red build where a failing
  test **blocked** the image stages. Gotcha found: `/build` returns 400 once a job has parameters.

### 9. What went wrong with Docker?
- `entrypoint.sh: Permission denied`: host files were `0600`, `COPY` keeps modes, and `chmod +x`
  doesn't add read permission → `COPY --chown/--chmod`.
- A mounted `output/` wasn't writable by the container's non-root UID on Linux → world-writable
  sticky dirs in the image + run as the host user; verified with an arbitrary UID.
- Neither showed up in any local test; only running the container found them.

### 10. How do you handle secrets?
- Credentials only from environment variables; `.env` is gitignored, `.env.example` has placeholders.
- `publish.py --dry-run` validates everything without logging in; tests prove a fake password
  never appears in output or error messages.
- `.dockerignore` excludes `.env`; I verified a fake secret in the build context is absent
  from every file in the image.

### 11. How would you scale to 100× the data?
- Today: 1,978 events × 7,342 cities in 0.19 s with an R-tree; I haven't measured 100× (**[not measured]**).
- First, benchmark (events and cities scale differently; the join is roughly events × nearby cities).
- Then: vectorize buffer creation; partition by region/tile and run in parallel; or move the
  join into a spatial database (`ST_DWithin` on a `geography` type in PostGIS) or ArcGIS's
  big-data tools. Keep the oracle on a sample as the correctness check.

### 12. What are the limits of LLM-generated tests?
- My experiment (DeepSeek-V4.1-Flash-1017, docstrings only, one shot): 62 tests.
- **Good:** it found **2 real bugs** I had missed: a docstring promising "scalars or arrays"
  that crashed on mixed input, and numpy rounding 12.345 → 12.34.
- **Limits:** its tests killed **12/13** injected bugs and missed exactly the subtle edge case
  (M03); 32 of 61 passing tests killed no mutant; one test's own setup was broken.
- Acceptance rate after my review: **[X]%** (95% CI [X]–[X]%), usable **[X]%**.
- Takeaway: good at checking what the docs say; weaker at the geometry corner cases. Needs a
  human reviewer and a mutation check, not just "it's green".

### 13. How did you keep the LLM experiment honest?
- Prompts and rules committed to git **before** generating any output (`f1cb91d`).
- One shot, no coaching; raw replies kept unmodified (`*.raw.md`).
- Decision categories defined up front; tooling refuses inconsistent rows.
- One rule changed after seeing pass/fail results (to credit tests that found real bugs). It's
  disclosed, and the rate under the original rules is always printed next to it.
- Wilson 95% interval, because ~60 tests leaves wide uncertainty.

### 14. A test passes locally but fails in CI. How do you debug it?
- Reproduce CI's environment: same Python version, run inside the same Docker image.
- Real near-misses here: the new experiment tests read `experiments/`, which wasn't copied into
  the image. CI's in-container run would have failed with a collection error; I caught it by
  building the image locally first. Also: pytest doesn't collect files that don't match
  `test_*.py`, and a Homebrew Python without the project packages fails every import.

### 15. What would you do differently?
- Smaller commits from day one (the early history is one commit per phase).
- Set up the project `.venv` on my Mac at the start, not in Phase 5.
- Ask for the ArcGIS account in week one: the publish is still blocked on SSO access.
- Add property-based tests (Hypothesis) for the geometry, e.g. "distance ≤ radius ⇔ city listed"
  for random points.

---

## Part B: questions about the project itself

### How long did this take?
- Git history: first commit **2026-10-20**, latest **2026-11-12**, across **[N]** working sessions.
- About **[N] hours** of hands-on time. Be precise and honest; don't round it down to sound
  faster or up to sound bigger. The calendar span includes waiting time (e.g. for ArcGIS access).

### Did you use AI tools?
- Yes, openly: **Claude** wrote most of the code, tests and docs and ran verification in a sandbox;
  **DeepSeek** was only the subject of the test-generation experiment.
- What I did: set the scope and honesty rules, ran everything on my own machine (tests, Docker,
  CI, the experiment), debugged my setup (git, venv, SSO), made the judgement calls (protocol
  amendment, rounding fix), made every commit, and review every generated test.
- How I kept it trustworthy: every claim labelled VERIFIED / UNTESTED, every number from a real
  run, an independent oracle, and mutation testing on the tests themselves.

### What did you learn?
- [Your own words; candidates from what actually happened:]
- A green test suite proves little until you show it can fail (the inscribed-polygon mutant).
- Real data breaks assumptions that synthetic data never will (a landslide in an earthquake feed).
- Containers fail in ways local runs can't show (file modes, UIDs).
- External services need contract tests (HTTP 200 errors).
- LLM tests are a useful second reviewer of your docs (they found 2 real bugs) but miss subtle edge cases.

### Why this topic?
- [Your reason.] Factual anchors: the Esri SDE internship focuses on Python, test automation,
  DevOps and LLMs for testing. A small geospatial question (earthquakes near cities) let me
  practise all of those on Esri's own domain with public data.

### What would you improve with more time?
- Run the real ArcGIS publish and the two pending contract tests.
- Finish the experiment: [N] more models or prompt versions, to compare acceptance rates.
- Property-based tests for the geometry; a 100× benchmark.
- Population exposure (people, not just city points) as the analysis next step.
