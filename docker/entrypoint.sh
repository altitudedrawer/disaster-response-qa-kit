#!/bin/sh
# Subcommands for the container. Anything after the subcommand is passed through.
set -eu
cmd="${1:-test}"
[ "$#" -gt 0 ] && shift

START="${START:-$(python -c 'import datetime as d; print(d.date.today()-d.timedelta(days=365))')}"
END="${END:-$(python -c 'import datetime as d; print(d.date.today())')}"
MIN_MAG="${MIN_MAG:-5}"
RADIUS_KM="${RADIUS_KM:-100}"

case "$cmd" in
  test)
    exec python -m pytest "$@"
    ;;
  demo)
    exec python -m pipeline.run \
      --events tests/fixtures/earthquakes_sample.geojson \
      --cities tests/fixtures/cities_sample.geojson \
      --out output/fixture_results.geojson "$@"
    ;;
  pipeline)
    python scripts/download_data.py --start "$START" --end "$END" --min-mag "$MIN_MAG"
    python -m pipeline.run \
      --events "data/raw/usgs_m${MIN_MAG}_${START}_${END}.geojson" \
      --cities zip://data/raw/ne_10m_populated_places_simple.zip \
      --out output/events_with_cities.geojson --radius-km "$RADIUS_KM" --min-mag "$MIN_MAG" "$@"
    exec python scripts/oracle_check.py output/events_with_cities.geojson \
      zip://data/raw/ne_10m_populated_places_simple.zip "$RADIUS_KM"
    ;;
  *)
    exec "$cmd" "$@"   # escape hatch, e.g. `docker run -it drqa:dev bash`
    ;;
esac
