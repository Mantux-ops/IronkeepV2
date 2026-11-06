#!/bin/bash
# Replace the Phase 1 Companion module with the Phase 2 upload module.
# Default is a dry run and does not write.
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

if [[ ! -f "$ROOT/config.py" || ! -f "$ROOT/companion_auth.py" ]]; then
  echo "Refusing to run: $ROOT is not an Ironkeep package with Companion phase 1 installed." >&2
  exit 1
fi

field() {
  awk -v name="$1" -v column="$2" '$1 == name { print $column; exit }' "$HERE/MANIFEST.txt"
}

hash_file() {
  sha256sum "$1" | awk '{ print $1 }'
}

before=$(field companion_auth.py 2)
after=$(field companion_auth.py 3)
reports_after=$(field companion_reports.py 3)
package_auth=$(hash_file "$HERE/new/companion_auth.py")
package_reports=$(hash_file "$HERE/new/companion_reports.py")
if [[ "$package_auth" != "$after" || "$package_reports" != "$reports_after" ]]; then
  echo "Refusing to run: the package files do not match MANIFEST.txt." >&2
  exit 1
fi

live=$(hash_file "$ROOT/companion_auth.py")
reports_live=""
if [[ -f "$ROOT/companion_reports.py" ]]; then
  reports_live=$(hash_file "$ROOT/companion_reports.py")
  if [[ "$reports_live" != "$reports_after" ]]; then
    echo "Refusing to replace companion_reports.py." >&2
    echo "  expected $reports_after" >&2
    echo "  found    $reports_live" >&2
    exit 1
  fi
fi
if [[ "$live" != "$before" && "$live" != "$after" ]]; then
  echo "Refusing to replace companion_auth.py." >&2
  echo "  expected $before" >&2
  echo "  or       $after" >&2
  echo "  found    $live" >&2
  exit 1
fi
if [[ "$live" == "$after" && "$reports_live" == "$reports_after" ]]; then
  echo "already installed"
  exit 0
fi
if [[ "$APPLY" -eq 0 ]]; then
  echo "dry-run ok"
  echo "would install companion_reports.py"
  echo "would replace companion_auth.py"
  exit 0
fi

mkdir -p "$BACKUP_DIR"
cp -p "$ROOT/companion_auth.py" "$BACKUP_DIR/companion_auth.py"
created_reports=0
if [[ -f "$ROOT/companion_reports.py" ]]; then
  cp -p "$ROOT/companion_reports.py" "$BACKUP_DIR/companion_reports.py"
else
  created_reports=1
fi

restore() {
  cp -p "$BACKUP_DIR/companion_auth.py" "$ROOT/companion_auth.py"
  if [[ "$created_reports" -eq 1 ]]; then
    rm -f "$ROOT/companion_reports.py"
  elif [[ -f "$BACKUP_DIR/companion_reports.py" ]]; then
    cp -p "$BACKUP_DIR/companion_reports.py" "$ROOT/companion_reports.py"
  fi
  echo "Rollback finished. companion_auth.py was restored." >&2
}

copied=0
trap 'if [[ "$copied" -eq 1 ]]; then restore; fi' ERR
copied=1
cp "$HERE/new/companion_reports.py" "$ROOT/companion_reports.py"
cp "$HERE/new/companion_auth.py" "$ROOT/companion_auth.py"
chmod --reference="$BACKUP_DIR/companion_auth.py" "$ROOT/companion_auth.py" "$ROOT/companion_reports.py"
if [[ "$(id -u)" -eq 0 ]]; then
  chown --reference="$BACKUP_DIR/companion_auth.py" "$ROOT/companion_auth.py" "$ROOT/companion_reports.py"
fi
if [[ "$(hash_file "$ROOT/companion_auth.py")" != "$after" || "$(hash_file "$ROOT/companion_reports.py")" != "$reports_after" ]]; then
  restore
  exit 1
fi
copied=0
trap - ERR
echo "installed"
echo "companion_auth.py $after"
echo "companion_reports.py $reports_after"
