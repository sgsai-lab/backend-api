---
name: implement-github-issue
description: "End-to-end workflow to implement a GitHub issue (API-xx) in backend-api: read issue, branch, implement, test, commit, open PR. Use when asked to 'work on issue #N', 'implement API-14', 'pick up the next task', or 'start the ticket'."
argument-hint: "Issue number, e.g. 14"
---

# Implement a GitHub issue

## Procedure

1. **Read the issue** — `gh issue view <N> --comments`. Extract tasks, endpoints, data model, security requirements, acceptance criteria and "Depends on". If a dependency is still open, check whether the needed code exists (`grep`/search) and tell the user before proceeding.
2. **Sync and branch** from `develop` (fallback `main`):

   ```bash
   git fetch origin && git switch develop && git pull --ff-only
   git switch -c <type>/<N>-<short-slug>   # feat/14-projects-crud, fix/22-refresh-reuse
   ```

3. **Plan** — list files to add/change. Use sibling skills:
   - New resource → `fastapi-crud-module`
   - Schema change → `alembic-migration`
   - Auth / tokens / passwords / MFA → `auth-security-review` (before opening the PR)
   - Tests → `api-integration-tests`
4. **Implement** in small steps following [AGENTS.md](../../../AGENTS.md) and `.github/instructions/*`. Add new settings to `Settings` **and** `.env.example`.
5. **Verify**:

   ```bash
   docker compose up -d db mailpit
   make migrate && make check
   ```

   Fix all failures; do not skip or `xfail` tests to get green.
6. **Tick the issue checklist** only for tasks actually done (`gh issue edit` or comment).
7. **Commit** with conventional commits, small and focused:
   `feat(projects): add owner-scoped CRUD endpoints` + body `Refs #<N>`.
8. **Push and open a draft PR** (confirm with the user before pushing):

   ```bash
   git push -u origin HEAD
   gh pr create --draft --base develop --title "<type>(<scope>): <summary>" --body-file <tmp>
   ```

   PR body: summary, `Closes #<N>`, checklist of acceptance criteria with evidence (tests, curl output), migration notes, security notes, follow-ups.

## Done when

- Every acceptance criterion is demonstrably met (test or manual evidence in the PR).
- `make check` passes; migration up/down/up works.
- OpenAPI (`/docs`) shows the new endpoints with request/response/error schemas.
