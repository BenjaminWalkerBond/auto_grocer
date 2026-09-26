#!/usr/bin/env bash
# SessionStart hook for the Grocery Ordering agent.
# Reminds the agent to validate the HEB session before proceeding.
# This writes a marker file that the agent's instructions reference.

set -euo pipefail

MARKER_FILE="${GITHUB_WORKSPACE:-.}/.github/agents/handoffs/session-check-needed.md"

# Always create the marker at session start - agent instructions will handle the check
mkdir -p "$(dirname "$MARKER_FILE")"
cat > "$MARKER_FILE" << 'EOF'
# Session Check Pending

The Grocery Ordering agent has started. Before using any HEB tools, you MUST:

1. Call `mcp_auto-grocer_auth_status` to verify the session
2. If `authenticated: false`:
   - Run the **refresh-heb-login** skill
   - After that skill completes, call `mcp_auto-grocer_refresh_session`
   - Re-check `mcp_auto-grocer_auth_status`
3. If tools return `OPERATION_NOT_CAPTURED`:
   - Run the **refresh-graphql-hashes** skill
   - After that skill completes, call `mcp_auto-grocer_refresh_session`

Delete this file once the session is validated.
EOF

echo "Session validation reminder created at $MARKER_FILE"
