# Copilot instructions

The single source of truth for AI agent guidance in this repo is [AGENTS.md](../AGENTS.md) — follow it for all chat, agent, and code review work.

Path-specific rules: [.github/instructions/](instructions/). Reusable workflows (skills): [.claude/skills/](../.claude/skills/).

When reviewing PRs, prioritise: owner-scoped queries (IDOR → 404), no identity from request body, `extra="forbid"` request schemas, no secrets/tokens in logs or responses, reversible zero-downtime migrations, and tests for auth-failure and cross-user cases.
