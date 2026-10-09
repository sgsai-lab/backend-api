---
name: auth-security-review
description: "Security review checklist for authentication and authorization code: signup, login, JWT/refresh tokens, Google sign-in, password reset, MFA/TOTP, sessions, rate limiting, IDOR, secrets and logging (OWASP ASVS / API Top 10). Use before merging any auth/security change, or when asked to 'security review', 'audit auth', 'check for vulnerabilities'."
---

# Auth & API security review

## Procedure

1. List changed files: `git diff --name-only origin/develop...HEAD`.
2. Walk through every section of the checklist that applies; for each item record ✅ / ❌ with file:line evidence.
3. Fix ❌ items (or open follow-up issues for non-blocking ones, labelled `type:security`).
4. Add tests that prove each security property (negative cases).
5. Paste the filled checklist in the PR description.

## Checklist

### Authentication

- [ ] Passwords hashed with Argon2id; rehash on login if params changed; never logged.
- [ ] Unknown email and wrong password return the same error and similar timing (dummy hash verify).
- [ ] Account lockout / progressive delay after repeated failures; rate limits per IP and per account.
- [ ] Signup / forgot-password / resend never reveal whether an account exists.

### Tokens

- [ ] Access JWT: ES256, `kid`, verifies `exp`, `iss`, `aud`, `typ`; `alg` pinned (no `none`, no HS/RS confusion); ≤ 15 min.
- [ ] Refresh tokens opaque, stored hashed, rotated on every use, reuse → revoke family.
- [ ] One-time tokens (verify, reset, MFA challenge): `secrets.token_urlsafe(32)`, stored hashed, single use (`FOR UPDATE`), short expiry, invalidated on new issue.
- [ ] Password change/reset and MFA disable revoke sessions.
- [ ] Token responses send `Cache-Control: no-store`.
- [ ] Web refresh cookie: `__Host-`, `HttpOnly`, `Secure`, `SameSite=Strict`, CSRF/Origin check.

### Google sign-in

- [ ] ID token verified server-side (`aud` in our client IDs, `iss`, `exp`, `email_verified`, `nonce`).
- [ ] Linking to an existing account only when the local email is verified.

### MFA

- [ ] TOTP secret encrypted at rest; replay of the same time-step rejected; attempt limits per challenge.
- [ ] Recovery codes hashed, single use, shown once.
- [ ] MFA enforced for Google logins as well as password logins.

### Authorization (OWASP API1/API3/API5)

- [ ] User identity only from the verified token; no `user_id`/`owner_id` from body/query (except admin filters).
- [ ] Every query owner-scoped; foreign resources → 404.
- [ ] Response models exclude sensitive fields; request models `extra="forbid"` (no mass assignment of `role`, `status`, `email_verified_at`).
- [ ] Admin routes check role (and `mfa` in `amr` once available).

### Input, output, logging

- [ ] All input validated with bounded Pydantic fields; list `page_size` capped; sort whitelisted; LIKE wildcards escaped.
- [ ] No raw SQL string building.
- [ ] Errors use the envelope; no stack traces/SQL/hostnames leaked; validation errors don't echo input.
- [ ] No secrets, tokens, OTPs, passwords, recovery codes in logs (test with `structlog.testing.capture_logs`).
- [ ] Security events written to the audit log.

### Config & secrets

- [ ] New secrets read via `Settings` and provided by Secret Manager; added to `.env.example` with dummy values only.
- [ ] No credentials committed (`git diff` scan; consider `detect-secrets`).
- [ ] Dependencies added are maintained and pinned in `uv.lock`; `pip-audit` clean.
