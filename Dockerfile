# DisasterResponse QA Kit -- one image, three commands:
#   docker run --rm drqa:dev test                       # offline test suite (default)
#   docker run --rm drqa:dev demo                       # pipeline on committed fixtures (offline)
#   docker run --rm -v "$PWD/output:/app/output" drqa:dev pipeline   # download real data + run (needs internet)
#   (Linux: add --user "$(id -u):$(id -g)" so files in output/ are owned by you)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    PYTEST_ADDOPTS="-p no:cacheprovider"

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes.
# geopandas/pyogrio/pyproj ship manylinux wheels with GDAL/PROJ inside, so no apt packages needed.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Non-root user. Permissions are set explicitly with --chown/--chmod because the source
# files may be owner-only (0600) on the host, and COPY preserves modes. (Found when the
# first build failed with "entrypoint.sh: Permission denied".)
RUN useradd --create-home --uid 10001 app \
 && mkdir -p data/raw output \
 # 1777 (like /tmp): writable by ANY uid, so `docker run --user "$(id -u):$(id -g)" -v ...`
 # works on Linux hosts/CI where the mounted folder isn't owned by uid 10001.
 && chmod 1777 data data/raw output
COPY --chown=app:app --chmod=a+rX pyproject.toml ./
COPY --chown=app:app --chmod=a+rX src/ src/
COPY --chown=app:app --chmod=a+rX tests/ tests/
COPY --chown=app:app --chmod=a+rX scripts/ scripts/
COPY --chown=app:app --chmod=a+rX experiments/ experiments/
COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/entrypoint.sh
USER app

ENTRYPOINT ["entrypoint.sh"]
CMD ["test"]
