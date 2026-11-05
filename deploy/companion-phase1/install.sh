#!/bin/bash
# Apply the phase 1 Companion patch onto the production package.
# Default is a dry run and does not write to the package.
# An install restores the six original files and removes only Companion
# files this run created if a later step fails.
# This script does not restart services, edit /etc/ironkeep.env, or open
# the production database. It does not set IRONKEEP_COMPANION_AUTH.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=""
APPLY=0
BACKUP_DIR=""
SERVICE_USER="ironkeep"
CHANGED=0
declare -a CREATED=()
declare -a REL=()
declare -a BEFORE=()
declare -a AFTER=()
declare -a KIND=()

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

if [[ -n "${IRONKEEP_INSTALL_FAILPOINT:-}" && "${IRONKEEP_INSTALL_TEST:-}" != 1 ]]; then
  echo "Refusing to run: IRONKEEP_INSTALL_FAILPOINT is only for the install tests." >&2
  exit 2
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Refusing to run: root is required so ownership can be kept and ${SERVICE_USER} can be checked." >&2
  exit 1
fi

if [[ -z "$ROOT" || ! -d "$ROOT" ]]; then
  echo "Refusing to run: --root must be the ironkeep package directory." >&2
  exit 2
fi
ROOT=$(cd "$ROOT" && pwd)
if [[ "$ROOT" == "/" || "$ROOT" == "/opt" || "$ROOT" == "/opt/ironkeep" ]]; then
  echo "Refusing to run: --root must be the inner package directory, /opt/ironkeep/ironkeep." >&2
  exit 2
fi
if [[ -n "$BACKUP_DIR" && "$APPLY" -ne 1 ]]; then
  echo "Refusing to run: --backup-dir is only used with --apply." >&2
  exit 2
fi
if [[ "$APPLY" -eq 1 && -z "$BACKUP_DIR" ]]; then
  echo "Refusing to apply: pass --backup-dir so the six current files are copied aside first." >&2
  exit 2
fi

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

restore_attrs() {
  local reference="$1"
  local dest="$2"
  chown --reference="$reference" "$dest"
  chmod --reference="$reference" "$dest"
}

rollback() {
  local path=""
  echo "Install failed. Restoring the six original files." >&2
  for i in "${!REL[@]}"; do
    if [[ "${KIND[$i]}" != "patch" ]]; then
      continue
    fi
    path="${REL[$i]}"
    cp -a "$BACKUP_DIR/$path" "$ROOT/$path"
    if [[ "$(sha256_file "$ROOT/$path")" != "${BEFORE[$i]}" ]]; then
      echo "ROLLBACK INCOMPLETE for $path. Copies remain in $BACKUP_DIR." >&2
      return 1
    fi
  done
  if [[ ${#CREATED[@]} -gt 0 ]]; then
    for path in "${CREATED[@]}"; do
      rm -f "$ROOT/$path"
    done
  fi
  echo "Rollback finished. Companion files created by this run were removed." >&2
}

cleanup() {
  local status=$?
  trap - EXIT
  if [[ "$CHANGED" -eq 1 && "$status" -ne 0 ]]; then
    rollback || status=1
  fi
  exit "$status"
}
trap cleanup EXIT

require_text() {
  local file="$1"
  local needle="$2"
  if [[ ! -f "$ROOT/$file" ]] || ! grep -q -F -- "$needle" "$ROOT/$file"; then
    echo "Refusing to run: $ROOT is not an Ironkeep package ($file)." >&2
    exit 1
  fi
}

require_text "config.py" "SUPERADMIN_ID"
require_text "main.py" 'SESSION_COOKIE = "ik_session"'
require_text "db.py" "def init("
require_text "discord_api.py" "def bot_member("
if [[ ! -f "$ROOT/bot.py" || ! -d "$ROOT/templates" || ! -d "$ROOT/static/js" ]]; then
  echo "Refusing to run: $ROOT is not an Ironkeep package." >&2
  exit 1
fi

while read -r kind path before after; do
  [[ -z "${kind:-}" || "$kind" == \#* ]] && continue
  KIND+=("$kind")
  REL+=("$path")
  BEFORE+=("$before")
  AFTER+=("$after")
done < "$HERE/MANIFEST.txt"

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "Refusing to run: service user ${SERVICE_USER} does not exist." >&2
  exit 1
fi

echo "Package: $HERE"
echo "Target:  $ROOT"
echo "Mode:    $([[ "$APPLY" -eq 1 ]] && echo apply || echo dry-run)"

for i in "${!REL[@]}"; do
  path="${REL[$i]}"
  dest="$ROOT/$path"
  if [[ "${KIND[$i]}" == "patch" ]]; then
    if [[ ! -f "$dest" ]]; then
      echo "Missing original file: $dest" >&2
      exit 1
    fi
    got=$(sha256_file "$dest")
    if [[ "$got" != "${BEFORE[$i]}" ]]; then
      echo "SHA-256 mismatch for $path" >&2
      echo "  expected original ${BEFORE[$i]}" >&2
      echo "  found            $got" >&2
      echo "Not patching. The live file is not the reviewed snapshot." >&2
      exit 1
    fi
    if ! runuser -u "$SERVICE_USER" -- test -r "$dest"; then
      echo "Refusing to run: ${SERVICE_USER} cannot read $path." >&2
      exit 1
    fi
    echo "original ok  $path"
  elif [[ "${KIND[$i]}" == "new" ]]; then
    if [[ -e "$dest" ]]; then
      got=$(sha256_file "$dest")
      if [[ "$got" != "${AFTER[$i]}" ]]; then
        echo "Refusing to overwrite existing $path (hash $got)." >&2
        exit 1
      fi
      if ! runuser -u "$SERVICE_USER" -- test -r "$dest"; then
        echo "Refusing to run: ${SERVICE_USER} cannot read existing $path." >&2
        exit 1
      fi
      echo "already new  $path"
    else
      parent=$(dirname "$dest")
      if [[ ! -d "$parent" ]] || ! runuser -u "$SERVICE_USER" -- test -x "$parent"; then
        echo "Refusing to run: ${SERVICE_USER} cannot reach $parent." >&2
        exit 1
      fi
      echo "new file     $path"
    fi
  else
    echo "Unknown manifest kind ${KIND[$i]}" >&2
    exit 1
  fi
done

if ! patch --forward --batch --dry-run -p1 -d "$ROOT" < "$HERE/phase1-production.patch"; then
  echo "Patch dry-run failed. No files were changed by this script." >&2
  exit 1
fi
echo "patch dry-run ok"

if [[ "$APPLY" -ne 1 ]]; then
  echo "Dry run finished. No files were written."
  exit 0
fi

backup_real=$(mkdir -p "$BACKUP_DIR" && cd "$BACKUP_DIR" && pwd)
if [[ "$backup_real" == "$ROOT" || "$backup_real" == "$ROOT"/* ]]; then
  echo "Refusing to apply: --backup-dir must be outside the package." >&2
  exit 1
fi
BACKUP_DIR=$backup_real

for i in "${!REL[@]}"; do
  if [[ "${KIND[$i]}" != "patch" ]]; then
    continue
  fi
  path="${REL[$i]}"
  mkdir -p "$BACKUP_DIR/$(dirname "$path")"
  cp -a "$ROOT/$path" "$BACKUP_DIR/$path"
  if [[ "$(sha256_file "$BACKUP_DIR/$path")" != "${BEFORE[$i]}" ]]; then
    echo "Backup hash mismatch for $path. The package was not changed." >&2
    exit 1
  fi
done
echo "file backup  $BACKUP_DIR"

CHANGED=1
patch --forward --batch -p1 -d "$ROOT" < "$HERE/phase1-production.patch"
for i in "${!REL[@]}"; do
  if [[ "${KIND[$i]}" != "patch" ]]; then
    continue
  fi
  path="${REL[$i]}"
  restore_attrs "$BACKUP_DIR/$path" "$ROOT/$path"
done
if [[ "${IRONKEEP_INSTALL_TEST:-}" == 1 && "${IRONKEEP_INSTALL_FAILPOINT:-}" == "after-patch" ]]; then
  echo "Test failpoint: after-patch" >&2
  exit 1
fi

reference="$ROOT/config.py"
for i in "${!REL[@]}"; do
  if [[ "${KIND[$i]}" != "new" ]]; then
    continue
  fi
  path="${REL[$i]}"
  dest="$ROOT/$path"
  if [[ ! -e "$dest" ]]; then
    # Register before cp so a partial file is removed if the copy fails.
    CREATED+=("$path")
    cp "$HERE/new/$path" "$dest"
    restore_attrs "$reference" "$dest"
    if [[ "${IRONKEEP_INSTALL_TEST:-}" == 1 && "${IRONKEEP_INSTALL_FAILPOINT:-}" == "after-first-new" && "${#CREATED[@]}" -eq 1 ]]; then
      echo "Test failpoint: after-first-new" >&2
      exit 1
    fi
  fi
  if ! runuser -u "$SERVICE_USER" -- test -r "$dest"; then
    echo "${SERVICE_USER} cannot read $path." >&2
    exit 1
  fi
  echo "readable     $path"
done

for i in "${!REL[@]}"; do
  got=$(sha256_file "$ROOT/${REL[$i]}")
  if [[ "$got" != "${AFTER[$i]}" ]]; then
    echo "Result hash mismatch for ${REL[$i]}" >&2
    echo "  expected ${AFTER[$i]}" >&2
    echo "  found    $got" >&2
    exit 1
  fi
  echo "result ok    ${REL[$i]}"
done

CHANGED=0
echo "Apply finished. IRONKEEP_COMPANION_AUTH was not set. No service was restarted."
