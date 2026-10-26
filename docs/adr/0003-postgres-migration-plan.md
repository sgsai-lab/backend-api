# ADR-003: Firestore → PostgreSQL migration path (spike)

- Status: Proposed (spike result, API-19 #24). Production migration needs a separate decision.
- Context: [ADR-002 alignment](0002-firestore-first-alignment.md)

## What the spike proves

| Step | Artifact | Verified by |
| --- | --- | --- |
| Schema for `clients`, `memberships`, `projects`, `products`, `assets` | `app/modules/hub/models.py`, `migrations/versions/20261101_0001_client_hub.py` | `alembic upgrade head` → `downgrade base` → `upgrade head`; `alembic check` reports no drift |
| Firestore document → row mapping | `app/modules/hub/migration.py` (pure functions) | `tests/unit/test_hub_contract.py` |
| Import | `scripts/migrate_firestore.py` (`app/modules/hub/load.py`): one transaction, upsert, idempotent, `--dry-run` | `tests/integration/test_hub_load.py`, CLI run twice on the fixture |
| Same JSON as `home` | Spike read routes `GET /api/v1/clients/{id}`, `/projects/{id}`, `/products` (local/test only) | `tests/integration/test_hub_api.py` replays recorded `home` responses byte-for-byte, plus tenant isolation (404) and error envelope |
| Recorded contract | `scripts/record_home_contract.mjs` runs `home`'s API in memory and writes `tests/fixtures/home_contract.json` | Re-run after any `home` contract change |

## Mapping rules

- Firestore document ids become primary keys, so URLs, ETags (`"v{version}"`), audit references and GCS object paths stay valid.
- ISO-8601 strings become `timestamptz`; serializers emit JavaScript `toISOString()` format (UTC, milliseconds, `Z`). `YYYY-MM-DD` strings become `date`.
- Nested maps (`contact`, `branding`, `sector_profile`, `store_urls`) and `milestones` stay JSONB; `tags` is `varchar[]`; product `order` is `sort_order`.
- Skipped: memberships that are not `active`, assets that are not `ready` (pending uploads are deleted by the bucket lifecycle anyway). The loader reports every skipped document.
- Not migrated by the spike: `users`, sessions, invites, launch tokens, audit log. Sessions and launch tokens are short-lived (users sign in again after cut-over); users and invites move with the auth work (API-09…13); audit log is exported to BigQuery/GCS instead of copied.
- Media never moves: rows keep `gcs_bucket`/`gcs_object`, and the bucket stays the store of record.

## Options considered

| Option | Verdict |
| --- | --- |
| Big-bang export → import during a short write freeze | **Chosen.** Data volume is small (hundreds of documents); a 15-minute read-only window is acceptable. |
| Dual-write from `home` to both stores | Rejected: two writers, partial-failure handling, and a second code path in `home` for a short-lived benefit. |
| Dual-read (Postgres first, Firestore fallback) | Rejected for writes; useful only as a shadow-read check before cut-over (compare responses, do not serve them). |

## Cut-over checklist

1. Auth (API-09…13) implemented with `home` token semantics and contract tests green against a fresh recording.
2. Export: `gcloud firestore export gs://<backup-bucket>/cutover-<date>` (also the rollback point), convert to `{"collections": {...}}` JSON.
3. Put `home` in read-only mode for `/api/v1` mutations (feature flag returning `503 SERVICE_UNAVAILABLE` with `Retry-After`).
4. `alembic upgrade head`, then `python scripts/migrate_firestore.py export.json --dry-run`, then without `--dry-run`. Compare counts with the export.
5. Shadow-read: replay a sample of production `GET`s against both upstreams and diff.
6. Switch `API_UPSTREAM` in `home`'s Nginx (`/api/v1/` → this service), deploy, smoke test web and mobile sign-in, workspace, launch.
7. Keep Firestore read-only for 14 days.

**Rollback:** point `API_UPSTREAM` back to `home` and lift read-only mode. Any writes made on Postgres after cut-over must be replayed by hand, so roll back within the first hour or not at all.

## Follow-ups

- `home`: add the `/api/v1` read-only switch used in cut-over step 3 (does not exist yet).
- Re-scope #14–#16 to the client-scoped model (ADR-002 §3) before resuming.
- Add `users`/`invites` tables with the auth work; add the `memberships.user_id` foreign key then.
- Convert the `gcloud firestore export` format (LevelDB) to JSON: use the Admin SDK reader in `home` (`queryDocs`) or `firestore-export` tooling; decide when cut-over is scheduled.
