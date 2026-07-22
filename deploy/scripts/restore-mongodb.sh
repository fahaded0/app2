#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  restore-mongodb.sh --container NAME --archive FILE --source-db DB \
    --target-db DB --confirm-target-db DB [--drop] \
    [--username-file CONTAINER_PATH --password-file CONTAINER_PATH \
     --authentication-db DB]

The archive is streamed through stdin and is never copied into the container.
Credential values are read only inside the target container from the supplied
file paths.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

container=""
archive=""
source_db=""
target_db=""
confirm_target_db=""
drop="false"
username_file=""
password_file=""
authentication_db="admin"

while (($#)); do
  case "$1" in
    --container)
      (($# >= 2)) || fail "--container requires a value"
      container="$2"
      shift 2
      ;;
    --archive)
      (($# >= 2)) || fail "--archive requires a value"
      archive="$2"
      shift 2
      ;;
    --source-db)
      (($# >= 2)) || fail "--source-db requires a value"
      source_db="$2"
      shift 2
      ;;
    --target-db)
      (($# >= 2)) || fail "--target-db requires a value"
      target_db="$2"
      shift 2
      ;;
    --confirm-target-db)
      (($# >= 2)) || fail "--confirm-target-db requires a value"
      confirm_target_db="$2"
      shift 2
      ;;
    --drop)
      drop="true"
      shift
      ;;
    --username-file)
      (($# >= 2)) || fail "--username-file requires a value"
      username_file="$2"
      shift 2
      ;;
    --password-file)
      (($# >= 2)) || fail "--password-file requires a value"
      password_file="$2"
      shift 2
      ;;
    --authentication-db)
      (($# >= 2)) || fail "--authentication-db requires a value"
      authentication_db="$2"
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

[[ -n "$container" ]] || fail "--container is required"
[[ -n "$archive" ]] || fail "--archive is required"
[[ -n "$source_db" ]] || fail "--source-db is required"
[[ -n "$target_db" ]] || fail "--target-db is required"
[[ "$target_db" == "$confirm_target_db" ]] ||
  fail "--confirm-target-db must exactly match --target-db"
[[ -f "$archive" ]] || fail "Archive not found: $archive"
[[ -s "$archive" ]] || fail "Archive is empty: $archive"
[[ "$source_db" =~ ^[A-Za-z0-9_-]+$ ]] || fail "Invalid source database name"
[[ "$target_db" =~ ^[A-Za-z0-9_-]+$ ]] || fail "Invalid target database name"

if [[ -n "$username_file" || -n "$password_file" ]]; then
  [[ -n "$username_file" && -n "$password_file" ]] ||
    fail "Both --username-file and --password-file are required together"
fi

command -v docker >/dev/null 2>&1 || fail "docker is required"
docker inspect "$container" >/dev/null 2>&1 || fail "Container not found: $container"
[[ "$(docker inspect -f '{{.State.Running}}' "$container")" == "true" ]] ||
  fail "Target container is not running"

docker exec -i \
  -e APP2_SOURCE_DB="$source_db" \
  -e APP2_TARGET_DB="$target_db" \
  -e APP2_DROP="$drop" \
  -e APP2_USERNAME_FILE="$username_file" \
  -e APP2_PASSWORD_FILE="$password_file" \
  -e APP2_AUTH_DB="$authentication_db" \
  "$container" \
  bash -ec '
    set -Eeuo pipefail
    args=(
      mongorestore
      --host 127.0.0.1
      --port 27017
      --archive
      --gzip
      --stopOnError
      --nsInclude "${APP2_SOURCE_DB}.*"
    )

    if [[ "$APP2_SOURCE_DB" != "$APP2_TARGET_DB" ]]; then
      args+=(
        --nsFrom "${APP2_SOURCE_DB}.*"
        --nsTo "${APP2_TARGET_DB}.*"
      )
    fi

    if [[ "$APP2_DROP" == "true" ]]; then
      args+=(--drop)
    fi

    if [[ -n "$APP2_USERNAME_FILE" ]]; then
      test -s "$APP2_USERNAME_FILE"
      test -s "$APP2_PASSWORD_FILE"
      username="$(cat "$APP2_USERNAME_FILE")"
      password="$(cat "$APP2_PASSWORD_FILE")"
      auth_config="$(mktemp)"
      cleanup_auth_config() {
        rm -f "$auth_config"
      }
      trap cleanup_auth_config EXIT
      yaml_password="${password//\\/\\\\}"
      yaml_password="${yaml_password//\"/\\\"}"
      printf "password: \"%s\"\n" "$yaml_password" > "$auth_config"
      chmod 0600 "$auth_config"
      args+=(
        --username "$username"
        --config "$auth_config"
        --authenticationDatabase "$APP2_AUTH_DB"
      )
    fi

    exec "${args[@]}"
  ' < "$archive"

printf 'MongoDB restore completed\n'
printf 'Container : %s\n' "$container"
printf 'Source DB : %s\n' "$source_db"
printf 'Target DB : %s\n' "$target_db"
printf 'Drop first: %s\n' "$drop"
