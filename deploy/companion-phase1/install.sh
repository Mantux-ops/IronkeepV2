#!/bin/bash
# Apply the phase 1 Companion patch onto a copy of the production package.
# Default is a dry run. This script does not restart services, edit
# /etc/ironkeep.env, or open the production database.
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

declare -a REL
declare -a BEFORE
declare -a AFTER
declare -a KIND
while read -r kind path before after; do
  [[ -z "${kind:-}" || "$kind" == \#* ]] && continue
  KIND+=("$kind")
  REL+=("$path")
  BEFORE+=("$before")
  AFTER+=("$after")
done < "$HERE/MANIFEST.txt"

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

echo "Package: $HERE"
echo "Target:  $ROOT"
echo "Mode:    $([[ $APPLY -eq 1 ]] && echo apply || echo dry-run)"

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
    echo "original ok  $path"
  elif [[ "${KIND[$i]}" == "new" ]]; then
    if [[ -e "$dest" ]]; then
      got=$(sha256_file "$dest")
      if [[ "$got" != "${AFTER[$i]}" ]]; then
        echo "Refusing to overwrite existing $path (hash $got)." >&2
        exit 1
      fi
      echo "already new  $path"
    else
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

mkdir -p "$BACKUP_DIR"
for i in "${!REL[@]}"; do
  if [[ "${KIND[$i]}" == "patch" ]]; then
    mkdir -p "$BACKUP_DIR/$(dirname "${REL[$i]}")"
    cp -a "$ROOT/${REL[$i]}" "$BACKUP_DIR/${REL[$i]}"
  fi
done
echo "file backup  $BACKUP_DIR"

patch --forward --batch -p1 -d "$ROOT" < "$HERE/phase1-production.patch"

for i in "${!REL[@]}"; do
  if [[ "${KIND[$i]}" != "new" ]]; then
    continue
  fi
  dest="$ROOT/${REL[$i]}"
  if [[ -e "$dest" ]]; then
    got=$(sha256_file "$dest")
    [[ "$got" == "${AFTER[$i]}" ]] || exit 1
    continue
  fi
  mkdir -p "$(dirname "$dest")"
  cp -a "$HERE/new/${REL[$i]}" "$dest"
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

echo "Apply finished. IRONKEEP_COMPANION_AUTH was not set. No service was restarted."
