# SessionStart hook for the Grocery Ordering agent (Windows).
# Reminds the agent to validate the HEB session before proceeding.

$ErrorActionPreference = "Stop"

$workspaceRoot = if ($env:GITHUB_WORKSPACE) { $env:GITHUB_WORKSPACE } else { Get-Location }
$markerFile = Join-Path $workspaceRoot ".github/agents/handoffs/session-check-needed.md"

# Ensure directory exists
$markerDir = Split-Path -Parent $markerFile
if (-not (Test-Path $markerDir)) {
    New-Item -ItemType Directory -Path $markerDir -Force | Out-Null
}

# Write the marker file
$content = @"
# Session Check Pending

The Grocery Ordering agent has started. Before using any HEB tools, you MUST:

1. Call ``mcp_auto-grocer_auth_status`` to verify the session
2. If ``authenticated: false``:
   - Run the **refresh-heb-login** skill
   - After that skill completes, call ``mcp_auto-grocer_refresh_session``
   - Re-check ``mcp_auto-grocer_auth_status``
3. If tools return ``OPERATION_NOT_CAPTURED``:
   - Run the **refresh-graphql-hashes** skill
   - After that skill completes, call ``mcp_auto-grocer_refresh_session``

Delete this file once the session is validated.
"@

Set-Content -Path $markerFile -Value $content -Encoding UTF8

Write-Host "Session validation reminder created at $markerFile"
