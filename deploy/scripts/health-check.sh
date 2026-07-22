#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  health-check.sh --base-url URL [--ca-certificate FILE | --insecure]
                  [--timeout-seconds N]

Checks application liveness and MongoDB-aware readiness through the published
edge. The command exits non-zero when either probe fails.

Production use should trust the internal CA with --ca-certificate or the host
trust store. The --insecure option is permitted only for disposable validation.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

base_url=""
ca_certificate=""
insecure="false"
timeout_seconds="5"

while (($#)); do
  case "$1" in
    --base-url)
      (($# >= 2)) || fail "--base-url requires a value"
      base_url="$2"
      shift 2
      ;;
    --ca-certificate)
      (($# >= 2)) || fail "--ca-certificate requires a value"
      ca_certificate="$2"
      shift 2
      ;;
    --insecure)
      insecure="true"
      shift
      ;;
    --timeout-seconds)
      (($# >= 2)) || fail "--timeout-seconds requires a value"
      timeout_seconds="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

[[ -n "$base_url" ]] || fail "--base-url is required"
[[ "$base_url" =~ ^https?://[^[:space:]]+$ ]] ||
  fail "--base-url must be an absolute HTTP or HTTPS URL"
[[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]] ||
  fail "--timeout-seconds must be a positive integer"
[[ -z "$ca_certificate" || "$insecure" == "false" ]] ||
  fail "--ca-certificate and --insecure cannot be used together"
[[ -z "$ca_certificate" || -f "$ca_certificate" ]] ||
  fail "CA certificate not found: $ca_certificate"

command -v curl >/dev/null 2>&1 || fail "curl is required"

base_url="${base_url%/}"
curl_args=(
  --silent
  --show-error
  --fail
  --output /dev/null
  --max-time "$timeout_seconds"
)

if [[ -n "$ca_certificate" ]]; then
  curl_args+=(--cacert "$ca_certificate")
elif [[ "$insecure" == "true" ]]; then
  curl_args+=(--insecure)
fi

check_endpoint() {
  local label="$1"
  local path="$2"

  if ! curl "${curl_args[@]}" "${base_url}${path}"; then
    fail "${label} probe failed: ${path}"
  fi

  printf '%s: PASSED\n' "$label"
}

check_endpoint "Liveness" "/api/healthz"
check_endpoint "Readiness" "/api/readyz"
printf 'Application health check: PASSED\n'
