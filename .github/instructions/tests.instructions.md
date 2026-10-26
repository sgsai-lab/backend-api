---
applyTo: "tests/**/*.py"
description: "pytest conventions for unit and integration tests of the FastAPI service."
---
# Tests

- pytest + pytest-asyncio (`asyncio_mode=auto` — no `@pytest.mark.asyncio` needed). HTTP via the `client` fixture (`httpx.AsyncClient` + `ASGITransport`) from `tests/conftest.py`.
- `tests/unit/`: no network, no DB; patch at the import site (`patch("app.api.health.get_engine", ...)`).
- `tests/integration/`: real Postgres (compose on `localhost:5433`, CI service on `5432`), mark with `pytestmark = pytest.mark.integration`. Never mock the database.
- One behaviour per test; name `test_<action>_<condition>_<expected>`; Arrange / Act / Assert separated by blank lines.
- Every endpoint must cover: happy path, validation error (400 `VALIDATION_ERROR` envelope), unauthenticated (401), another user's resource (404), and conflict/edge cases.
- Assert on the error envelope `response.json()["error"]["code"]`, not on message text.
- Use factories/fixtures for users and auth headers; never hardcode real secrets. Test emails use `InMemoryEmailSender`.
- Do not assert on log output except in redaction tests.
- Keep tests deterministic: freeze time for token/OTP expiry (`time-machine`), no sleeps.
