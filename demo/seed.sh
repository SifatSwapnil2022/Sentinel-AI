#!/bin/sh
# Create keys for the demo, then stream the scenarios into the API (see simulate.py).
set -eu
admin=$(sentinel-admin create-key --name demo-admin --scope admin)
ingest=$(sentinel-admin create-key --name demo-ingest --scope ingest)
exec python /app/demo/simulate.py --url "$SENTINEL_URL" --admin-key "$admin" --ingest-key "$ingest" "$@"
