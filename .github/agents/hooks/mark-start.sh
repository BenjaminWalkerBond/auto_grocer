#!/usr/bin/env bash
# SubagentStart hook: record when a subagent begins so the SubagentStop hook can
# tell whether the subagent updated the shared status file during its run.
set -euo pipefail
handoffs="$(cd "$(dirname "${BASH_SOURCE[0]}")/../handoffs" && pwd)"
date +%s > "$handoffs/.subagent_start"
