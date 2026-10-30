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
python -m pytest -v                       # offline; contract tests auto-skip
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

## Phase 3: publish to ArcGIS Online (you run this; Claude never sees your credentials)

What you need: an ArcGIS account that can **publish hosted feature layers** (an ArcGIS
Online organizational account with publisher privileges, or an ArcGIS Location Platform
account). If your account signs in only through SSO (e.g. a university login),
username/password won't work. Tell me and we'll switch `publish.py` to OAuth or an API key.

```bash
cd ~/DisasterResponse/disaster-response-qa-kit && source .venv/bin/activate
uv pip install -r requirements-publish.txt      # arcgis 2.4.4 (works on macOS arm64)

# 1. Dry run: validates the GeoJSON, builds metadata, no login, no network
PYTHONPATH=src python -m pipeline.publish output/m5_1yr.geojson --dry-run

# 2. Credentials: only in .env, which git ignores
cp .env.example .env
open -e .env                                    # fill ARCGIS_USERNAME / ARCGIS_PASSWORD, save
set -a; source .env; set +a

# 3. Real publish. --name must be unique in your org. --share-public lets the
#    contract tests run without a token (the data is public anyway).
PYTHONPATH=src python -m pipeline.publish output/m5_1yr.geojson --name drqa_m5_cities --share-public
#    -> prints JSON with "layer_url": ".../FeatureServer/0"

# 4. Put that layer_url into .env as FEATURE_SERVICE_URL=..., then reload and run the contract tests
set -a; source .env; set +a
python -m pytest tests/contract -v
```

Expected: 8 contract tests run. `test_longest_city_names_not_truncated` is the one most
likely to fail (it checks whether ArcGIS kept our 307-character `city_names`). If it fails,
that's a real finding: tell me and we'll fix the field length.

Re-publishing: delete the old item in ArcGIS Online -> Content first, or use a new `--name`.

Optional self-test of the contract-test harness against a public Esri layer, no account needed:
```bash
FEATURE_SERVICE_URL=https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/USGS_Seismic_Data_v1/FeatureServer/0 \
CONTRACT_EXPECTED_FIELDS=id,mag,place CONTRACT_LOCAL_GEOJSON= python -m pytest tests/contract -v
```

## Phase 4: Docker, CI, Jenkins, Ansible

```bash
# Docker (needs Docker Desktop running)
docker build -t drqa:dev .
docker run --rm drqa:dev                                   # test suite (default command)
docker run --rm drqa:dev demo                              # pipeline on fixtures, offline
docker run --rm -v "$PWD/output:/app/output" drqa:dev pipeline   # real data, needs internet (~20 s)
#   on Linux add: --user "$(id -u):$(id -g)"   (Docker Desktop on Mac handles ownership for you)

# GitHub Actions: just push. Then open the repo's "Actions" tab and check the "CI" run.
git push

# Jenkins: see docs/JENKINS.md

# Ansible (optional)
python3 -m pip install ansible-core docker
ansible-galaxy collection install -r ansible/requirements.yml
ansible-playbook -i ansible/inventory.ini ansible/deploy.yml
#   If it can't find Docker on macOS:  export DOCKER_HOST=unix://$HOME/.docker/run/docker.sock
```

## Phase 5: LLM test-generation experiment (you run it; results are yours)

Full protocol: `experiments/llm_tests/README.md`. Short version:
```bash
python experiments/llm_tests/extract_signatures.py src/pipeline/clean.py --functions CleanResult clean_events > /tmp/prompt_clean.txt
#   paste into an LLM, one shot, save output to experiments/llm_tests/generated/<model>_clean_v1.py
python -m pytest experiments/llm_tests/generated/ -v -p no:cacheprovider
#   fill experiments/llm_tests/review_sheet.csv (one row per test)
python experiments/llm_tests/acceptance_rate.py
```

## Commands added in later phases
TODO: filled in as each phase lands.
