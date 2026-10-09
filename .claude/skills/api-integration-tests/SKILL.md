---
name: api-integration-tests
description: "Write pytest integration tests for FastAPI endpoints against a real Postgres, including auth, authorization (IDOR), validation, pagination and error-envelope assertions. Use when asked to 'add tests', 'test this endpoint', 'increase coverage', or when implementing any new endpoint."
---

# API integration tests

## Setup (once)

Integration fixtures live in `tests/integration/conftest.py`. If absent, create them as in [fixtures.md](./references/fixtures.md): per-test transaction rollback on a real Postgres, `user_factory`, `auth_headers`, and in-memory email capture.

Run locally:

```bash
docker compose up -d db && make migrate
uv run pytest tests/integration -m integration -q
```

## Test matrix — cover for every endpoint

| Case | Expectation |
| --- | --- |
| Happy path | status code, body shape, `Location` on 201 |
| No / invalid / expired token | 401, `UNAUTHENTICATED` / `TOKEN_EXPIRED` |
| Another user's resource | 404 (not 403), for GET/PATCH/DELETE |
| Body with forbidden fields (`owner_id`, `role`, `id`) | 422 `VALIDATION_ERROR` |
| Boundary values (min/max length, page_size 0/101) | 422 |
| Unique conflict | 409 `CONFLICT` |
| Soft-deleted resource | 404, excluded from lists |
| Filters / sort / pagination | correct subset, order, `total` |
| Admin-only route as normal user | 403 `FORBIDDEN` |
| Rate-limited route (auth) | 429 `RATE_LIMITED` with `Retry-After` |

## Auth-flow specifics

- Assert identical responses for "unknown email" vs "wrong password" and for forgot-password on unknown email.
- Assert tokens are single use (second use fails) and expire (use `time-machine` to travel).
- Assert no token/password appears in captured logs for sensitive flows (`structlog.testing.capture_logs`).

## Style

- `test_<action>_<condition>_<expected>`; AAA blocks; one behaviour per test; parametrize method/role variants.
- Assert on `error.code`, never on message text.
