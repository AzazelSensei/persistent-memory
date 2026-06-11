#!/usr/bin/env bash
# Snapshot a records directory into a tar.gz archive.
# Usage: backup.sh [src-dir] [out.tar.gz]   (defaults: docs, pm-backup-<timestamp>.tar.gz)
set -euo pipefail
SRC="${1:-docs}"
OUT="${2:-pm-backup-$(date +%Y%m%d-%H%M%S).tar.gz}"
tar -czf "$OUT" -C "$(dirname "$SRC")" "$(basename "$SRC")"
echo "snapshot: $OUT"
