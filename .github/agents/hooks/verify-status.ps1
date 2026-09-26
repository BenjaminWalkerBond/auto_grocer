# SubagentStop hook: if a subagent stopped without updating the active status
# file (e.g. it crashed or hard-errored), inject an ERROR record so the
# Orchestrator can detect the failure and recover or escalate.
$ErrorActionPreference = 'Stop'
$handoffs = (Resolve-Path (Join-Path $PSScriptRoot '..\handoffs')).Path
$startFile = Join-Path $handoffs '.subagent_start'

# Active status file = newest *.md excluding the template. None => nothing to do.
$active = Get-ChildItem -Path $handoffs -Filter *.md -File |
  Where-Object { $_.Name -ne 'STATUS-template.md' } |
  Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if ($null -eq $active) { exit 0 }

$startTs = 0
if (Test-Path $startFile) { $startTs = [int64]((Get-Content $startFile -Raw).Trim()) }

$fileTs = ([DateTimeOffset]$active.LastWriteTimeUtc).ToUnixTimeSeconds()

if ($fileTs -lt $startTs) {
  $ts = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  $block = "`n## ERROR (auto-injected by SubagentStop hook) $ts`nstatus: ERROR`nreason: Subagent stopped without updating the status file (possible crash or hard error)."
  Add-Content -Path $active.FullName -Value $block
  Write-Output "SubagentStop: status file '$($active.Name)' was not updated by the subagent; injected ERROR record."
}
exit 0
