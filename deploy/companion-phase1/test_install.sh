#!/bin/bash
# Local checks for install.sh. They use a temporary copy of the production
# snapshot and do not touch /opt/ironkeep or the production database.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
UP=/home/ubuntu/.cursor/projects/workspace/uploads
WORK=$(mktemp -d)
chmod 755 "$WORK"
trap 'sudo rm -rf "$WORK"' EXIT

if ! id ironkeep >/dev/null 2>&1; then
  sudo useradd --system --shell /usr/sbin/nologin --no-create-home ironkeep
fi

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

identity() {
  local file="$1"
  sudo stat -c '%u %g %a %Y %Z' "$file"
  sudo sha256sum "$file"
}

snapshot_tree() {
  local root="$1"
  local file
  sudo find "$root" -print | sort | while read -r file; do
    sudo stat -c '%n %F %u %g %a %Y %Z' "$file"
    if [[ -f "$file" ]]; then
      sudo sha256sum "$file"
    fi
  done
}

make_tree() {
  local root="$1"
  mkdir -p "$root/templates" "$root/static/js"
  cp "$UP/config_1a78.py" "$root/config.py"
  cp "$UP/discord_api_3302.py" "$root/discord_api.py"
  cp "$UP/db_0beb.py" "$root/db.py"
  cp "$UP/main_20db.py" "$root/main.py"
  cp "$UP/settings_48e5.html" "$root/templates/settings.html"
  cp "$UP/settings_cc8e.js" "$root/static/js/settings.js"
  cp "$UP/bot_da00.py" "$root/bot.py"
  sudo chown -R ironkeep:ironkeep "$root"
  sudo find "$root" -type d -exec chmod 750 {} +
  sudo find "$root" -type f -exec chmod 640 {} +
}

assert_original_six() {
  local root="$1"
  local manifest="$HERE/MANIFEST.txt"
  local kind path before after
  while read -r kind path before after; do
    [[ -z "${kind:-}" || "$kind" == \#* || "$kind" != "patch" ]] && continue
    local got
    got=$(sudo sha256sum "$root/$path" | awk '{print $1}')
    if [[ "$got" != "$before" ]]; then
      echo "expected original hash for $path" >&2
      exit 1
    fi
  done < "$manifest"
}

pass() {
  echo "ok  $1"
}

dry_root="$WORK/dry"
make_tree "$dry_root"
before=$(snapshot_tree "$dry_root")
sudo bash "$HERE/install.sh" --root "$dry_root"
after=$(snapshot_tree "$dry_root")
if [[ "$before" != "$after" ]]; then
  echo "dry-run changed the package" >&2
  diff -u <(printf '%s\n' "$before") <(printf '%s\n' "$after") || true
  exit 1
fi
if [[ -e "$dry_root/companion_auth.py" || -e "$dry_root/templates/companion_connect.html" ]]; then
  echo "dry-run created a Companion file" >&2
  exit 1
fi
pass "dry-run is read-only"

good_root="$WORK/good"
good_backup="$WORK/good-backup"
make_tree "$good_root"
declare -A original_id=()
while read -r kind path before after; do
  [[ -z "${kind:-}" || "$kind" == \#* || "$kind" != "patch" ]] && continue
  original_id["$path"]=$(sudo stat -c '%u %g %a' "$good_root/$path")
done < "$HERE/MANIFEST.txt"
sudo bash "$HERE/install.sh" --root "$good_root" --apply --backup-dir "$good_backup"
while read -r kind path before after; do
  [[ -z "${kind:-}" || "$kind" == \#* ]] && continue
  got=$(sudo sha256sum "$good_root/$path" | awk '{print $1}')
  if [[ "$got" != "$after" ]]; then
    echo "result hash mismatch for $path" >&2
    exit 1
  fi
  if [[ "$kind" == "patch" && "$(sudo stat -c '%u %g %a' "$good_root/$path")" != "${original_id[$path]}" ]]; then
    echo "owner or mode changed for $path" >&2
    exit 1
  fi
done < "$HERE/MANIFEST.txt"
config_id=$(sudo stat -c '%u %g %a' "$good_root/config.py")
for path in companion_auth.py templates/companion_connect.html; do
  if [[ "$(sudo stat -c '%u %g %a' "$good_root/$path")" != "$config_id" ]]; then
    echo "new file $path does not match config.py ownership" >&2
    exit 1
  fi
  sudo runuser -u ironkeep -- test -r "$good_root/$path"
done
if sudo grep -RInE 'IRONKEEP_COMPANION_AUTH=(1|true|yes)' "$good_root/config.py" "$good_root/companion_auth.py" >/dev/null; then
  echo "feature flag was enabled in installed files" >&2
  exit 1
fi
pass "apply keeps hashes, ownership, and readability"

fail_root="$WORK/fail"
fail_backup="$WORK/fail-backup"
make_tree "$fail_root"
sudo cp "$HERE/new/templates/companion_connect.html" "$fail_root/templates/companion_connect.html"
sudo chown ironkeep:ironkeep "$fail_root/templates/companion_connect.html"
sudo chmod 640 "$fail_root/templates/companion_connect.html"
kept_html=$(sudo sha256sum "$fail_root/templates/companion_connect.html" | awk '{print $1}')
declare -A fail_id=()
while read -r kind path before after; do
  [[ -z "${kind:-}" || "$kind" == \#* || "$kind" != "patch" ]] && continue
  fail_id["$path"]=$(sudo stat -c '%u %g %a' "$fail_root/$path")
done < "$HERE/MANIFEST.txt"
set +e
sudo IRONKEEP_INSTALL_TEST=1 IRONKEEP_INSTALL_FAILPOINT=after-first-new \
  bash "$HERE/install.sh" --root "$fail_root" --apply --backup-dir "$fail_backup"
fail_status=$?
set -e
if [[ "$fail_status" -eq 0 ]]; then
  echo "failpoint install should have failed" >&2
  exit 1
fi
assert_original_six "$fail_root"
while read -r kind path before after; do
  [[ -z "${kind:-}" || "$kind" == \#* || "$kind" != "patch" ]] && continue
  if [[ "$(sudo stat -c '%u %g %a' "$fail_root/$path")" != "${fail_id[$path]}" ]]; then
    echo "rollback changed owner or mode of $path" >&2
    exit 1
  fi
done < "$HERE/MANIFEST.txt"
if [[ -e "$fail_root/companion_auth.py" ]]; then
  echo "rollback left companion_auth.py behind" >&2
  exit 1
fi
if [[ "$(sudo sha256sum "$fail_root/templates/companion_connect.html" | awk '{print $1}')" != "$kept_html" ]]; then
  echo "rollback removed a Companion file this run did not create" >&2
  exit 1
fi
pass "failed install rolls back"

bad_root="$WORK/bad"
mkdir -p "$bad_root"
set +e
sudo bash "$HERE/install.sh" --root "$bad_root" >/dev/null
bad_status=$?
set -e
if [[ "$bad_status" -eq 0 ]]; then
  echo "invalid package should have been refused" >&2
  exit 1
fi
pass "invalid package is refused"

mismatch_root="$WORK/mismatch"
make_tree "$mismatch_root"
echo "changed" | sudo tee -a "$mismatch_root/config.py" >/dev/null
sudo chown ironkeep:ironkeep "$mismatch_root/config.py"
sudo chmod 640 "$mismatch_root/config.py"
before_mismatch=$(snapshot_tree "$mismatch_root")
set +e
sudo bash "$HERE/install.sh" --root "$mismatch_root" >/dev/null
mismatch_status=$?
set -e
after_mismatch=$(snapshot_tree "$mismatch_root")
if [[ "$mismatch_status" -eq 0 || "$before_mismatch" != "$after_mismatch" ]]; then
  echo "hash mismatch should refuse without writing" >&2
  exit 1
fi
pass "hash mismatch refuses without writing"

echo "install tests passed"
