#!/usr/bin/env bash
# Kill and relaunch Claude Desktop (Windows app) from a WSL/bash shell — thin
# wrapper around scripts/restart-claude.ps1, for quickly testing MCP config
# changes without leaving the terminal you're already working in.
#
# Requires PowerShell 7 (pwsh.exe) so it doesn't hit the UTF-8 decoding issues
# Windows PowerShell 5.1 has with this repo's em-dash comments.
#
# Usage:
#   ./scripts/restart-claude.sh              # kill + relaunch
#   ./scripts/restart-claude.sh --tail-log    # kill + relaunch + tail the MCP log
#   ./scripts/restart-claude.sh --no-relaunch # just kill
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ps1_path="$script_dir/restart-claude.ps1"

if ! command -v pwsh.exe >/dev/null 2>&1; then
  echo "Error: pwsh.exe (PowerShell 7) not found on PATH." >&2
  echo "Install it on Windows, or run scripts/restart-claude.ps1 directly from PowerShell." >&2
  exit 1
fi

# This repo lives under OneDrive. wslpath.exe resolves paths via Windows
# interop, which can briefly 404 a just-created/just-synced file even though
# WSL's own /mnt/c (DrvFs) view already sees it — retry a few times instead of
# failing on a transient race.
if [[ ! -f "$ps1_path" ]]; then
  echo "Error: $ps1_path not found." >&2
  exit 1
fi

win_script=""
for _ in 1 2 3 4 5; do
  if win_script="$(wslpath -w "$ps1_path" 2>/dev/null)"; then
    break
  fi
  win_script=""
  sleep 0.5
done

if [[ -z "$win_script" ]]; then
  echo "Error: wslpath could not resolve '$ps1_path' after retries." >&2
  echo "If this repo is under OneDrive, it may still be syncing the new file — wait a moment and re-run." >&2
  exit 1
fi

ps_args=()
for arg in "$@"; do
  case "$arg" in
    --tail-log) ps_args+=("-TailLog") ;;
    --no-relaunch) ps_args+=("-NoRelaunch") ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

exec pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "$win_script" "${ps_args[@]}"
