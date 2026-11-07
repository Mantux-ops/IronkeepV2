#!/bin/bash
# Local check for the phase 2 installer. Do not copy this to the server.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(mktemp -d)
trap 'rm -rf "$ROOT"' EXIT

git -C "$HERE/../.." show 8cc056c78f8b43ab5b5f1dd978bb54599f18b657:production/ironkeep/companion_auth.py > "$ROOT/companion_auth.py"
git -C "$HERE/../.." show 8cc056c78f8b43ab5b5f1dd978bb54599f18b657:production/ironkeep/db.py > "$ROOT/db.py"
printf 'config\n' > "$ROOT/config.py"
before=$(sha256sum "$ROOT/companion_auth.py" | awk '{ print $1 }')
before_db=$(sha256sum "$ROOT/db.py" | awk '{ print $1 }')

bash "$HERE/install.sh" --root "$ROOT"
after_dry=$(sha256sum "$ROOT/companion_auth.py" | awk '{ print $1 }')
after_db=$(sha256sum "$ROOT/db.py" | awk '{ print $1 }')
if [[ "$after_dry" != "$before" || "$after_db" != "$before_db" || -e "$ROOT/companion_reports.py" ]]; then
  echo "dry-run wrote a file" >&2
  exit 1
fi

bad=$(mktemp -d)
printf 'config\n' > "$bad/config.py"
printf 'other\n' > "$bad/companion_auth.py"
cp "$ROOT/db.py" "$bad/db.py"
if bash "$HERE/install.sh" --root "$bad" >/tmp/phase2-mismatch.txt 2>&1; then
  echo "hash mismatch was accepted" >&2
  exit 1
fi
rm -rf "$bad"

bad_db=$(mktemp -d)
cp "$ROOT/companion_auth.py" "$bad_db/companion_auth.py"
printf 'config\n' > "$bad_db/config.py"
printf 'other-db\n' > "$bad_db/db.py"
if bash "$HERE/install.sh" --root "$bad_db" >/tmp/phase2-db-mismatch.txt 2>&1; then
  echo "db.py hash mismatch was accepted" >&2
  exit 1
fi
if [[ -e "$bad_db/companion_reports.py" ]]; then
  echo "refused install wrote companion_reports.py" >&2
  exit 1
fi
rm -rf "$bad_db"

backup=$(mktemp -d)
bash "$HERE/install.sh" --root "$ROOT" --apply --backup-dir "$backup"
auth=$(sha256sum "$ROOT/companion_auth.py" | awk '{ print $1 }')
reports=$(sha256sum "$ROOT/companion_reports.py" | awk '{ print $1 }')
database=$(sha256sum "$ROOT/db.py" | awk '{ print $1 }')
want_auth=$(awk '$1=="companion_auth.py"{print $3; exit}' "$HERE/MANIFEST.txt")
want_reports=$(awk '$1=="companion_reports.py"{print $3; exit}' "$HERE/MANIFEST.txt")
want_db=$(awk '$1=="db.py"{print $3; exit}' "$HERE/MANIFEST.txt")
if [[ "$auth" != "$want_auth" || "$reports" != "$want_reports" || "$database" != "$want_db" ]]; then
  echo "installed hashes do not match the manifest" >&2
  exit 1
fi
saved=$(sha256sum "$backup/companion_auth.py" | awk '{ print $1 }')
saved_db=$(sha256sum "$backup/db.py" | awk '{ print $1 }')
if [[ "$saved" != "$before" || "$saved_db" != "$before_db" ]]; then
  echo "backup is not the phase 1 files" >&2
  exit 1
fi
if [[ -e "$backup/companion_reports.py" ]]; then
  echo "a missing reports file was backed up" >&2
  exit 1
fi
second=$(bash "$HERE/install.sh" --root "$ROOT" --apply --backup-dir "$backup")
if [[ "$second" != "already installed" ]]; then
  echo "second install was not a no-op: $second" >&2
  exit 1
fi

upgrade=$(mktemp -d)
git -C "$HERE/../.." show 9521a7982eb3210921776ef1f33df4fbbf78cf2a:production/ironkeep/companion_auth.py > "$upgrade/companion_auth.py"
git -C "$HERE/../.." show 9521a7982eb3210921776ef1f33df4fbbf78cf2a:production/ironkeep/companion_reports.py > "$upgrade/companion_reports.py"
git -C "$HERE/../.." show 9521a7982eb3210921776ef1f33df4fbbf78cf2a:production/ironkeep/db.py > "$upgrade/db.py"
printf 'config\n' > "$upgrade/config.py"
old_reports=$(sha256sum "$upgrade/companion_reports.py" | awk '{ print $1 }')
upgrade_backup=$(mktemp -d)
bash "$HERE/install.sh" --root "$upgrade" --apply --backup-dir "$upgrade_backup"
upgraded_reports=$(sha256sum "$upgrade/companion_reports.py" | awk '{ print $1 }')
upgraded_db=$(sha256sum "$upgrade/db.py" | awk '{ print $1 }')
kept_reports=$(sha256sum "$upgrade_backup/companion_reports.py" | awk '{ print $1 }')
if [[ "$upgraded_reports" != "$want_reports" || "$upgraded_db" != "$want_db" || "$kept_reports" != "$old_reports" ]]; then
  echo "upgrade from the first phase 2 package failed" >&2
  exit 1
fi
rm -rf "$upgrade" "$upgrade_backup"

if [[ -e "$ROOT/companion_reports.py.sqlite" || -e "$ROOT/ironkeep.db" ]]; then
  echo "installer created a database" >&2
  exit 1
fi
echo "install tests passed"
