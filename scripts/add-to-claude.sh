#!/usr/bin/env bash
# Registers the auto-grocer MCP server with Claude Desktop.
#
# Adds (or updates) an "auto-grocer" entry in Claude Desktop's
# claude_desktop_config.json so Claude launches the MCP server over stdio via
# Docker Compose. The absolute path to docker/docker-compose.yml is computed
# automatically from this script's location, so you can run it from anywhere.
#
# The existing config is backed up to claude_desktop_config.json.bak before any
# change is written. Other MCP servers and settings are preserved.
#
# Run this AFTER building the Docker image:
#   docker compose -f docker/docker-compose.yml build mcp
#
# Usage:
#   ./scripts/add-to-claude.sh
#
# Requires: jq (https://jqlang.github.io/jq/). Install with `brew install jq`
# (macOS) or `sudo apt-get install jq` (Debian/Ubuntu).
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is required but not installed." >&2
  echo "  macOS:  brew install jq" >&2
  echo "  Ubuntu: sudo apt-get install jq" >&2
  exit 1
fi

# Repo root is the parent of the folder containing this script (scripts/..).
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
compose_path="$repo_root/docker/docker-compose.yml"

if [[ ! -f "$compose_path" ]]; then
  echo "Error: could not find docker-compose.yml at '$compose_path'." >&2
  echo "Run this script from inside the auto_grocer clone." >&2
  exit 1
fi

# Which compose service Claude launches (default: mcp). Set
# MCP_SERVICE=mcp-patchright to test the experimental patchright login engine.
mcp_service="${MCP_SERVICE:-mcp}"

# Detect WSL so we register the *Windows* Claude Desktop (not the Linux config)
# and hand Docker Desktop a Windows-style compose path it understands.
is_wsl=0
if grep -qiE '(microsoft|wsl)' /proc/version 2>/dev/null; then
  is_wsl=1
fi

# Compose path exactly as Claude/Docker will consume it (forward slashes). On
# WSL that means the Windows drive path (C:/...), not /mnt/c/...
if [[ "$is_wsl" -eq 1 ]] && command -v wslpath >/dev/null 2>&1; then
  compose_path_json="$(wslpath -w "$compose_path" | sed 's#\\#/#g')"
  env_path_json="$(wslpath -w "$repo_root/.env" | sed 's#\\#/#g')"
else
  compose_path_json="$compose_path"
  env_path_json="$repo_root/.env"
fi

# Resolve the Claude Desktop config path (override with $1).
if [[ -n "${1:-}" ]]; then
  config_path="$1"
elif [[ "$is_wsl" -eq 1 ]]; then
  # WSL: write to the Windows Claude Desktop config under %APPDATA%.
  win_appdata="$(cmd.exe /c 'echo %APPDATA%' 2>/dev/null | tr -d '\r')"
  if [[ -n "$win_appdata" ]] && command -v wslpath >/dev/null 2>&1; then
    config_path="$(wslpath -u "$win_appdata")/Claude/claude_desktop_config.json"
  else
    config_path="${XDG_CONFIG_HOME:-$HOME/.config}/Claude/claude_desktop_config.json"
  fi
elif [[ "$(uname)" == "Darwin" ]]; then
  config_path="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
else
  # Linux
  config_path="${XDG_CONFIG_HOME:-$HOME/.config}/Claude/claude_desktop_config.json"
fi

echo "Repo root:      $repo_root"
echo "Compose file:   $compose_path_json"
echo "Env file:       $env_path_json"
echo "MCP service:    $mcp_service"
echo "Claude config:  $config_path"
echo ""

# Load existing config or start from an empty object.
if [[ -f "$config_path" ]]; then
  if ! jq empty "$config_path" >/dev/null 2>&1; then
    echo "Error: existing config at '$config_path' is not valid JSON." >&2
    echo "Fix or remove it, then re-run." >&2
    exit 1
  fi
  cp "$config_path" "$config_path.bak"
  echo "Backed up existing config to $config_path.bak"
  base="$(cat "$config_path")"
else
  mkdir -p "$(dirname "$config_path")"
  base='{}'
  echo "No existing config found — creating a new one."
fi

# Merge the auto-grocer entry into mcpServers, preserving everything else.
echo "$base" | jq \
  --arg compose "$compose_path_json" \
  --arg envfile "$env_path_json" \
  --arg service "$mcp_service" \
  '.mcpServers = (.mcpServers // {}) |
   .mcpServers["auto-grocer"] = {
     "command": "docker",
     "args": ["compose", "--env-file", $envfile, "-f", $compose, "run", "--rm", "-T", $service]
   }' > "$config_path"

echo ""
echo "Added 'auto-grocer' (service: $mcp_service) to Claude Desktop config."
echo "Restart Claude Desktop, then ask it to call auth_status to verify."
