#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  verify-backup.sh --archive FILE --sha256 FILE --source-state FILE \
    [--mongo-image IMAGE]

Verifies the SHA-256 sidecar, restores the archive into a disposable isolated
MongoDB container, and compares the restored database dbHash and collection
counts with the source-state record.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
archive=""
sha_file=""
source_state=""
mongo_image="mongo:8.0@sha256:721f8fe7ae88f6acee8c163a358f726cef6dfc4181b9d3ca77212a0cef6b781c"

while (($#)); do
  case "$1" in
    --archive)
      (($# >= 2)) || fail "--archive requires a value"
      archive="$2"
      shift 2
      ;;
    --sha256)
      (($# >= 2)) || fail "--sha256 requires a value"
      sha_file="$2"
      shift 2
      ;;
    --source-state)
      (($# >= 2)) || fail "--source-state requires a value"
      source_state="$2"
      shift 2
      ;;
    --mongo-image)
      (($# >= 2)) || fail "--mongo-image requires a value"
      mongo_image="$2"
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

[[ -f "$archive" && -s "$archive" ]] || fail "Archive is missing or empty"
[[ -f "$sha_file" && -s "$sha_file" ]] || fail "SHA-256 sidecar is missing or empty"
[[ -f "$source_state" && -s "$source_state" ]] ||
  fail "Source-state file is missing or empty"
command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"

archive_dir="$(cd "$(dirname "$archive")" && pwd)"
sha_file_abs="$(cd "$(dirname "$sha_file")" && pwd)/$(basename "$sha_file")"
(
  cd "$archive_dir"
  sha256sum -c "$sha_file_abs"
)

container="app2-pkg7-verify-$(date -u +%Y%m%d%H%M%S)-$$"
started_epoch="$(date +%s)"
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run -d --rm --name "$container" "$mongo_image" \
  --bind_ip_all >/dev/null

ready="false"
for _ in $(seq 1 60); do
  if docker exec "$container" mongosh \
    --host 127.0.0.1 \
    --port 27017 \
    --quiet \
    --eval 'quit(db.adminCommand({ ping: 1 }).ok === 1 ? 0 : 1)' \
    >/dev/null 2>&1; then
    ready="true"
    break
  fi
  sleep 1
done
[[ "$ready" == "true" ]] || fail "Disposable MongoDB did not become ready"

docker cp "$source_state" "${container}:/tmp/app2-source-state.json"

database="$(
  docker exec "$container" mongosh --quiet --nodb --eval '
    const fs = require("fs");
    const state = JSON.parse(
      fs.readFileSync("/tmp/app2-source-state.json", "utf8")
    );
    const database = state.database || "";
    if (!/^[A-Za-z0-9_-]+$/.test(database)) {
      throw new Error("Invalid database in source-state file");
    }
    print(database);
  '
)"

"${repo_root}/deploy/scripts/restore-mongodb.sh" \
  --container "$container" \
  --archive "$archive" \
  --source-db "$database" \
  --target-db "$database" \
  --confirm-target-db "$database" \
  --drop >/dev/null

docker exec -e APP2_VERIFY_DB="$database" "$container" mongosh \
  --host 127.0.0.1 \
  --port 27017 \
  "$database" \
  --quiet \
  --eval '
    const fs = require("fs");
    const expected = JSON.parse(
      fs.readFileSync("/tmp/app2-source-state.json", "utf8")
    );

    const names = db.getCollectionNames().sort();
    const counts = {};
    for (const name of names) {
      counts[name] = db.getCollection(name).countDocuments({});
    }

    const hash = db.runCommand({ dbHash: 1 });
    if (hash.ok !== 1) {
      throw new Error("dbHash failed");
    }

    const actual = {
      database: db.getName(),
      dbHash: hash.md5,
      collections: counts
    };

    if (JSON.stringify(expected) !== JSON.stringify(actual)) {
      print("Expected: " + JSON.stringify(expected));
      print("Actual  : " + JSON.stringify(actual));
      throw new Error("Restored database state does not match source state");
    }
  ' >/dev/null

finished_epoch="$(date +%s)"
duration="$((finished_epoch - started_epoch))"

printf 'MongoDB backup verification PASSED\n'
printf 'Archive       : %s\n' "$(basename "$archive")"
printf 'Database      : %s\n' "$database"
printf 'Restore target: disposable isolated container\n'
printf 'Integrity     : SHA-256, dbHash, and collection counts matched\n'
printf 'Duration sec  : %s\n' "$duration"
