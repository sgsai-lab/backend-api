#!/usr/bin/env bash
# Copies the Google OAuth client ID(s) from Secret Manager into .env for local Google sign-in.
# Usage: scripts/google-client-id.sh [PROJECT_ID]   (default: gcloud's configured project)
set -euo pipefail

PROJECT="${1:-${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}}"
SECRET="${GOOGLE_CLIENT_SECRET_NAME:-GOOGLE_OAUTH_CLIENT_IDS}"
ENV_FILE="${ENV_FILE:-.env}"
[[ -n "$PROJECT" ]] || { echo "No GCP project: pass one or run 'gcloud config set project <id>'." >&2; exit 1; }

if ! IDS=$(gcloud secrets versions access latest --secret="$SECRET" --project="$PROJECT" 2>&1); then
  echo "Could not read secret $SECRET in $PROJECT:" >&2
  echo "$IDS" >&2
  echo "If gcloud asks to reauthenticate, run: gcloud auth login" >&2
  exit 1
fi

# The secret is a JSON list (backend format); the first entry is the web client used by the browser button.
python3 - "$ENV_FILE" "$IDS" <<'PY'
import json, pathlib, re, sys

env_path, raw = pathlib.Path(sys.argv[1]), sys.argv[2].strip()
ids = json.loads(raw) if raw.startswith("[") else [raw]
ids = [i.strip() for i in ids if isinstance(i, str) and i.strip()]
if not ids or not all(re.fullmatch(r"[\w.-]+\.apps\.googleusercontent\.com", i) for i in ids):
    sys.exit("Secret does not contain Google OAuth client IDs (*.apps.googleusercontent.com).")

values = {"GOOGLE_CLIENT_ID": ids[0], "GOOGLE_OAUTH_CLIENT_IDS": json.dumps(ids, separators=(",", ":"))}
lines = env_path.read_text().splitlines() if env_path.exists() else []
for key, value in values.items():
    entry = f"{key}={value}"
    index = next((n for n, line in enumerate(lines) if line.startswith(f"{key}=")), None)
    if index is None:
        lines.append(entry)
    else:
        lines[index] = entry
env_path.write_text("\n".join(lines) + "\n")
print(f"Wrote GOOGLE_CLIENT_ID={ids[0]} and GOOGLE_OAUTH_CLIENT_IDS ({len(ids)} id(s)) to {env_path}")
PY

echo "Restart to apply: docker compose up -d api webapp"
echo "Ensure http://localhost:3000 is an Authorized JavaScript origin on this OAuth client."
