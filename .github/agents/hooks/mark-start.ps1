# SubagentStart hook: record when a subagent begins so the SubagentStop hook can
# tell whether the subagent updated the shared status file during its run.
$ErrorActionPreference = 'Stop'
$handoffs = (New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot '..\handoffs')).FullName
$startFile = Join-Path $handoffs '.subagent_start'
[DateTimeOffset]::UtcNow.ToUnixTimeSeconds() | Out-File -FilePath $startFile -Encoding ascii
