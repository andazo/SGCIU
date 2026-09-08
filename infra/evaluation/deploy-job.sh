#!/bin/sh
set -eu

PROJECT_ID="${1:-tfm-sgciu}"
REGION="${2:-us-central1}"
BACKEND_SERVICE="${3:-sgciu-backend}"
EVALUATION_JOB="sgciu-evaluate-metrics"
RUNTIME_SERVICE_ACCOUNT="sgciu-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

# Reuse the exact immutable image and Cloud SQL connection of the deployed backend.
# This avoids a second build and makes a stored evaluation attributable to a revision.
BACKEND_IMAGE=$(gcloud run services describe "$BACKEND_SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --format='value(spec.template.spec.containers[0].image)')
CLOUD_SQL_INSTANCE=$(gcloud run services describe "$BACKEND_SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --format='value(spec.template.metadata.annotations.run.googleapis.com/cloudsql-instances)')

test -n "$BACKEND_IMAGE"
test -n "$CLOUD_SQL_INSTANCE"

gcloud run jobs deploy "$EVALUATION_JOB" \
  --project="$PROJECT_ID" \
  --image="$BACKEND_IMAGE" \
  --region="$REGION" \
  --command=python \
  --args=-m,app.evaluation.module_runner,--modules,all,--seed-incidents,--confirm-production \
  --set-cloudsql-instances="$CLOUD_SQL_INSTANCE" \
  --set-env-vars=APP_ENV=production,OPENAI_MODEL=gpt-5.4-mini,OPENAI_INTAKE_MODEL=gpt-5.6,OPENAI_EMBEDDING_MODEL=text-embedding-3-small,LEGAL_RAG_MODEL=gpt-5.4-mini,LEGAL_RAG_EMBEDDING_MODEL=text-embedding-3-large \
  --set-secrets=DATABASE_URL=sgciu-database-url:latest,OPENAI_API_KEY=sgciu-openai-key:latest \
  --service-account="$RUNTIME_SERVICE_ACCOUNT" \
  --cpu=1 \
  --memory=1Gi \
  --max-retries=0 \
  --task-timeout=3600s \
  --labels=application=sgciu,component=evaluation,environment=production \
  --quiet

echo "Job ${EVALUATION_JOB} configurado con la imagen ${BACKEND_IMAGE}."
