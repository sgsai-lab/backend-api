#!/usr/bin/env bash
# Enables TOTP MFA for an account on the local API. Run interactively; secrets stay in this terminal.
set -euo pipefail

API="${API:-http://localhost:8080/api/v1}"
read -rp "Email: " EMAIL
read -rsp "Password: " PASSWORD; echo

json() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }

LOGIN=$(curl -fsS -X POST "$API/auth/login" -H 'content-type: application/json' \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"email": sys.argv[1], "password": sys.argv[2]}))' "$EMAIL" "$PASSWORD")")
unset PASSWORD
if [[ "$(echo "$LOGIN" | json '.get("mfa_required", False)')" == "True" ]]; then
  echo "MFA is already enabled for $EMAIL."; exit 0
fi
TOKEN=$(echo "$LOGIN" | json '["access_token"]')
AUTH=(-H "Authorization: Bearer $TOKEN" -H 'content-type: application/json')

SETUP=$(curl -fsS -X POST "$API/auth/mfa/totp/setup" "${AUTH[@]}")
URI=$(echo "$SETUP" | json '["otpauth_uri"]')
echo
if command -v qrencode >/dev/null; then
  qrencode -t ANSIUTF8 "$URI"
else
  echo "Add this account to your authenticator app (Google Authenticator, Authy, 1Password):"
  echo "  Secret key: $(echo "$SETUP" | json '["secret"]')"
  echo "  Or URI:     $URI"
fi
echo
for attempt in 1 2 3; do
  read -rp "Enter the 6-digit code from the app: " CODE
  CODE="${CODE//[^0-9]/}"
  if [[ ${#CODE} -ne 6 ]]; then echo "Code must be 6 digits."; continue; fi
  CONFIRM=$(curl -sS -w '\n%{http_code}' -X POST "$API/auth/mfa/totp/confirm" "${AUTH[@]}" -d "{\"code\":\"$CODE\"}")
  STATUS=$(echo "$CONFIRM" | tail -1)
  [[ "$STATUS" == "200" ]] && break
  echo "Confirmation failed ($STATUS): $(echo "$CONFIRM" | head -1)"
  echo "Wait for the next code and try again (attempt $attempt/3)."
done
[[ "${STATUS:-}" == "200" ]] || exit 1
echo
echo "MFA enabled. Store these recovery codes somewhere safe (shown once):"
echo "$CONFIRM" | head -1 | python3 -c "import json,sys; [print('  ' + c) for c in json.load(sys.stdin)['recovery_codes']]"
