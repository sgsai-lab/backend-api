---
name: cloud-run-deploy
description: "Build, deploy, migrate, roll back and troubleshoot the backend on GCP Cloud Run with Cloud SQL, Secret Manager and Artifact Registry. Use when asked to 'deploy', 'roll back', 'add a secret/env var', 'check logs', 'why is Cloud Run failing', 'readyz 503', 'too many connections'."
argument-hint: "Environment (development|staging|production) and action"
---

# Cloud Run deploy & operations

Normal path is CI (`develop` → development). Use manual commands only for debugging or emergencies, and **confirm with the user before any command that changes a shared environment**.

## Conventions

| Item | Value |
| --- | --- |
| Service | `backend-api` |
| Project / region | `home-509818` / `asia-south1` (shared with `sgsai-lab/home`; repo variables `GCP_*`) |
| Image | `${REGION}-docker.pkg.dev/${PROJECT}/sgsai-images/backend-api:<git-sha>` |
| Migration job | `backend-api-migrate` (same image, `alembic upgrade head`) |
| Deploy SA (WIF) | `sgsai-github-deploy@home-509818.iam.gserviceaccount.com` |
| Runtime SA | `GCP_RUNTIME_SERVICE_ACCOUNT` (currently `sgs-ai-website-runtime@home-509818.iam.gserviceaccount.com`) |
| Secrets | `DATABASE_URL`, `JWT_PRIVATE_KEY`, `MFA_ENCRYPTION_KEY`, `EMAIL_API_KEY`, `GOOGLE_OAUTH_CLIENT_IDS` |
| Limits | `--max-instances 3 --min-instances 0 --memory 512Mi --timeout 60s`, `DB_POOL_SIZE=5` |

## Deploy (manual)

```bash
SHA=$(git rev-parse HEAD)
PROJECT=home-509818 REGION=asia-south1
IMAGE=${REGION}-docker.pkg.dev/${PROJECT}/sgsai-images/backend-api:${SHA}
gcloud run jobs update backend-api-migrate --image "$IMAGE" --region "$REGION"
gcloud run jobs execute backend-api-migrate --region "$REGION" --wait
gcloud run deploy backend-api --image "$IMAGE" --region "$REGION" \
  --service-account sgs-ai-website-runtime@${PROJECT}.iam.gserviceaccount.com \
  --set-secrets DATABASE_URL=DATABASE_URL:latest,JWT_PRIVATE_KEY=JWT_PRIVATE_KEY:latest \
  --set-env-vars ENVIRONMENT=development,LOG_JSON=true
curl -fsS "$(gcloud run services describe backend-api --region "$REGION" --format 'value(status.url)')/readyz"
```

## Rollback

```bash
gcloud run revisions list --service backend-api --region "$REGION" --limit 5
gcloud run services update-traffic backend-api --region "$REGION" --to-revisions <PREVIOUS_REVISION>=100
```

Migrations are not rolled back automatically — because they are backwards compatible, the previous revision keeps working. Only run `alembic downgrade` deliberately.

## Add a config value or secret

1. Add to `Settings` + `.env.example`.
2. Non-secret → `--set-env-vars` in the deploy workflow. Secret → create in Secret Manager, grant `roles/secretmanager.secretAccessor` to the runtime SA, add to `--set-secrets`.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Revision fails to start | `gcloud run services logs read backend-api --region $REGION --limit 100` — usually a missing env var (pydantic `ValidationError`) |
| `/readyz` 503 | Cloud SQL connectivity (VPC egress / connector), `DATABASE_URL`, SA has `roles/cloudsql.client` |
| `too many connections` | `max-instances × (DB_POOL_SIZE + DB_MAX_OVERFLOW)` + migration job vs Cloud SQL `max_connections` |
| 401 everywhere after deploy | `JWT_*` secret mismatch / key rotation without overlap |
| Emails not sent | `EMAIL_API_KEY`, provider dashboard, CPU throttling if sending after response |
| Find a request | Logs Explorer: `jsonPayload.request_id="<X-Request-ID>"` |
