#!/bin/sh
set -eu

PROJECT_ID="${1:-tfm-sgciu}"
REGION="${2:-us-central1}"
SCRIPT_DIR=$(dirname -- "$0")
SCRIPT_DIR=$(CDPATH='' cd -- "$SCRIPT_DIR" && pwd)
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT HUP INT TERM

ensure_log_metric() {
  metric_name=$1
  config_file=$2
  if gcloud logging metrics describe "$metric_name" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud logging metrics update "$metric_name" \
      --project="$PROJECT_ID" \
      --config-from-file="$config_file" \
      --quiet
  else
    gcloud logging metrics create "$metric_name" \
      --project="$PROJECT_ID" \
      --config-from-file="$config_file" \
      --quiet
  fi
}

ensure_uptime_check() {
  display_name=$1
  host=$2
  path=$3
  matcher=$4
  check_id=$(gcloud monitoring uptime list-configs \
    --project="$PROJECT_ID" \
    --filter="displayName='$display_name'" \
    --format='value(name.basename())' \
    --limit=1)

  if [ -n "$check_id" ]; then
    gcloud monitoring uptime update "$check_id" \
      --project="$PROJECT_ID" \
      --display-name="$display_name" \
      --path="$path" \
      --period=1 \
      --timeout=10 \
      --set-regions=usa-iowa,usa-oregon,usa-virginia \
      --validate-ssl=true \
      --quiet >/dev/null
  else
    matcher_arguments=""
    if [ -n "$matcher" ]; then
      matcher_arguments="--matcher-content=$matcher --matcher-type=contains-string"
    fi
    # shellcheck disable=SC2086
    gcloud monitoring uptime create "$display_name" \
      --project="$PROJECT_ID" \
      --resource-type=uptime-url \
      --resource-labels="host=$host,project_id=$PROJECT_ID" \
      --protocol=https \
      --path="$path" \
      --period=1 \
      --timeout=10 \
      --regions=usa-iowa,usa-oregon,usa-virginia \
      --validate-ssl=true \
      --status-classes=2xx \
      $matcher_arguments \
      --quiet >/dev/null
    check_id=$(gcloud monitoring uptime list-configs \
      --project="$PROJECT_ID" \
      --filter="displayName='$display_name'" \
      --format='value(name.basename())' \
      --limit=1)
  fi
  printf '%s\n' "$check_id"
}

ensure_policy() {
  config_file=$1
  display_name=$2
  policy_id=$(gcloud monitoring policies list \
    --project="$PROJECT_ID" \
    --filter="displayName='$display_name'" \
    --format='value(name.basename())' \
    --limit=1)
  if [ -n "$policy_id" ]; then
    current_policy="$TEMP_DIR/current-policy-$policy_id.json"
    merged_policy="$TEMP_DIR/merged-policy-$policy_id.json"
    gcloud monitoring policies describe "$policy_id" \
      --project="$PROJECT_ID" \
      --format=json > "$current_policy"
    python3 - "$config_file" "$current_policy" "$merged_policy" <<'PY'
import json
import sys

desired_path, current_path, output_path = sys.argv[1:]
with open(desired_path, encoding="utf-8") as desired_file:
    desired = json.load(desired_file)
with open(current_path, encoding="utf-8") as current_file:
    current = json.load(current_file)

for field in ("notificationChannels", "alertStrategy"):
    if field in current and field not in desired:
        desired[field] = current[field]

with open(output_path, "w", encoding="utf-8") as output_file:
    json.dump(desired, output_file)
PY
    gcloud monitoring policies update "$policy_id" \
      --project="$PROJECT_ID" \
      --policy-from-file="$merged_policy" \
      --quiet >/dev/null
  else
    gcloud monitoring policies create \
      --project="$PROJECT_ID" \
      --policy-from-file="$config_file" \
      --quiet >/dev/null
  fi
}

render_uptime_policy() {
  check_id=$1
  display_name=$2
  check_label=$3
  output_file=$4
  sed \
    -e "s/__CHECK_ID__/$check_id/g" \
    -e "s/__DISPLAY_NAME__/$display_name/g" \
    -e "s/__CHECK_LABEL__/$check_label/g" \
    "$SCRIPT_DIR/policies/uptime.json.in" > "$output_file"
}

backend_url=$(gcloud run services describe sgciu-backend \
  --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')
frontend_url=$(gcloud run services describe sgciu-frontend \
  --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')
backend_host=${backend_url#https://}
frontend_host=${frontend_url#https://}

ensure_log_metric sgciu_ai_estimated_cost_usd "$SCRIPT_DIR/log-metrics/ai-cost.yaml"
ensure_log_metric sgciu_ai_input_tokens "$SCRIPT_DIR/log-metrics/ai-input-tokens.yaml"
ensure_log_metric sgciu_ai_output_tokens "$SCRIPT_DIR/log-metrics/ai-output-tokens.yaml"
ensure_log_metric sgciu_readiness_failures "$SCRIPT_DIR/log-metrics/readiness-failures.yaml"

backend_check_id=$(ensure_uptime_check \
  "SGCIU backend readiness" "$backend_host" "/ready" '"status":"ready"')
frontend_check_id=$(ensure_uptime_check \
  "SGCIU frontend availability" "$frontend_host" "/" "")

render_uptime_policy "$backend_check_id" \
  "SGCIU - disponibilidad backend" "del backend y PostgreSQL" \
  "$TEMP_DIR/backend-uptime.json"
render_uptime_policy "$frontend_check_id" \
  "SGCIU - disponibilidad frontend" "del frontend" \
  "$TEMP_DIR/frontend-uptime.json"

ensure_policy "$TEMP_DIR/backend-uptime.json" "SGCIU - disponibilidad backend"
ensure_policy "$TEMP_DIR/frontend-uptime.json" "SGCIU - disponibilidad frontend"
ensure_policy "$SCRIPT_DIR/policies/cloud-run-5xx.json" "SGCIU - errores 5xx backend"
ensure_policy "$SCRIPT_DIR/policies/backend-latency.json" "SGCIU - latencia p95 backend"
ensure_policy "$SCRIPT_DIR/policies/cloud-sql-cpu.json" "SGCIU - CPU Cloud SQL"
ensure_policy "$SCRIPT_DIR/policies/database-readiness.json" \
  "SGCIU - disponibilidad de base de datos"
ensure_policy "$SCRIPT_DIR/policies/ai-cost-spike.json" "SGCIU - aumento de coste IA"

dashboard_id=$(gcloud monitoring dashboards list \
  --project="$PROJECT_ID" \
  --filter="displayName='SGCIU - Operación y costes'" \
  --format='value(name.basename())' \
  --limit=1)
if [ -n "$dashboard_id" ]; then
  current_dashboard="$TEMP_DIR/current-dashboard.json"
  merged_dashboard="$TEMP_DIR/merged-dashboard.json"
  gcloud monitoring dashboards describe "$dashboard_id" \
    --project="$PROJECT_ID" \
    --format=json > "$current_dashboard"
  python3 - "$SCRIPT_DIR/dashboard.json" "$current_dashboard" "$merged_dashboard" <<'PY'
import json
import sys

desired_path, current_path, output_path = sys.argv[1:]
with open(desired_path, encoding="utf-8") as desired_file:
    desired = json.load(desired_file)
with open(current_path, encoding="utf-8") as current_file:
    current = json.load(current_file)

for field in ("name", "etag"):
    desired[field] = current[field]

with open(output_path, "w", encoding="utf-8") as output_file:
    json.dump(desired, output_file)
PY
  gcloud monitoring dashboards update "$dashboard_id" \
    --project="$PROJECT_ID" \
    --config-from-file="$merged_dashboard" \
    --quiet >/dev/null
else
  gcloud monitoring dashboards create \
    --project="$PROJECT_ID" \
    --config-from-file="$SCRIPT_DIR/dashboard.json" \
    --quiet >/dev/null
fi

echo "Monitorización SGCIU configurada en $PROJECT_ID ($REGION)."
echo "Añada al menos un canal de notificación verificado a las políticas desde Cloud Monitoring."
