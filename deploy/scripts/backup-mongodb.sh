#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  backup-mongodb.sh --env-file PATH --destination DIR [--compose-file PATH]

Creates an application-database MongoDB archive, SHA-256 sidecar, source-state
record, and manifest. The destination must be an approved off-server mounted
backup path for production use.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_file="${repo_root}/docker-compose.production.yml"
env_file=""
destination=""

while (($#)); do
  case "$1" in
    --compose-file)
      (($# >= 2)) || fail "--compose-file requires a value"
      compose_file="$2"
      shift 2
      ;;
    --env-file)
      (($# >= 2)) || fail "--env-file requires a value"
      env_file="$2"
      shift 2
      ;;
    --destination)
      (($# >= 2)) || fail "--destination requires a value"
      destination="$2"
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

[[ -n "$env_file" ]] || fail "--env-file is required"
[[ -n "$destination" ]] || fail "--destination is required"
[[ -f "$compose_file" ]] || fail "Compose file not found: $compose_file"
[[ -f "$env_file" ]] || fail "Environment file not found: $env_file"
command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"

read_env_value() {
  local key="$1"
  awk -v wanted="$key" '
    /^[[:space:]]*#/ { next }
    {
      line=$0
      sub(/\r$/, "", line)
      if (line ~ "^[[:space:]]*" wanted "[[:space:]]*=") {
        sub("^[[:space:]]*" wanted "[[:space:]]*=[[:space:]]*", "", line)
        print line
        exit
      }
    }
  ' "$env_file"
}

db_name="$(read_env_value DB_NAME)"
db_name="${db_name:-medstock}"
[[ "$db_name" =~ ^[A-Za-z0-9_-]+$ ]] ||
  fail "DB_NAME contains unsupported characters"

mkdir -p "$destination"
chmod 0700 "$destination" 2>/dev/null || true

compose=(docker compose --env-file "$env_file" -f "$compose_file")
mongo_id="$("${compose[@]}" ps -q mongo)"
[[ -n "$mongo_id" ]] || fail "Mongo service container was not found"
[[ "$(docker inspect -f '{{.State.Running}}' "$mongo_id")" == "true" ]] ||
  fail "Mongo service is not running"
health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$mongo_id")"
[[ "$health" == "healthy" ]] || fail "Mongo service is not healthy: $health"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
prefix="app2-${db_name}-${timestamp}"
partial_dir="$(mktemp -d "${destination}/.${prefix}.partial.XXXXXX")"
trap 'rm -rf "$partial_dir"' EXIT

archive_tmp="${partial_dir}/${prefix}.archive.gz"
state_tmp="${partial_dir}/${prefix}.source-state.json"
sha_tmp="${partial_dir}/${prefix}.sha256"
manifest_tmp="${partial_dir}/${prefix}.manifest"

"${compose[@]}" exec -T -e APP2_BACKUP_DB="$db_name" mongo bash -ec '
  set -Eeuo pipefail
  root_user="$(cat /run/secrets/mongo_root_username)"
  root_password="$(cat /run/secrets/mongo_root_password)"
  exec mongosh     --host 127.0.0.1     --port 27017     --username "$root_user"     --password "$root_password"     --authenticationDatabase admin     "$APP2_BACKUP_DB"     --quiet     --eval '"'"'
      const names = db.getCollectionNames().sort();
      const counts = {};
      for (const name of names) {
        counts[name] = db.getCollection(name).countDocuments({});
      }
      const hash = db.runCommand({ dbHash: 1 });
      if (hash.ok !== 1) {
        throw new Error("dbHash failed");
      }
      print(JSON.stringify({
        database: db.getName(),
        dbHash: hash.md5,
        collections: counts
      }));
    '"'"'
' > "$state_tmp"

[[ -s "$state_tmp" ]] || fail "Source-state capture is empty"

"${compose[@]}" exec -T -e APP2_BACKUP_DB="$db_name" mongo bash -ec '
  set -Eeuo pipefail
  root_user="$(cat /run/secrets/mongo_root_username)"
  root_password="$(cat /run/secrets/mongo_root_password)"
  auth_config="$(mktemp)"
  cleanup_auth_config() {
    rm -f "$auth_config"
  }
  trap cleanup_auth_config EXIT
  yaml_password="${root_password//\\/\\\\}"
  yaml_password="${yaml_password//\"/\\\"}"
  printf "password: \"%s\"\n" "$yaml_password" > "$auth_config"
  chmod 0600 "$auth_config"
  mongodump     --host 127.0.0.1     --port 27017     --username "$root_user"     --config "$auth_config"     --authenticationDatabase admin     --readPreference primary     --db "$APP2_BACKUP_DB"     --archive     --gzip
' > "$archive_tmp"

[[ -s "$archive_tmp" ]] || fail "Backup archive is empty"
(
  cd "$partial_dir"
  sha256sum "$(basename "$archive_tmp")" > "$(basename "$sha_tmp")"
)

source_commit="unknown"
if command -v git >/dev/null 2>&1 && git -C "$repo_root" rev-parse HEAD >/dev/null 2>&1; then
  source_commit="$(git -C "$repo_root" rev-parse HEAD)"
fi

cat > "$manifest_tmp" <<EOF
format_version=1
created_utc=${timestamp}
database=${db_name}
archive_file=$(basename "$archive_tmp")
sha256_file=$(basename "$sha_tmp")
source_state_file=$(basename "$state_tmp")
source_commit=${source_commit}
consistency_requirement=application_writes_quiesced_during_backup
EOF

archive_final="${destination}/$(basename "$archive_tmp")"
state_final="${destination}/$(basename "$state_tmp")"
sha_final="${destination}/$(basename "$sha_tmp")"
manifest_final="${destination}/$(basename "$manifest_tmp")"

mv "$archive_tmp" "$archive_final"
mv "$state_tmp" "$state_final"
mv "$sha_tmp" "$sha_final"
mv "$manifest_tmp" "$manifest_final"
chmod 0600 "$archive_final" "$state_final" "$sha_final" "$manifest_final" 2>/dev/null || true

trap - EXIT
rm -rf "$partial_dir"

printf 'MongoDB backup completed\n'
printf 'Database    : %s\n' "$db_name"
printf 'Archive     : %s\n' "$archive_final"
printf 'SHA-256     : %s\n' "$sha_final"
printf 'Source state: %s\n' "$state_final"
printf 'Manifest    : %s\n' "$manifest_final"
printf 'Bytes       : %s\n' "$(wc -c < "$archive_final" | tr -d ' ')"
