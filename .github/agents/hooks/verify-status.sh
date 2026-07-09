#!/usr/bin/env bash
# SubagentStop hook: if a subagent stopped without updating the active status
# file (e.g. it crashed or hard-errored), inject an ERROR record so the
# Orchestrator can detect the failure and recover or escalate.
set -euo pipefail

handoffs="$(cd "$(dirname "${BASH_SOURCE[0]}")/../handoffs" && pwd)"
start_file="$handoffs/.subagent_start"

# Active status file = newest *.md excluding the template. None => nothing to do.
active="$(ls -t "$handoffs"/*.md 2>/dev/null | grep -v 'STATUS-template.md' | head -n1 || true)"
[ -z "$active" ] && exit 0

start_ts=0
[ -f "$start_file" ] && start_ts="$(cat "$start_file" 2>/dev/null || echo 0)"

# Modification time of the active status file (GNU stat, then BSD stat fallback).
file_ts="$(stat -c %Y "$active" 2>/dev/null || stat -f %m "$active" 2>/dev/null || echo 0)"

if [ "$file_ts" -lt "$start_ts" ]; then
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  {
    echo ""
    echo "## ERROR (auto-injected by SubagentStop hook) $ts"
    echo "status: ERROR"
    echo "reason: Subagent stopped without updating the status file (possible crash or hard error)."
  } >> "$active"
  echo "SubagentStop: status file '$active' was not updated by the subagent; injected ERROR record."
fi
exit 0
