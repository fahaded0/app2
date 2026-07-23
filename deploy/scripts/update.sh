#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  update.sh --env-file PATH --release TAG_OR_FULL_SHA --base-url URL
            --backup-destination DIR
            [--compose-file PATH] [--ca-certificate FILE | --insecure]
            [--timeout-seconds N] [--wait-seconds N]
            [--service-env-file PATH] [--skip-fetch]

Updates the application from an explicit Git tag or full 40-character commit SHA.
Branch names and moving refs are rejected. A MongoDB backup is required before
the update proceeds.
EOF
}

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_file="${repo_root}/docker-compose.production.yml"
env_file=""
release_ref=""
base_url=""
backup_destination=""
ca_certificate=""
insecure="false"
timeout_seconds="10"
wait_seconds="180"
service_env_file=""
skip_fetch="false"
state_dir="${repo_root}/deploy/state"

while (($#)); do
  case "$1" in
    --compose-file) (($# >= 2)) || fail "--compose-file requires a value"; compose_file="$2"; shift 2 ;;
    --env-file) (($# >= 2)) || fail "--env-file requires a value"; env_file="$2"; shift 2 ;;
    --release) (($# >= 2)) || fail "--release requires a value"; release_ref="$2"; shift 2 ;;
    --base-url) (($# >= 2)) || fail "--base-url requires a value"; base_url="$2"; shift 2 ;;
    --backup-destination) (($# >= 2)) || fail "--backup-destination requires a value"; backup_destination="$2"; shift 2 ;;
    --ca-certificate) (($# >= 2)) || fail "--ca-certificate requires a value"; ca_certificate="$2"; shift 2 ;;
    --insecure) insecure="true"; shift ;;
    --timeout-seconds) (($# >= 2)) || fail "--timeout-seconds requires a value"; timeout_seconds="$2"; shift 2 ;;
    --wait-seconds) (($# >= 2)) || fail "--wait-seconds requires a value"; wait_seconds="$2"; shift 2 ;;
    --service-env-file) (($# >= 2)) || fail "--service-env-file requires a value"; service_env_file="$2"; shift 2 ;;
    --skip-fetch) skip_fetch="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done

[[ -n "$env_file" ]] || fail "--env-file is required"
[[ -n "$release_ref" ]] || fail "--release is required"
[[ -n "$base_url" ]] || fail "--base-url is required"
[[ -n "$backup_destination" ]] || fail "--backup-destination is required"
[[ -f "$env_file" ]] || fail "Environment file not found: $env_file"
[[ -f "$compose_file" ]] || fail "Compose file not found: $compose_file"
[[ -x "${repo_root}/deploy/scripts/backup-mongodb.sh" ]] || fail "backup-mongodb.sh is missing or not executable"
[[ "$base_url" =~ ^https?://[^[:space:]]+$ ]] || fail "--base-url must be an absolute HTTP or HTTPS URL"
[[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]] || fail "--timeout-seconds must be a positive integer"
[[ "$wait_seconds" =~ ^[1-9][0-9]*$ ]] || fail "--wait-seconds must be a positive integer"
[[ -z "$ca_certificate" || "$insecure" == "false" ]] || fail "--ca-certificate and --insecure cannot be used together"
[[ -z "$ca_certificate" || -f "$ca_certificate" ]] || fail "CA certificate not found: $ca_certificate"
command -v git >/dev/null 2>&1 || fail "git is required"
command -v docker >/dev/null 2>&1 || fail "docker is required"

reject_moving_ref() {
  local ref="$1"
  case "$ref" in
    HEAD|main|master|develop|dev|staging|production|prod|origin/*|refs/heads/*|refs/remotes/*|feature/*|bugfix/*|hotfix/*|release/*)
      fail "--release must be an explicit tag or full 40-character commit SHA, not a moving ref: $ref" ;;
  esac
}

resolve_release() {
  local ref="$1"
  reject_moving_ref "$ref"
  if [[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
    git -C "$repo_root" cat-file -e "${ref}^{commit}" 2>/dev/null || fail "Commit SHA not found locally: $ref"
    git -C "$repo_root" rev-parse "${ref}^{commit}"
    return
  fi
  if git -C "$repo_root" show-ref --verify --quiet "refs/tags/${ref}"; then
    git -C "$repo_root" rev-parse "refs/tags/${ref}^{commit}"
    return
  fi
  fail "--release must be an existing tag name or full 40-character commit SHA: $ref"
}

safe_image_tag() { local ref="$1" commit="$2" tag; tag="$(printf '%s' "$ref" | tr -c 'A-Za-z0-9_.-' '-' | cut -c1-64)"; tag="${tag:-${commit:0:12}}"; printf '%s\n' "$tag"; }
ensure_clean_tracked_tree() { git -C "$repo_root" diff --quiet || fail "Tracked working tree changes exist"; git -C "$repo_root" diff --cached --quiet || fail "Staged changes exist"; }

health_args() {
  printf '%s\0' "${repo_root}/deploy/scripts/health-check.sh"
  printf '%s\0' "--base-url" "$base_url"
  printf '%s\0' "--timeout-seconds" "$timeout_seconds"
  if [[ -n "$ca_certificate" ]]; then printf '%s\0' "--ca-certificate" "$ca_certificate"; elif [[ "$insecure" == "true" ]]; then printf '%s\0' "--insecure"; fi
}

wait_for_health() {
  local deadline=$((SECONDS + wait_seconds)) args=()
  mapfile -d '' -t args < <(health_args)
  while true; do
    if "${args[@]}"; then return 0; fi
    if (( SECONDS >= deadline )); then return 1; fi
    sleep 5
  done
}

write_state_file() {
  local path="$1" ref="$2" commit="$3" image_tag="$4"
  mkdir -p "$(dirname "$path")"; chmod 0700 "$(dirname "$path")" 2>/dev/null || true
  cat > "$path" <<EOF
APP2_RELEASE_REF=$ref
APP2_RELEASE_COMMIT=$commit
APP2_IMAGE_TAG=$image_tag
APP2_DEPLOYED_AT_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
}

write_service_env_file() {
  local path="$1" ref="$2" commit="$3" image_tag="$4"
  [[ -n "$path" ]] || return 0
  mkdir -p "$(dirname "$path")"
  cat > "$path" <<EOF
APP_IMAGE_TAG=$image_tag
APP2_RELEASE_REF=$ref
APP2_RELEASE_COMMIT=$commit
EOF
  chmod 0600 "$path" 2>/dev/null || true
}

ensure_clean_tracked_tree
current_commit="$(git -C "$repo_root" rev-parse HEAD)"
current_ref="$current_commit"
current_image_tag="${current_commit:0:12}"
if [[ -f "${state_dir}/current-release.env" ]]; then
  source "${state_dir}/current-release.env"
  current_ref="${APP2_RELEASE_REF:-$current_commit}"
  current_commit="${APP2_RELEASE_COMMIT:-$current_commit}"
  current_image_tag="${APP2_IMAGE_TAG:-${current_commit:0:12}}"
fi

mkdir -p "$state_dir"
write_state_file "${state_dir}/previous-release.env" "$current_ref" "$current_commit" "$current_image_tag"

"${repo_root}/deploy/scripts/backup-mongodb.sh" --env-file "$env_file" --compose-file "$compose_file" --destination "$backup_destination"
if [[ "$skip_fetch" != "true" ]]; then git -C "$repo_root" fetch --tags --prune origin; fi

target_commit="$(resolve_release "$release_ref")"
target_image_tag="$(safe_image_tag "$release_ref" "$target_commit")"

git -C "$repo_root" checkout --detach "$target_commit"
[[ -x "${repo_root}/deploy/scripts/health-check.sh" ]] || fail "deploy/scripts/health-check.sh is missing or not executable in release $target_commit"

compose=(docker compose --env-file "$env_file" -f "$compose_file")
APP_IMAGE_TAG="$target_image_tag" "${compose[@]}" config >/dev/null
APP_IMAGE_TAG="$target_image_tag" "${compose[@]}" build backend frontend
APP_IMAGE_TAG="$target_image_tag" "${compose[@]}" up -d --remove-orphans

if ! wait_for_health; then
  printf 'ERROR: Update health gate failed for release %s (%s)\n' "$release_ref" "$target_commit" >&2
  printf 'Previous release retained in %s\n' "${state_dir}/previous-release.env" >&2
  printf 'Run rollback.sh without --to-release, or pass --to-release %s\n' "$current_commit" >&2
  exit 1
fi

write_state_file "${state_dir}/current-release.env" "$release_ref" "$target_commit" "$target_image_tag"
write_service_env_file "$service_env_file" "$release_ref" "$target_commit" "$target_image_tag"

printf 'Update completed successfully.\n'
printf 'Previous commit: %s\n' "$current_commit"
printf 'Release ref    : %s\n' "$release_ref"
printf 'Release commit : %s\n' "$target_commit"
printf 'Image tag      : %s\n' "$target_image_tag"
