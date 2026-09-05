#!/bin/bash
# Double-clickable macOS launcher for SatQuery AI.
cd "$(dirname "$0")" || exit 1
chmod +x "./scripts/start-satquery.sh" 2>/dev/null || true
exec "./scripts/start-satquery.sh"
