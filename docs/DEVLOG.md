# Dev log

Dates are **git commit dates** (author's choice). Where work happened before its commit, that's
noted. Every error below is one that actually occurred; numbers come from commands that were run.

---

## Phase 0: environment check (no separate commit; part of `b40a920`, 2026-10-20)

**Done:** checked what could run where. The Linux VM attached to the project folder (arm64) had
Python 3.10 and no Docker; Claude's cloud sandbox (x86_64) had Python 3.13 and a working Docker
engine. Both could reach USGS, Natural Earth, GeoNames and PyPI.

**Failed → fixed:** the VM's Python 3.10 is below the project's 3.11 requirement → installed
3.11.17 with `uv`.

**Untested:** nothing yet; `docs/RUN_ON_YOUR_MACHINE.md` started.

## Phase 1: core pipeline + offline tests (`b40a920`, 2026-10-20 21:09 −07:00)

**Done:** `ingest`, `clean`, `geo` (geodesic buffers, antimeridian split), `join` (R-tree
pre-filter + exact distance), CLI. Fixtures: 92 real USGS events + 8 labelled synthetic edge
cases, 200 Natural Earth cities, built by `scripts/make_fixtures.py` (seed 42). 61 tests passed
on the first run.

**Failed → fixed:** a suite that passes immediately might not be able to fail, so **7 bugs were
injected by hand** (mutation testing). 6 were caught; **1 survived**: using the plain (inscribed)
64-gon as the pre-filter, which misses cities at ~99.9 km lying between two vertices. Added
`test_city_just_inside_radius_between_polygon_vertices_is_found` → all 7 caught, 63 tests.
*Correction:* this was later described in chat as "all 8 bugs caught"; there were 7. The
automated check added on 2026-11-12 uses 13 (M01–M07 are these 7).

**Untested:** real data (Phase 2).

## Phase 2: real data (`cda4405`, 2026-10-29 15:36 −07:00; data downloaded 2026-10-21 04:10 UTC)

**Done:** `scripts/download_data.py` (with SHA-256 manifest), run on 1,979 M5+ events (1 year) and
the 30-day feed. 563 of 1,978 kept events have ≥1 city within 100 km; 0.19 s per run.
`scripts/oracle_check.py` brute-forced all 14.5 M pairs (5.5 s): **0 mismatches**.

**Failed → fixed:**
- Profiling found a **landslide** (`us7000tbwb`, "M5.2") in an earthquake query → new
  `non_earthquake` cleaning rule + test.
- 242 duplicate city names (Aberdeen UK/US) → `"name (country)"` labels.
- Natural Earth's lat/lon columns disagree with the point geometry for 301 places (up to 0.73°)
  → only the geometry is used.
- 19 pairs of events < 60 s and < 0.5° apart → investigated; they look like foreshock/mainshock
  pairs → kept, documented as a limitation.
- **Repo move:** the project was moved into a `disaster-response-qa-kit/` subfolder mid-phase, so
  paths broke (`scripts/download_data.py: No such file`) → continued in the new location.
- **`.gitignore` and `.env.example` were left in the parent folder** (Finder hides dotfiles), so
  the first pushes included `data/`, `output/`, `.DS_Store` and `__pycache__` (public data, no
  secrets) → copied the dotfiles in; untracked the files with `git rm --cached` in `a31bdd1`
  (the first attempt ran in the wrong folder: `fatal: not a git repository`).

**Untested:** GeoNames download path (`--geonames`) not run.

## Phase 3: ArcGIS publish + contract tests (`a31bdd1`, 2026-10-29 16:32 −07:00)

**Done:** `publish.py` with `--dry-run`, written against ArcGIS API for Python 2.4.4 after reading
the current docs and inspecting the installed package's signatures. Contract tests auto-skip
without `FEATURE_SERVICE_URL`; credentials only from environment variables.

**Failed → fixed:**
- `arcgis` **won't install on Linux arm64** (its `arcgis-geometry` dependency has no wheel) →
  made it optional (`requirements-publish.txt`); its tests ran in the x86_64 sandbox (83 passed).
- ArcGIS REST returns **errors as HTTP 200** with an `{"error": ...}` body → the contract-test
  client checks the body; a test pins this behaviour.
- Longest `city_names` is 307 chars; unknown whether publishing truncates it → contract test
  `test_longest_city_names_not_truncated` to answer it on a real publish.
- Contract-test harness verified against Esri's public Living Atlas earthquake layer (6 passed),
  and shown to fail when it should (missing fields; 1 ms time budget).

**Still blocked (2026-10-29, timestamp from the Microsoft error page 23:24 UTC):** no ArcGIS
account. Claude first pointed to the `usc` org (an inference from its public name, which turned
out wrong); USC SSO there returned `AADSTS50105` from an app named "USC-FPM-ArcGIS
Enterprise-SSO". Student accounts go through USC's Spatial Sciences Institute → next step: email
`spatial_support@usc.edu` (status: [sent on DATE / not sent yet]).

**Untested:** real publish; the 2 contract tests that need our own layer.

## Phase 4: DevOps (`8826824`, 2026-10-29 17:08 −07:00; `6085765`, 17:12)

**Done:** Dockerfile (`test`/`demo`/`pipeline`, non-root), `.dockerignore`, GitHub Actions
(3.11 + 3.13 matrix, Docker job), Jenkinsfile + local Jenkins image, minimal Ansible playbook.

**Failed → fixed:**
- Sandbox-only: Claude's sandbox proxy re-signs TLS, so `pip` in `docker build` failed → a
  sandbox-only copy of the Dockerfile trusted the proxy CA; the committed Dockerfile is unchanged.
- **`entrypoint.sh: Permission denied`**: host files were mode `0600`, `COPY` kept it, `chmod +x`
  doesn't add read → `COPY --chown/--chmod`.
- **Bind-mounted `output/` not writable** for a non-default UID → `chmod 1777 data output` in the
  image + run as the host user; verified as uid 1234.
- pytest cache warning in a root-owned `/app` → `PYTEST_ADDOPTS=-p no:cacheprovider`.
- Docker Hub `429 Too Many Requests` → waited and retried.
- **Jenkins `/build` → HTTP 400** after the first run (job became parameterized) →
  `/buildWithParameters`. Build #1 green (72 s); build #2 with a deliberately broken test red,
  and the image stages were skipped.
- **Ansible failed loudly** on the same bind-mount UID issue → runs the container as the target
  host's user (`ansible_facts.user_uid`); verified as a non-root user.
- On the Mac: `docker: command not found` → installed Docker Desktop; `docker run --rm drqa:dev`
  → 81 passed, 3 skipped.
- **CI #1 passed on GitHub** in 1m 0s (commit `8826824`); README badge added in `6085765`.

**Untested:** Jenkins on Apple Silicon; Jenkins contract stage; Ansible registry pull.

## Phase 5: LLM test-generation experiment (`0841db3`, 2026-10-29 17:35; `f1cb91d`, 2026-10-30 11:36; `a645ee4`, 2026-11-12 12:23 −08:00)

**Done:** prompt template, signature extractor, review sheet, `acceptance_rate.py` (Wilson 95% CI),
`prefill_sheet.py`; prompts frozen and committed **before** any output was generated (`f1cb91d`).
DeepSeek-V4.1-Flash-1017 generated 62 tests for 4 modules; 59 passed unmodified.

**Failed → fixed (before generation):**
- The extractor showed `CleanResult` had no docstring and hid its fields → documented; fields shown.
- The Docker image didn't include `experiments/`, so the new tests would have broken CI's
  in-container run ("1 error") → added to the image.
- The extractor **leaked annotated local variables** from a function body; `PublishError` didn't
  show it's an `Exception`; defaults and input columns weren't visible → fixed + regression test.

**Failed → fixed (during generation, all on the Mac):**
- `SyntaxError: ```python`: the reply was saved with Markdown fences → `prefill_sheet.py` strips a
  single fenced block and keeps the raw reply as `*.raw.md`.
- File named `4.1flash_clean_v1.py` (a dot → pytest can't import it), and `python` was Homebrew
  3.14 without the project packages (no `.venv` existed). Both would have silently marked every
  test "not green" → the helper now refuses both; `.venv` created with `uv`.
- Model name spelled two ways in the sheet → `acceptance_rate.py` now flags case-only differences.
- Two of Claude's own Phase 5 tests assumed the review sheet stays empty forever → rewritten to
  check the sheet is well-formed instead.
- `pytest generated/` collects nothing (files don't match `test_*.py`) → docs name files explicitly.

**Bugs found by the generated tests (fixed in `a645ee4`, with regression tests):**
1. `geodesic_distance_m` promised "scalars or arrays" but raised `GeodError` for a scalar vs. an
   array → inputs are broadcast.
2. `nearest_km` used numpy/pandas rounding: 12.345 → 12.34 (correctly rounded: 12.35) → Python
   `round()`.
→ **Protocol amendment v1.1** (author's decision, disclosed): reason `found_real_bug`; the
original-v1 rate is always printed alongside.

**Untested / pending:** human review of all 62 rows; acceptance rate not computed.

## 2026-11-12: mutation check + Phase 6 docs (commits pending; dates = their commit dates)

**Done:** `mutation_check.py` with 13 documented mutants (M01–M07 = Phase 1's, M08–M13 new so
every tested module has some). Tool validated by reproducing Phase 1's kill counts on our suite.
Results: our suite kills **13/13**; the generated tests kill **12/13**, with **M03 surviving**
(the inscribed-polygon edge case); 32 of 61 generated tests that pass kill no mutant
(`mutation_results.csv`). Docs: README rewrite (scope, diagrams, test strategy, trade-offs,
AI assistance), this log, `WORKFLOW.md`, `CONCEPTS.md` (5 core concepts), `INTERVIEW.md`,
`CHEATSHEET.md`.

**Failed → fixed:** first run counted skipped tests as passing and parametrized cases separately
(72 rows vs 62 sheet rows) → skips excluded; results aggregated to one row per sheet `test_id`.

**Review tooling (same day):** running `acceptance_rate.py` listed all 62 rows as "not reviewed
yet": the sheet on disk had no decisions saved (identical to the committed version). Added
`review.py`, an interactive reviewer that shows each test, the frozen docstring and the bugs it
catches, saves every answer atomically and enforces the same rules as `acceptance_rate.py`
(tests in `tests/test_review_tool.py`). While building it: one scripted test had out-of-step
answers (test bug, fixed); quitting rewrote the file unchanged (now it doesn't); the sheet mixed
`\n` and `\r\n` line endings (both tools now write `\n`). Suite: 129 passed, 3 skipped.

**Untested / pending:** same as Phase 5, plus the ArcGIS publish.
