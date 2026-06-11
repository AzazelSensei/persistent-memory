#!/usr/bin/env bash
# Restore a backup archive created by backup.sh.
# Refuses to overwrite existing top-level paths in the destination unless --force is given.
set -euo pipefail
FORCE_FLAG="--force"
ARCHIVE="${1:?usage: restore.sh <archive.tar.gz> [dest-dir] [--force]}"
DEST="${2:-.}"
FORCE="${3:-}"
if [ "$FORCE" != "$FORCE_FLAG" ]; then
  while IFS= read -r top; do
    [ -z "$top" ] && continue
    if [ -e "$DEST/$top" ]; then
      echo "$top already exists in destination; pass $FORCE_FLAG to overwrite" >&2
      exit 1
    fi
  done < <(tar -tzf "$ARCHIVE" | cut -d/ -f1 | sort -u)
fi
tar -xzf "$ARCHIVE" -C "$DEST"
echo "restored: $ARCHIVE -> $DEST"
