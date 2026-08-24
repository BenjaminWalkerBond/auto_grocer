<#
.SYNOPSIS
    Kills and relaunches Claude Desktop, for quickly testing MCP config changes.

.DESCRIPTION
    Claude Desktop only re-reads claude_desktop_config.json on startup, so after
    editing it (e.g. via add-to-claude.ps1) you need to fully restart the app.
    This script:
      1. Kills all running Claude processes (main window + Electron helpers).
      2. Waits for them to fully exit.
      3. Relaunches Claude via its packaged-app identity (shell:AppsFolder), since
         Claude Desktop ships as an MSIX package — running the .exe path directly
         can misbehave for packaged apps, so this uses the same launch mechanism
         the Start Menu uses. The AppID is looked up dynamically (falls back to
         the last-known value if lookup fails, e.g. after an app update changes
         the install path).
      4. Optionally tails the auto-grocer MCP server log so you can immediately
         see whether the new config connected.

.PARAMETER NoRelaunch
    Only kill Claude; don't start it again.

.PARAMETER TailLog
    After relaunching, tail the auto-grocer MCP server log (waits for new
    activity — press Ctrl+C to stop watching once you've seen enough).

.PARAMETER WaitSeconds
    Seconds to wait after killing Claude before relaunching (default 2).

.EXAMPLE
    ./scripts/restart-claude.ps1
.EXAMPLE
    ./scripts/restart-claude.ps1 -TailLog
.EXAMPLE
    ./scripts/restart-claude.ps1 -NoRelaunch
#>
[CmdletBinding()]
param(
    [switch]$NoRelaunch,
    [switch]$TailLog,
    [int]$WaitSeconds = 2
)

$ErrorActionPreference = 'Stop'

# Last-known AppUserModelID for the Claude Desktop MSIX package, used as a
# fallback if a fresh Get-StartApps lookup fails (e.g. transient shell issue).
$fallbackAppId = 'Claude_pzs8sxrjxfjjc!Claude'

Write-Host "Looking for running Claude processes..."
$procs = Get-Process -Name 'claude' -ErrorAction SilentlyContinue

if (-not $procs) {
    Write-Host "No Claude process is currently running."
}
else {
    Write-Host "Killing $($procs.Count) Claude process(es)..."
    $procs | Stop-Process -Force -ErrorAction SilentlyContinue

    # Wait for a clean exit (packaged Electron apps can take a moment).
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Name 'claude' -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 300
    }
    if (Get-Process -Name 'claude' -ErrorAction SilentlyContinue) {
        Write-Warning "Some Claude process(es) did not exit within 10s; continuing anyway."
    }
    else {
        Write-Host "Claude fully exited."
    }
}

if ($NoRelaunch) {
    Write-Host "NoRelaunch set — not starting Claude again."
    return
}

Start-Sleep -Seconds $WaitSeconds

# Resolve the packaged app's launch ID. Claude Desktop ships as an MSIX package,
# so `& "...\Claude.exe"` directly can fail/misbehave; shell:AppsFolder is the
# same mechanism the Start Menu / taskbar use to launch packaged apps.
$appId = $fallbackAppId
try {
    $found = Get-StartApps | Where-Object { $_.Name -eq 'Claude' } | Select-Object -First 1
    if ($found) { $appId = $found.AppID }
}
catch {
    Write-Warning "Get-StartApps lookup failed; using last-known AppID ($fallbackAppId)."
}

Write-Host "Relaunching Claude (AppID: $appId)..."
Start-Process "shell:AppsFolder\$appId"

if ($TailLog) {
    $logPath = Join-Path $env:LOCALAPPDATA 'Claude\logs\mcp-server-auto-grocer.log'
    Write-Host ""
    Write-Host "Waiting for Claude to start logging, then tailing:"
    Write-Host "  $logPath"
    Write-Host "(Ctrl+C to stop watching once you see 'Server started and connected successfully'.)"
    Write-Host ""

    $deadline = (Get-Date).AddSeconds(20)
    while (-not (Test-Path $logPath) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
    }
    if (Test-Path $logPath) {
        Get-Content -Path $logPath -Wait -Tail 20
    }
    else {
        Write-Warning "Log file did not appear within 20s: $logPath"
    }
}
else {
    Write-Host "Done. Ask Claude to call auth_status once it's back up."
}
