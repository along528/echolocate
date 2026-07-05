#!/bin/bash
# One-time setup: keyless GitHub Actions -> GCP auth via Workload Identity Federation,
# plus a deployer service account with the roles the sonar workflows need.
#
# Run once, locally, with an account that has project Owner (or IAM + enable-services
# admin). Idempotent — safe to re-run. After it finishes, add the two printed values as
# GitHub *repository variables*: WIF_PROVIDER and WIF_SERVICE_ACCOUNT
# (Settings -> Secrets and variables -> Actions -> Variables).
set -euo pipefail

PROJECT_ID="cloud-crate-485418"
REPO="along528/echolocate"          # owner/name — only this repo's Actions can impersonate the SA
POOL="github-actions"
PROVIDER="github"
SA_NAME="gha-sonar-deployer"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

echo ">> Enabling required APIs..."
gcloud services enable \
  iamcredentials.googleapis.com \
  iam.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  --project "$PROJECT_ID"

echo ">> Creating deployer service account (if missing)..."
gcloud iam service-accounts describe "$SA_EMAIL" --project "$PROJECT_ID" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" \
    --project "$PROJECT_ID" \
    --display-name "GitHub Actions sonar deployer"

echo ">> Granting project roles to the deployer SA..."
for ROLE in \
  roles/run.developer \
  roles/cloudbuild.builds.editor \
  roles/iam.serviceAccountUser \
  roles/storage.admin \
  roles/viewer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${SA_EMAIL}" \
    --role "$ROLE" \
    --condition=None >/dev/null
done
# Cloud Run runtime SA (default compute SA) — deployer must act-as it to deploy.
gcloud iam service-accounts add-iam-policy-binding \
  "${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:${SA_EMAIL}" \
  --role roles/iam.serviceAccountUser >/dev/null || true

echo ">> Creating Workload Identity pool + provider (if missing)..."
gcloud iam workload-identity-pools describe "$POOL" \
  --project "$PROJECT_ID" --location global >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools create "$POOL" \
    --project "$PROJECT_ID" --location global \
    --display-name "GitHub Actions"

gcloud iam workload-identity-pools providers describe "$PROVIDER" \
  --project "$PROJECT_ID" --location global --workload-identity-pool "$POOL" >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
    --project "$PROJECT_ID" --location global \
    --workload-identity-pool "$POOL" \
    --display-name "GitHub" \
    --issuer-uri "https://token.actions.githubusercontent.com" \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition "assertion.repository=='${REPO}'"

POOL_ID="$(gcloud iam workload-identity-pools describe "$POOL" \
  --project "$PROJECT_ID" --location global --format='value(name)')"

echo ">> Binding the GitHub repo principal to the deployer SA..."
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --project "$PROJECT_ID" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/${POOL_ID}/attribute.repository/${REPO}" >/dev/null

PROVIDER_RESOURCE="$(gcloud iam workload-identity-pools providers describe "$PROVIDER" \
  --project "$PROJECT_ID" --location global --workload-identity-pool "$POOL" \
  --format='value(name)')"

cat <<MSG

==========================================================================
Done. Add these as GitHub repository *Variables* (not Secrets):
  Settings -> Secrets and variables -> Actions -> Variables -> New variable

  WIF_PROVIDER         = ${PROVIDER_RESOURCE}
  WIF_SERVICE_ACCOUNT  = ${SA_EMAIL}

Then redeploy vector-rs once so the new CORS predicate takes effect:
  cd vector-rs && ./deploy.sh
==========================================================================
MSG
