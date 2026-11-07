#!/bin/bash
# Local check for the phase 2 installer. Do not copy this to the server.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(mktemp -d)
trap 'rm -rf "$ROOT"' EXIT

seed_layout() {
  local dest=$1
  mkdir -p "$dest/templates"
  cat > "$dest/templates/app_layout.html" <<'EOF'
<nav>
      <a class="nav__item {% if nav == 'members' %}is-active{% endif %}" href="/{{ guild.slug }}/members">{{ icon("users") }}<span>Members</span></a>
      <a class="nav__item {% if nav == 'settings' %}is-active{% endif %}" href="/{{ guild.slug }}/settings">{{ icon("settings") }}<span>Settings</span></a>
</nav>
EOF
}

git -C "$HERE/../.." show 8cc056c78f8b43ab5b5f1dd978bb54599f18b657:production/ironkeep/companion_auth.py > "$ROOT/companion_auth.py"
git -C "$HERE/../.." show 8cc056c78f8b43ab5b5f1dd978bb54599f18b657:production/ironkeep/db.py > "$ROOT/db.py"
git -C "$HERE/../.." show 439044e85bc04ba78d44af9462a1d64016ce6606:production/ironkeep/main.py > "$ROOT/main.py"
printf 'config\n' > "$ROOT/config.py"
seed_layout "$ROOT"
before=$(sha256sum "$ROOT/companion_auth.py" | awk '{ print $1 }')
before_db=$(sha256sum "$ROOT/db.py" | awk '{ print $1 }')
before_main=$(sha256sum "$ROOT/main.py" | awk '{ print $1 }')
before_layout=$(sha256sum "$ROOT/templates/app_layout.html" | awk '{ print $1 }')

bash "$HERE/install.sh" --root "$ROOT"
after_dry=$(sha256sum "$ROOT/companion_auth.py" | awk '{ print $1 }')
after_db=$(sha256sum "$ROOT/db.py" | awk '{ print $1 }')
after_main=$(sha256sum "$ROOT/main.py" | awk '{ print $1 }')
after_layout=$(sha256sum "$ROOT/templates/app_layout.html" | awk '{ print $1 }')
if [[ "$after_dry" != "$before" || "$after_db" != "$before_db" || "$after_main" != "$before_main" || "$after_layout" != "$before_layout" || -e "$ROOT/companion_reports.py" || -e "$ROOT/roster.py" || -e "$ROOT/templates/roster.html" ]]; then
  echo "dry-run wrote a file" >&2
  exit 1
fi

bad=$(mktemp -d)
printf 'config\n' > "$bad/config.py"
printf 'other\n' > "$bad/companion_auth.py"
cp "$ROOT/db.py" "$bad/db.py"
cp "$ROOT/main.py" "$bad/main.py"
seed_layout "$bad"
if bash "$HERE/install.sh" --root "$bad" >/tmp/phase2-mismatch.txt 2>&1; then
  echo "hash mismatch was accepted" >&2
  exit 1
fi
rm -rf "$bad"

bad_db=$(mktemp -d)
cp "$ROOT/companion_auth.py" "$bad_db/companion_auth.py"
cp "$ROOT/main.py" "$bad_db/main.py"
printf 'config\n' > "$bad_db/config.py"
printf 'other-db\n' > "$bad_db/db.py"
seed_layout "$bad_db"
if bash "$HERE/install.sh" --root "$bad_db" >/tmp/phase2-db-mismatch.txt 2>&1; then
  echo "db.py hash mismatch was accepted" >&2
  exit 1
fi
if [[ -e "$bad_db/companion_reports.py" || -e "$bad_db/roster.py" ]]; then
  echo "refused install wrote a new file" >&2
  exit 1
fi
rm -rf "$bad_db"

bad_main=$(mktemp -d)
cp "$ROOT/companion_auth.py" "$bad_main/companion_auth.py"
cp "$ROOT/db.py" "$bad_main/db.py"
printf 'config\n' > "$bad_main/config.py"
printf 'other-main\n' > "$bad_main/main.py"
seed_layout "$bad_main"
if bash "$HERE/install.sh" --root "$bad_main" >/tmp/phase2-main-mismatch.txt 2>&1; then
  echo "main.py hash mismatch was accepted" >&2
  exit 1
fi
if [[ -e "$bad_main/roster.py" ]]; then
  echo "refused main.py install wrote roster.py" >&2
  exit 1
fi
rm -rf "$bad_main"

bad_layout=$(mktemp -d)
cp "$ROOT/companion_auth.py" "$bad_layout/companion_auth.py"
cp "$ROOT/db.py" "$bad_layout/db.py"
cp "$ROOT/main.py" "$bad_layout/main.py"
printf 'config\n' > "$bad_layout/config.py"
mkdir -p "$bad_layout/templates"
printf '<nav>no members link</nav>\n' > "$bad_layout/templates/app_layout.html"
if bash "$HERE/install.sh" --root "$bad_layout" >/tmp/phase2-layout-mismatch.txt 2>&1; then
  echo "a layout without Members was accepted" >&2
  exit 1
fi
if [[ -e "$bad_layout/roster.py" || -e "$bad_layout/templates/roster.html" ]]; then
  echo "refused layout install wrote a roster file" >&2
  exit 1
fi
rm -rf "$bad_layout"

backup=$(mktemp -d)
bash "$HERE/install.sh" --root "$ROOT" --apply --backup-dir "$backup"
auth=$(sha256sum "$ROOT/companion_auth.py" | awk '{ print $1 }')
reports=$(sha256sum "$ROOT/companion_reports.py" | awk '{ print $1 }')
database=$(sha256sum "$ROOT/db.py" | awk '{ print $1 }')
main=$(sha256sum "$ROOT/main.py" | awk '{ print $1 }')
roster=$(sha256sum "$ROOT/roster.py" | awk '{ print $1 }')
page=$(sha256sum "$ROOT/templates/roster.html" | awk '{ print $1 }')
want_auth=$(awk '$1=="companion_auth.py"{print $3; exit}' "$HERE/MANIFEST.txt")
want_reports=$(awk '$1=="companion_reports.py"{print $3; exit}' "$HERE/MANIFEST.txt")
want_db=$(awk '$1=="db.py"{print $3; exit}' "$HERE/MANIFEST.txt")
want_main=$(awk '$1=="main.py"{print $3; exit}' "$HERE/MANIFEST.txt")
want_roster=$(awk '$1=="roster.py"{print $3; exit}' "$HERE/MANIFEST.txt")
want_page=$(awk '$1=="templates/roster.html"{print $3; exit}' "$HERE/MANIFEST.txt")
if [[ "$auth" != "$want_auth" || "$reports" != "$want_reports" || "$database" != "$want_db" || "$main" != "$want_main" || "$roster" != "$want_roster" || "$page" != "$want_page" ]]; then
  echo "installed hashes do not match the manifest" >&2
  exit 1
fi
if [[ $(grep -c "nav == 'roster'" "$ROOT/templates/app_layout.html") -ne 1 ]]; then
  echo "Roster link was not inserted once" >&2
  exit 1
fi
if ! grep -q 'href="/{{ guild.slug }}/members"' "$ROOT/templates/app_layout.html"; then
  echo "Members link was removed" >&2
  exit 1
fi
saved=$(sha256sum "$backup/companion_auth.py" | awk '{ print $1 }')
saved_db=$(sha256sum "$backup/db.py" | awk '{ print $1 }')
saved_main=$(sha256sum "$backup/main.py" | awk '{ print $1 }')
if [[ "$saved" != "$before" || "$saved_db" != "$before_db" || "$saved_main" != "$before_main" ]]; then
  echo "backup is not the previous files" >&2
  exit 1
fi
if [[ -e "$backup/companion_reports.py" || -e "$backup/roster.py" ]]; then
  echo "a missing file was backed up" >&2
  exit 1
fi
second=$(bash "$HERE/install.sh" --root "$ROOT" --apply --backup-dir "$backup")
if [[ "$second" != "already installed" ]]; then
  echo "second install was not a no-op: $second" >&2
  exit 1
fi
if [[ $(grep -c "nav == 'roster'" "$ROOT/templates/app_layout.html") -ne 1 ]]; then
  echo "second install duplicated the Roster link" >&2
  exit 1
fi

upgrade=$(mktemp -d)
git -C "$HERE/../.." show 9521a7982eb3210921776ef1f33df4fbbf78cf2a:production/ironkeep/companion_auth.py > "$upgrade/companion_auth.py"
git -C "$HERE/../.." show 9521a7982eb3210921776ef1f33df4fbbf78cf2a:production/ironkeep/companion_reports.py > "$upgrade/companion_reports.py"
git -C "$HERE/../.." show 9521a7982eb3210921776ef1f33df4fbbf78cf2a:production/ironkeep/db.py > "$upgrade/db.py"
cp "$ROOT/main.py" "$upgrade/main.py"
printf 'config\n' > "$upgrade/config.py"
seed_layout "$upgrade"
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
if [[ $(grep -c "nav == 'roster'" "$upgrade/templates/app_layout.html") -ne 1 ]]; then
  echo "upgrade did not insert the Roster link" >&2
  exit 1
fi
rm -rf "$upgrade" "$upgrade_backup"

if [[ -e "$ROOT/companion_reports.py.sqlite" || -e "$ROOT/ironkeep.db" ]]; then
  echo "installer created a database" >&2
  exit 1
fi
echo "install tests passed"
