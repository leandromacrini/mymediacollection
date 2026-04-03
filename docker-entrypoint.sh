#!/bin/sh
set -eu

mkdir -p "${HOME:-/tmp/filebot-home}"

LICENSE_FILE="${FILEBOT_LICENSE_FILE:-/licenses/FileBot_License.psm}"
DEFAULT_LICENSE_FILE="/licenses/FileBot_License.psm"

if [ ! -f "$LICENSE_FILE" ] && [ -f "$DEFAULT_LICENSE_FILE" ]; then
  LICENSE_FILE="$DEFAULT_LICENSE_FILE"
fi

if command -v filebot >/dev/null 2>&1; then
  if [ -f "$LICENSE_FILE" ]; then
    if filebot -script fn:sysinfo >/tmp/filebot-sysinfo.txt 2>/tmp/filebot-sysinfo.err; then
      if ! grep -q "License:.*Valid-Until" /tmp/filebot-sysinfo.txt; then
        echo "[filebot] activating license from $LICENSE_FILE"
        filebot --license "$LICENSE_FILE" >/tmp/filebot-license.txt 2>/tmp/filebot-license.err || true
      fi
    else
      echo "[filebot] sysinfo check failed, trying license activation"
      filebot --license "$LICENSE_FILE" >/tmp/filebot-license.txt 2>/tmp/filebot-license.err || true
    fi
  else
    echo "[filebot] license file not found at $LICENSE_FILE"
  fi
else
  echo "[filebot] binary not found in PATH"
fi

exec "$@"
