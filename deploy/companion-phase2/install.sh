#!/bin/bash
# Install Companion Phase 2 onto a server that already has Phase 1.
# Also replaces db.py and companion_reports.py when an earlier Phase 2
# package is already present. Default is a dry run and does not write.
# This script does not restart services, edit /etc/ironkeep.env, open the
# database, or set IRONKEEP_COMPANION_AUTH.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=""
APPLY=0
BACKUP_DIR=""

usage() {
  echo "Usage: install.sh --root /opt/ironkeep/ironkeep [--apply --backup-dir DIR]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      ROOT=${2:-}
      shift 2
      ;;
    --apply)
      APPLY=1
      shift
      ;;
    --backup-dir)
      BACKUP_DIR=${2:-}
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

if [[ -z "$ROOT" ]]; then
  usage
fi
if [[ "$APPLY" -eq 1 && -z "$BACKUP_DIR" ]]; then
  echo "An install needs --backup-dir." >&2
  exit 2
fi

if [[ ! -f "$ROOT/config.py" || ! -f "$ROOT/companion_auth.py" || ! -f "$ROOT/db.py" ]]; then
  echo "Refusing to run: $ROOT is not an Ironkeep package with Companion phase 1 installed." >&2
  exit 1
fi

hash_file() {
  sha256sum "$1" | awk '{ print $1 }'
}

declare -A AFTER=()
declare -A ACCEPT=()
while read -r name before after; do
  [[ -n "${name:-}" && "$name" != \#* ]] || continue
  if [[ -n "${AFTER[$name]:-}" && "${AFTER[$name]}" != "$after" ]]; then
    echo "Refusing to run: MANIFEST.txt disagrees about $name." >&2
    exit 1
  fi
  AFTER[$name]=$after
  ACCEPT[$name]="${ACCEPT[$name]:-} $before"
done < "$HERE/MANIFEST.txt"

for name in companion_auth.py companion_reports.py db.py; do
  if [[ -z "${AFTER[$name]:-}" ]]; then
    echo "Refusing to run: MANIFEST.txt has no $name." >&2
    exit 1
  fi
  package=$(hash_file "$HERE/new/$name")
  if [[ "$package" != "${AFTER[$name]}" ]]; then
    echo "Refusing to run: new/$name does not match MANIFEST.txt." >&2
    exit 1
  fi
done

live_hash() {
  local name=$1
  if [[ ! -f "$ROOT/$name" ]]; then
    echo "-"
  else
    hash_file "$ROOT/$name"
  fi
}

accepted() {
  local name=$1
  local live=$2
  local token
  if [[ "$live" == "${AFTER[$name]}" ]]; then
    return 0
  fi
  for token in ${ACCEPT[$name]}; do
    if [[ "$live" == "$token" ]]; then
      return 0
    fi
  done
  return 1
}

declare -A LIVE=()
for name in companion_auth.py companion_reports.py db.py; do
  LIVE[$name]=$(live_hash "$name")
  if ! accepted "$name" "${LIVE[$name]}"; then
    echo "Refusing to replace $name." >&2
    echo "  found ${LIVE[$name]}" >&2
    exit 1
  fi
done

pending=0
for name in companion_auth.py companion_reports.py db.py; do
  if [[ "${LIVE[$name]}" != "${AFTER[$name]}" ]]; then
    pending=1
  fi
done
if [[ "$pending" -eq 0 ]]; then
  echo "already installed"
  exit 0
fi
if [[ "$APPLY" -eq 0 ]]; then
  echo "dry-run ok"
  for name in companion_reports.py db.py companion_auth.py; do
    if [[ "${LIVE[$name]}" != "${AFTER[$name]}" ]]; then
      echo "would install $name"
    fi
  done
  exit 0
fi

mkdir -p "$BACKUP_DIR"
declare -A CREATED=()
for name in companion_auth.py companion_reports.py db.py; do
  CREATED[$name]=0
  if [[ -f "$ROOT/$name" ]]; then
    cp -p "$ROOT/$name" "$BACKUP_DIR/$name"
  else
    CREATED[$name]=1
  fi
done

restore() {
  local name
  for name in companion_auth.py companion_reports.py db.py; do
    if [[ "${CREATED[$name]}" -eq 1 ]]; then
      rm -f "$ROOT/$name"
    elif [[ -f "$BACKUP_DIR/$name" ]]; then
      cp -p "$BACKUP_DIR/$name" "$ROOT/$name"
    fi
  done
  echo "Rollback finished. The previous Companion files were restored." >&2
}

copied=0
trap 'if [[ "$copied" -eq 1 ]]; then restore; fi' ERR
copied=1
# The parser goes down before the module that imports it. db.py is independent.
cp "$HERE/new/companion_reports.py" "$ROOT/companion_reports.py"
cp "$HERE/new/db.py" "$ROOT/db.py"
cp "$HERE/new/companion_auth.py" "$ROOT/companion_auth.py"
chmod --reference="$BACKUP_DIR/companion_auth.py" "$ROOT/companion_auth.py" "$ROOT/companion_reports.py" "$ROOT/db.py"
if [[ "$(id -u)" -eq 0 ]]; then
  chown --reference="$BACKUP_DIR/companion_auth.py" "$ROOT/companion_auth.py" "$ROOT/companion_reports.py" "$ROOT/db.py"
fi
for name in companion_auth.py companion_reports.py db.py; do
  if [[ "$(hash_file "$ROOT/$name")" != "${AFTER[$name]}" ]]; then
    restore
    exit 1
  fi
done
copied=0
trap - ERR
echo "installed"
for name in companion_auth.py companion_reports.py db.py; do
  echo "$name ${AFTER[$name]}"
done
