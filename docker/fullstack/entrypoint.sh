#!/usr/bin/env bash
# Runs API, contact server and nginx; exits when any stops so the platform restarts the container.
set -uo pipefail

PORT=8000 python -m app &
pids=($!)
node /app/webapp/server.mjs &
pids+=($!)
nginx -g 'daemon off;' &
pids+=($!)

trap 'kill -TERM "${pids[@]}" 2>/dev/null' TERM INT
wait -n
exit_code=$?
kill -TERM "${pids[@]}" 2>/dev/null
wait
exit "$exit_code"
