#!/usr/bin/env bash
# bid-scan first-run installer: user-level systemd units (no sudo needed).
set -euo pipefail
ROOT="/home/lynxadmin/project/bid-scaning"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR" "$ROOT/data/logs"

for unit in bidscan-{pipeline,callbacks,digest,followup,watchdog}-{service,timer}; do
  :
done
cp "$ROOT"/services/bidscan-*.service "$ROOT"/services/bidscan-*.timer "$UNIT_DIR/"

systemctl --user daemon-reload
systemctl --user enable --now bidscan-pipeline.timer bidscan-callbacks.timer \
  bidscan-digest.timer bidscan-followup.timer bidscan-watchdog.timer

# persist across logins/reboots (no sudo needed — polkit allows self-linger)
loginctl enable-linger "$USER" 2>/dev/null || true

echo "installed. timers status:"
systemctl --user list-timers 'bidscan-*' --no-legend
echo
echo "OLD CRONTAB STILL ACTIVE (dual-run while proving systemd)."
echo "After one successful proven cycle pair, remove crons:"
echo "  bidscan crontab-remove"
