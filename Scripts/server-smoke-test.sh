#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <image-tag>" >&2
  exit 1
fi

image_tag="$1"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker command is required for the smoke tests" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl command is required for the smoke tests" >&2
  exit 1
fi

# Configuration matrices to exercise different runtime modes.
declare -a CONFIG_SEQUENCE=(
  "authenticated"
  "dev_mode"
  "high_scale"
)

# Authenticated production-like configuration
# Note: Kerberos credentials omitted for smoke tests as they require valid keytabs
# The smoke tests verify the server can start and respond to health checks
declare -A CONFIG_authenticated=(
  [SESSION_SECRET_KEY]="ci-smoke-secret"
  [AUTH_ENABLED]="true"
  [OIDC_ISSUER_URL]="https://auth.example.com/realms/ci"
  [OIDC_CLIENT_ID]="ci-smoke-client"
  [OIDC_REDIRECT_URI]="https://ci-smoke.example.com/callback"
  [ENVIRONMENT_NAME]="CI Smoke Test"
  [HYPERV_HOSTS]="hyperv-01.example.com,hyperv-02.example.com"
  [AGENT_DOWNLOAD_BASE_URL]="https://downloads.example.com/aether"
)

# Developer friendly configuration with auth disabled and dummy data enabled
declare -A CONFIG_dev_mode=(
  [SESSION_SECRET_KEY]="ci-smoke-secret"
  [AUTH_ENABLED]="false"
  [ALLOW_DEV_AUTH]="true"
  [DEBUG]="true"
  [DUMMY_DATA]="true"
  [COOKIE_SECURE]="false"
  [COOKIE_SAMESITE]="lax"
  [ENVIRONMENT_NAME]="Developer Sandbox"
)

# High scale configuration exercising concurrency tuning knobs
# Note: Kerberos credentials omitted for smoke tests as they require valid keytabs
declare -A CONFIG_high_scale=(
  [SESSION_SECRET_KEY]="ci-smoke-secret"
  [AUTH_ENABLED]="true"
  [OIDC_ISSUER_URL]="https://auth.example.com/realms/qa"
  [OIDC_CLIENT_ID]="ci-qa-client"
  [OIDC_REDIRECT_URI]="https://qa.example.com/callback"
  [ENVIRONMENT_NAME]="QA Lab"
  [HYPERV_HOSTS]="qa-host-01.lab.local,qa-host-02.lab.local,qa-host-03.lab.local"
  [AGENT_DOWNLOAD_BASE_URL]="https://downloads.example.com/qa-agent"
  [REMOTE_TASK_MAX_CONCURRENCY]="32"
  [REMOTE_TASK_DYNAMIC_CEILING]="64"
  [JOB_WORKER_CONCURRENCY]="10"
  [INVENTORY_REFRESH_INTERVAL]="30"
)

current_container=""
cleanup() {
  if [[ -n "${current_container}" ]]; then
    docker logs "${current_container}" || true
    docker rm -f "${current_container}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

run_smoke_test() {
  local name="$1"
  local config_ref="$2"
  local port="$3"

  declare -n config_map="${config_ref}"

  local -a env_args=()
  for key in "${!config_map[@]}"; do
    env_args+=("-e" "${key}=${config_map[$key]}")
  done

  local container_name="aetherv-smoke-${name}-${RANDOM}"
  echo "::group::Launching ${name} configuration"
  current_container="$(docker run -d --rm --name "${container_name}" -p "${port}:8000" "${env_args[@]}" "${image_tag}")"

  local ready=0
  for attempt in {1..30}; do
    if ! docker ps -q -f "id=${current_container}" >/dev/null 2>&1; then
      echo "Container ${current_container} exited before becoming ready" >&2
      docker logs "${current_container}" || true
      return 1
    fi

    if curl --fail --silent "http://127.0.0.1:${port}/healthz" >/dev/null; then
      ready=1
      break
    fi
    sleep 2
  done

  if [[ "${ready}" -ne 1 ]]; then
    echo "Container ${current_container} failed readiness checks" >&2
    docker logs "${current_container}" || true
    return 1
  fi

  echo "Health endpoint responded successfully for ${name} configuration"
  docker stop "${current_container}" >/dev/null
  current_container=""
  echo "::endgroup::"
  return 0
}

port_base=18080
for index in "${!CONFIG_SEQUENCE[@]}"; do
  config_name="${CONFIG_SEQUENCE[$index]}"
  config_var="CONFIG_${config_name}"
  port=$((port_base + index))
  run_smoke_test "${config_name}" "${config_var}" "${port}"
  echo "Completed smoke test for ${config_name} configuration"
done

trap - EXIT
exit 0
