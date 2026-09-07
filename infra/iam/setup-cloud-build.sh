#!/bin/sh
set -eu

PROJECT_ID="${1:-tfm-sgciu}"
REGION="${2:-us-central1}"
REPOSITORY="${3:-sgciu}"
TRIGGER_NAME="${4:-sgciu-production-main}"
BUILD_SERVICE_ACCOUNT_ID="sgciu-cloud-build"
RUNTIME_SERVICE_ACCOUNT_ID="sgciu-runtime"
COORDINATOR_ROLE_ID="sgciuCloudBuildCoordinator"
RESOURCE_ROLE_ID="sgciuCloudRunResourceDeployer"
SCRIPT_DIR=$(dirname -- "$0")
SCRIPT_DIR=$(CDPATH='' cd -- "$SCRIPT_DIR" && pwd)
IMAGE_TAG_SUBSTITUTION="_IMAGE_TAG=\$SHORT_SHA"

BUILD_SERVICE_ACCOUNT="${BUILD_SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SERVICE_ACCOUNT_RESOURCE="projects/${PROJECT_ID}/serviceAccounts/${BUILD_SERVICE_ACCOUNT}"
COORDINATOR_ROLE="projects/${PROJECT_ID}/roles/${COORDINATOR_ROLE_ID}"
RESOURCE_ROLE="projects/${PROJECT_ID}/roles/${RESOURCE_ROLE_ID}"

ensure_role() {
  role_id=$1
  role_file=$2
  if gcloud iam roles describe "$role_id" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam roles update "$role_id" \
      --project="$PROJECT_ID" \
      --file="$role_file" \
      --quiet
  else
    gcloud iam roles create "$role_id" \
      --project="$PROJECT_ID" \
      --file="$role_file" \
      --quiet
  fi
}

if ! gcloud iam service-accounts describe "$BUILD_SERVICE_ACCOUNT" \
  --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$BUILD_SERVICE_ACCOUNT_ID" \
    --project="$PROJECT_ID" \
    --display-name="SGCIU Cloud Build deployer"
fi

ensure_role "$COORDINATOR_ROLE_ID" "$SCRIPT_DIR/cloud-build-coordinator-role.yaml"
ensure_role "$RESOURCE_ROLE_ID" "$SCRIPT_DIR/cloud-run-resource-deployer-role.yaml"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SERVICE_ACCOUNT" \
  --role="$COORDINATOR_ROLE" \
  --condition=None \
  --quiet >/dev/null

for service in sgciu-backend sgciu-frontend; do
  gcloud run services add-iam-policy-binding "$service" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --member="serviceAccount:$BUILD_SERVICE_ACCOUNT" \
    --role="$RESOURCE_ROLE" \
    --quiet >/dev/null
done

for job in sgciu-migrate sgciu-provision-users sgciu-index-legal-corpus; do
  gcloud run jobs add-iam-policy-binding "$job" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --member="serviceAccount:$BUILD_SERVICE_ACCOUNT" \
    --role="$RESOURCE_ROLE" \
    --quiet >/dev/null
done

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SERVICE_ACCOUNT" \
  --role="roles/logging.logWriter" \
  --condition=None \
  --quiet >/dev/null

gcloud artifacts repositories add-iam-policy-binding "$REPOSITORY" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --member="serviceAccount:$BUILD_SERVICE_ACCOUNT" \
  --role="roles/artifactregistry.writer" \
  --condition=None \
  --quiet >/dev/null

gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SERVICE_ACCOUNT" \
  --project="$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SERVICE_ACCOUNT" \
  --role="roles/iam.serviceAccountUser" \
  --condition=None \
  --quiet >/dev/null

project_number=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
cloud_build_service_agent="service-${project_number}@gcp-sa-cloudbuild.iam.gserviceaccount.com"
gcloud iam service-accounts add-iam-policy-binding "$BUILD_SERVICE_ACCOUNT" \
  --project="$PROJECT_ID" \
  --member="serviceAccount:$cloud_build_service_agent" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --condition=None \
  --quiet >/dev/null

gcloud builds triggers update github "$TRIGGER_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --service-account="$BUILD_SERVICE_ACCOUNT_RESOURCE" \
  --update-substitutions="$IMAGE_TAG_SUBSTITUTION" \
  --quiet

echo "Cloud Build configurado con IAM mínimo para $PROJECT_ID ($REGION)."
