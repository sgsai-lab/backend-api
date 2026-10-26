# ADR-002 alignment: `home` owns `/api/v1` for now

- Status: Accepted (2026-10-27, founder)
- Upstream decision: [sgsai-lab/home ADR-002](https://github.com/sgsai-lab/home/blob/main/docs/adr/0002-firestore-first-data-platform.md)
- Related: ADR-001 (#7, backend-owned auth), API-18 (#23), API-19 (#24)

## Context

`home` now serves the client hub (`/api/v1`) on Firestore for both the website and the mobile app. This service planned the same resources on PostgreSQL as **per-user** resources (#14–#17). Building both unchanged would give two incompatible contracts and turn the later `API_UPSTREAM` switch into a rewrite.

## Decision

1. `home` is the system of record for `/api/v1` until a new decision says otherwise (initially six weeks). Its [`docs/api.md`](https://github.com/sgsai-lab/home/blob/main/docs/api.md) and [`docs/data-model.md`](https://github.com/sgsai-lab/home/blob/main/docs/data-model.md) are the contract.
2. Feature work on API-07…API-16 (email, auth, users, projects, products, hardening) is **paused**. API-02…API-05 (health, container, CI, deploy) stay green.
3. When work resumes, resources are **client-scoped**, not per-user:
   - every tenant resource carries `client_id`; access is by active membership (`viewer < member < admin < owner`), SGS admins act as owners;
   - other tenants' data answers `404`, never `403` with details;
   - products have `kind`, `launch_url`, `store_urls`, `visibility`, `order`; assets are metadata pointing at GCS objects.
4. Route paths, JSON field names (snake_case), list shape `{items, total, page, page_size}` and the error envelope are identical to `home`:
   `{"error": {"code", "message", "details": [{"field", "message"}], "request_id"}}` with codes `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `VALIDATION_ERROR` (400), `RATE_LIMITED`. This repo's envelope was changed to match in this PR.
5. Auth (ADR-001) keeps its design but is implemented with `home`'s token semantics (1 h access token, rotating single-use refresh tokens with family revocation, `X-Client: mobile`) so mobile clients do not change.
6. The only active Postgres work is the migration spike (#24, [ADR-003](0003-postgres-migration-plan.md)).

## Consequences

- #14/#15/#16 must be re-scoped to the client-scoped model before they resume.
- Contract drift is caught by replaying responses recorded from `home` (`tests/fixtures/home_contract.json`).
- One database per environment until cut-over; no dual writes.
