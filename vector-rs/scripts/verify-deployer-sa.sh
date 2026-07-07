#!/usr/bin/env bash
#
# Read-only check that the GitHub Actions deployer SA can build + deploy the
# vector-rs PR previews (.github/workflows/vector-rs-pr-preview.yml). Makes NO
# changes. Run with an account that can read project IAM (e.g. project Owner):
#   bash vector-rs/scripts/verify-deployer-sa.sh
#
# The roles checked here are exactly what .github/setup-wif.sh grants; if any are
# missing, re-run that script to reconcile.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-cloud-crate-485418}"
SA_EMAIL="${SA_EMAIL:-gha-sonar-deployer@${PROJECT_ID}.iam.gserviceaccount.com}"
SERVICE="${SERVICE:-cloud-crate-vector-rs}"
REGION="${REGION:-us-central1}"

command -v gcloud >/dev/null 2>&1 || { echo "❌ gcloud not found." >&2; exit 1; }

echo "Project: $PROJECT_ID"
echo "SA:      $SA_EMAIL"
echo

roles_file="$(mktemp)"
trap 'rm -f "$roles_file"' EXIT
gcloud projects get-iam-policy "$PROJECT_ID" \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:${SA_EMAIL}" \
  --format="value(bindings.role)" | sort -u > "$roles_file"

echo "== Required project roles for vector-rs preview build+deploy =="
ok=1
for ROLE in \
  roles/run.developer \
  roles/cloudbuild.builds.editor \
  roles/storage.admin \
  roles/iam.serviceAccountUser; do
  if grep -qx "$ROLE" "$roles_file"; then
    echo "  ✓ $ROLE"
  else
    echo "  ✗ MISSING $ROLE"; ok=0
  fi
done

echo
echo "== act-as the Cloud Run runtime (default compute) SA =="
PN="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="${PN}-compute@developer.gserviceaccount.com"
# Project-level roles/iam.serviceAccountUser (checked above) already covers
# act-as for every SA in the project; this confirms the specific binding too.
if grep -qx "roles/iam.serviceAccountUser" "$roles_file"; then
  echo "  ✓ project-level serviceAccountUser covers act-as $RUNTIME_SA"
else
  echo "  ? no project-level serviceAccountUser — checking the runtime SA directly..."
  gcloud iam service-accounts get-iam-policy "$RUNTIME_SA" --project "$PROJECT_ID" \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:${SA_EMAIL}" \
    --format="value(bindings.role)" | grep -q "serviceAccountUser" \
      && echo "  ✓ direct act-as binding present on $RUNTIME_SA" \
      || { echo "  ✗ cannot act-as $RUNTIME_SA"; ok=0; }
fi

echo
echo "== Target service (previews tag an existing service) =="
if url="$(gcloud run services describe "$SERVICE" --region "$REGION" \
          --project "$PROJECT_ID" --format='value(status.url)' 2>/dev/null)" && [ -n "$url" ]; then
  echo "  ✓ $SERVICE exists ($url)"
else
  echo "  (i) $SERVICE not found — the first preview creates it; deploy.sh covers prod."
fi

echo
echo "== GitHub repository Variables (needed by the workflows) =="
echo "  Confirm these exist under Settings → Secrets and variables → Actions → Variables:"
echo "    WIF_PROVIDER, WIF_SERVICE_ACCOUNT (= $SA_EMAIL)"

echo
if [[ "$ok" -eq 1 ]]; then
  echo "✅ Deployer SA has the roles vector-rs previews need."
else
  echo "‼️  Missing roles above — re-run .github/setup-wif.sh to grant them."
  exit 1
fi
