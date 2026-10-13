# ADR-001: Firebase identity for mobile clients

**Status:** Accepted for mobile; backend-issued sessions remain supported for existing clients.

## Context

APP-07 selected Firebase Authentication as the identity source for the mobile app.
Firebase owns mobile sign-in, ID-token refresh and local sign-out. The backend still
owns local user records, roles, account status and authorization decisions.

## Decision

- The mobile app signs in with Firebase Auth and sends the Firebase ID token as
  its bearer token on API requests.
- `POST /api/v1/auth/firebase` verifies the token and creates or links an
  `OAuthAccount(provider="firebase", provider_subject=<uid>)` record. An existing
  local account is linked by email only when its email is already verified.
- Authenticated requests verify Firebase signature, issuer, audience, expiry and
  revocation through Firebase Admin. A verified Firebase UID must map to an active
  local user; request bodies never identify the caller.
- Firebase ID tokens are not exchanged for backend JWTs on the mobile path.
  Existing ES256 access/rotating-refresh sessions continue for web and legacy
  clients during migration.
- Firebase logout revokes the user's Firebase refresh tokens and signs out the
  local SDK. Firebase currently exposes user-wide revocation, so this logs out all
  devices rather than one individual device session.
- The backend uses Application Default Credentials/Workload Identity to verify
  revocation. It requires only the non-secret `FIREBASE_PROJECT_ID`; no service
  account key is stored in the repository.
- Mobile Firebase ID tokens are persisted/refreshed only by the Firebase SDK.
  Native Firebase config files are supplied per environment and remain outside Git.

## Consequences

- Each backend environment must use the matching Firebase project ID. The mobile
  flavor's native Firebase project and API URL must target the same environment.
- Firebase users must have verified email before first provisioning. Unverified
  existing local accounts cannot be linked by email.
- Backend password, MFA and session-management endpoints remain available for
  legacy ES256 users; Firebase Auth users use Firebase's provider and MFA flows.
- Firebase project registration, provider enablement, ADC/IAM permissions, native
  config files, and tester provisioning are external setup tasks tracked by APP-04.
