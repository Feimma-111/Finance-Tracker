#!/bin/bash
# Copy the Pi's daily backups to this Mac (the second copy of your data).
#
# Run by hand:   ./deploy/pull-backups.sh
# Run daily:     crontab -e   and add the line
#                30 21 * * * "$HOME/Documents/Summer Projects/Finance-Tracker/deploy/pull-backups.sh"
#
# Uses Tailscale SSH to reach the Pi; nothing is exposed to the internet.

set -euo pipefail
PI_HOST="${PI_HOST:-finance-pi}"
DEST="$HOME/Library/Application Support/Finance Tracker/pi-backups"

mkdir -p "$DEST"
chmod 700 "$DEST"
# --ignore-existing: backups never change once written, so only new ones are copied.
rsync -a --ignore-existing --chmod=F600 "$PI_HOST:.local/share/finance-tracker/backups/" "$DEST/"
echo "Backups from $PI_HOST are in: $DEST"
ls -1t "$DEST" | head -3
