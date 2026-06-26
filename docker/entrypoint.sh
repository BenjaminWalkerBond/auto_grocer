#!/usr/bin/env bash
# Entrypoint for the auto_grocier MCP container.
#
# Starts a virtual X display (Xvfb) on $DISPLAY so the nodriver login flow has a
# screen to drive Chromium headfully, then execs the requested command (default:
# the MCP stdio server). Xvfb runs in the background; if it's already up on the
# target display we skip it.
set -euo pipefail

DISPLAY="${DISPLAY:-:99}"
SCREEN="${XVFB_SCREEN:-1920x1080x24}"

# Start Xvfb only if nothing is already listening on this display.
lock="/tmp/.X${DISPLAY#:}-lock"
if [ ! -e "$lock" ]; then
    Xvfb "$DISPLAY" -screen 0 "$SCREEN" -nolisten tcp >/tmp/xvfb.log 2>&1 &
    # Give Xvfb a moment to come up.
    for _ in $(seq 1 20); do
        [ -e "$lock" ] && break
        sleep 0.2
    done
fi

export DISPLAY
exec "$@"
