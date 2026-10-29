# Run on your machine (macOS)

This file collects every step Claude could NOT run for you, with exact commands.
It grows phase by phase.

## Where Claude ran things (Phase 0 findings, 2026-10-20)

| Capability | Your folder's Linux VM (arm64, Ubuntu 22.04) | Claude's cloud sandbox (x86_64) |
|---|---|---|
| Python | 3.10 system; 3.11.17 installed via `uv` | 3.13 |
| pip / package installs | yes (PyPI reachable) | yes |
| Internet: USGS, Natural Earth, GeoNames | yes | yes |
| Docker | no | yes (daemon started, Docker Hub pulls work) |
| git | yes, but see note below | yes |
| Jenkins / Ansible | not installed | not installed (can run Jenkins in Docker) |
| ArcGIS Online login | no credentials (by design) | no credentials (by design) |

Note on git: the session can't delete files in your folder, and git deletes its own
`.lock` files, so Claude will NOT run `git commit` there. You make the commits on your Mac.

## One-time Mac setup

```bash
# 1. Install uv (fast Python/venv manager). Pick ONE:
brew install uv
# or: curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. From the project folder, create a Python 3.11 virtual env
cd ~/DisasterResponse/disaster-response-qa-kit
uv venv --python 3.11 .venv
source .venv/bin/activate

# 3. Install dependencies (requirements.txt is created in Phase 1)
uv pip install -r requirements.txt

# 4. Docker Desktop for Mac (needed for Phase 4): https://www.docker.com/products/docker-desktop/
docker --version
```

## Phase 1: tests and pipeline on fixtures (offline)

```bash
cd ~/DisasterResponse/disaster-response-qa-kit && source .venv/bin/activate
python -m pytest -v                       # 64 tests, no internet needed
PYTHONPATH=src python -m pipeline.run \
  --events tests/fixtures/earthquakes_sample.geojson \
  --cities tests/fixtures/cities_sample.geojson \
  --out output/fixture_results.geojson
```

Optional: rebuild fixtures (needs `data/raw/` downloads; output should be identical):
`python scripts/make_fixtures.py` (identical output only from the same USGS snapshot; the 30-day feed changes, so a fresh download gives different fixtures and some fixture tests would need updating)

## Phase 2: real data (needs internet, ~4 s download, ~2.6 MB)

```bash
python scripts/download_data.py --start 2025-10-20 --end 2026-10-20 --min-mag 5
PYTHONPATH=src python -m pipeline.run \
  --events data/raw/usgs_m5_2025-10-20_2026-10-20.geojson \
  --cities zip://data/raw/ne_10m_populated_places_simple.zip \
  --out output/m5_1yr.geojson
python scripts/oracle_check.py output/m5_1yr.geojson zip://data/raw/ne_10m_populated_places_simple.zip
```

## Commands added in later phases
TODO: filled in as each phase lands.
