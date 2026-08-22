<#
.SYNOPSIS
    Registers the auto-grocer MCP server with Claude Desktop.

.DESCRIPTION
    Adds (or updates) an "auto-grocer" entry in Claude Desktop's
    claude_desktop_config.json so Claude launches the MCP server over stdio via
    Docker Compose. The absolute path to docker/docker-compose.yml is computed
    automatically from this script's location, so you can run it from anywhere.

    The existing config is backed up to claude_desktop_config.json.bak before any
    change is written. Other MCP servers and settings are preserved.

.NOTES
    Run this AFTER building the Docker image:
        docker compose -f docker/docker-compose.yml build mcp

.EXAMPLE
    ./scripts/add-to-claude.ps1
#>
[CmdletBinding()]
param(
    # Override the Claude Desktop config path if you use a non-standard location.
    [string]$ConfigPath = (Join-Path $env:APPDATA 'Claude\claude_desktop_config.json')
)

$ErrorActionPreference = 'Stop'

# Repo root is the parent of the folder containing this script (scripts/..).
$repoRoot = Split-Path -Parent $PSScriptRoot
$composePath = Join-Path $repoRoot 'docker\docker-compose.yml'

if (-not (Test-Path $composePath)) {
    throw "Could not find docker-compose.yml at '$composePath'. Run this script from inside the auto_grocer clone."
}

# Claude Desktop needs forward slashes in JSON, even on Windows.
$composePathJson = ($composePath -replace '\\', '/')

Write-Host "Repo root:      $repoRoot"
Write-Host "Compose file:   $composePathJson"
Write-Host "Claude config:  $ConfigPath"
Write-Host ""

# Load existing config or start a fresh object.
if (Test-Path $ConfigPath) {
    try {
        $config = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
    }
    catch {
        throw "Existing config at '$ConfigPath' is not valid JSON. Fix or remove it, then re-run."
    }
    # Back up before modifying.
    $backupPath = "$ConfigPath.bak"
    Copy-Item -Path $ConfigPath -Destination $backupPath -Force
    Write-Host "Backed up existing config to $backupPath"
}
else {
    $config = [PSCustomObject]@{}
    $configDir = Split-Path -Parent $ConfigPath
    if (-not (Test-Path $configDir)) {
        New-Item -ItemType Directory -Path $configDir -Force | Out-Null
    }
    Write-Host "No existing config found — creating a new one."
}

# Ensure mcpServers exists.
$hasMcpServers = ($config.PSObject.Properties.Name -contains 'mcpServers') -and ($null -ne $config.mcpServers)
if (-not $hasMcpServers) {
    $config | Add-Member -NotePropertyName 'mcpServers' -NotePropertyValue ([PSCustomObject]@{}) -Force
}

# Build the auto-grocer entry.
$entry = [PSCustomObject]@{
    command = 'docker'
    args    = @(
        'compose',
        '-f', $composePathJson,
        'run', '--rm', '-T', 'mcp'
    )
}

$config.mcpServers | Add-Member -NotePropertyName 'auto-grocer' -NotePropertyValue $entry -Force

# Write it back (pretty-printed).
$config | ConvertTo-Json -Depth 10 | Set-Content -Path $ConfigPath -Encoding UTF8

Write-Host ""
Write-Host "Added 'auto-grocer' to Claude Desktop config." -ForegroundColor Green
Write-Host "Restart Claude Desktop, then ask it to call auth_status to verify."
