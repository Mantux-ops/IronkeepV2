#!/bin/bash
# Local check for the phase 2 installer. Do not copy this to the server.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(mktemp -d)
trap 'rm -rf "$ROOT"' EXIT

git -C "$HERE/../.." show 8cc056c78f8b43ab5b5f1dd978bb54599f18b657:production/ironkeep/companion_auth.py > "$ROOT/companion_auth.py"
printf 'config\n' > "$ROOT/config.py"
before=$(sha256sum "$ROOT/companion_auth.py" | awk '{ print $1 }')

bash "$HERE/install.sh" --root "$ROOT"
after_dry=$(sha256sum "$ROOT/companion_auth.py" | awk '{ print $1 }')
if [[ "$after_dry" != "$before" || -e "$ROOT/companion_reports.py" ]]; then
  echo "dry-run wrote a file" >&2
  exit 1
fi

bad=$(mktemp -d)
printf 'config\n' > "$bad/config.py"
printf 'other\n' > "$bad/companion_auth.py"
if bash "$HERE/install.sh" --root "$bad" >/tmp/phase2-mismatch.txt 2>&1; then
  echo "hash mismatch was accepted" >&2
  exit 1
fi
rm -rf "$bad"

backup=$(mktemp -d)
bash "$HERE/install.sh" --root "$ROOT" --apply --backup-dir "$backup"
auth=$(sha256sum "$ROOT/companion_auth.py" | awk '{ print $1 }')
reports=$(sha256sum "$ROOT/companion_reports.py" | awk '{ print $1 }')
want_auth=$(awk '$1=="companion_auth.py"{print $3}' "$HERE/MANIFEST.txt")
want_reports=$(awk '$1=="companion_reports.py"{print $3}' "$HERE/MANIFEST.txt")
if [[ "$auth" != "$want_auth" || "$reports" != "$want_reports" ]]; then
  echo "installed hashes do not match the manifest" >&2
  exit 1
fi
saved=$(sha256sum "$backup/companion_auth.py" | awk '{ print $1 }')
if [[ "$saved" != "$before" ]]; then
  echo "backup is not the phase 1 module" >&2
  exit 1
fi
second=$(bash "$HERE/install.sh" --root "$ROOT" --apply --backup-dir "$backup")
if [[ "$second" != "already installed" ]]; then
  echo "second install was not a no-op: $second" >&2
  exit 1
fi
if [[ -e "$ROOT/companion_reports.py.sqlite" || -e "$ROOT/ironkeep.db" ]]; then
  echo "installer created a database" >&2
  exit 1
fi
echo "install tests passed"
