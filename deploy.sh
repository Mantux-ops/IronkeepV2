#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/ironkeep"
VENV_DIR="$APP_DIR/.venv"
REQ_FILE="$APP_DIR/requirements.txt"
DEPS_STAMP="$VENV_DIR/.deps_stamp"

cd "$APP_DIR"

echo "== Ironkeep deploy =="

PREVIOUS_COMMIT="$(git rev-parse --short HEAD)"
echo "Current commit: $PREVIOUS_COMMIT"
git --no-pager log --oneline -1

echo
echo "Pulling latest main..."
git pull origin main

NEW_COMMIT="$(git rev-parse --short HEAD)"
echo
echo "New commit: $NEW_COMMIT"
git --no-pager log --oneline -1

echo
if [ ! -f "$DEPS_STAMP" ] || [ "$REQ_FILE" -nt "$DEPS_STAMP" ]; then
  echo "requirements.txt changed or dependency stamp missing."
  echo "Installing dependencies..."
  "$VENV_DIR/bin/pip" install -r "$REQ_FILE"
  touch "$DEPS_STAMP"
else
  echo "Dependencies unchanged. Skipping pip install."
fi

echo
echo "Restarting services..."
systemctl restart ironkeep-app
systemctl restart ironkeep-scheduler
systemctl restart ironkeep-bot

echo
echo "Checking health..."
sleep 3
curl -f http://127.0.0.1:8000/health

echo
echo
echo "Deploy complete."
echo "Previous commit: $PREVIOUS_COMMIT"
echo "Running commit : $NEW_COMMIT"

if [ "$PREVIOUS_COMMIT" != "$NEW_COMMIT" ]; then
  echo
  echo "Rollback command if needed:"
  echo "  cd $APP_DIR && git reset --hard $PREVIOUS_COMMIT && systemctl restart ironkeep-app ironkeep-scheduler ironkeep-bot"
fi