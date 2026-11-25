#!/bin/sh
# Start one Lamikraft One backend process. LK_PROCESS=api (default) or worker.
# The API applies migrations as the owner role before serving; the worker never migrates.
set -eu

case "${LK_PROCESS:-api}" in
  api)
    python -m app.cli db migrate
    exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers \
      --forwarded-allow-ips "${LK_FORWARDED_ALLOW_IPS:-*}" --workers "${LK_API_WORKERS:-2}"
    ;;
  worker)
    exec python -m app.worker
    ;;
  *)
    echo "LK_PROCESS must be api or worker, got ${LK_PROCESS}" >&2
    exit 2
    ;;
esac
