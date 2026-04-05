$ErrorActionPreference = "Stop"

$taskName = "codex-PYjiaoben-Launcher"
$projectRoot = Split-Path -Parent $PSScriptRoot
$configDir = Join-Path $env:LOCALAPPDATA "codex-PYjiaoben"
$targetFile = Join-Path $configDir "task_target_path.txt"

if (-not (Test-Path -LiteralPath $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}

Set-Content -LiteralPath $targetFile -Value $projectRoot -Encoding UTF8
Write-Host "Scheduled task target root saved: $projectRoot"

$taskExists = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $taskExists) {
    throw "Scheduled task not found: $taskName. Run scripts/register_scheduled_task.ps1 first."
}

$runOutput = & schtasks.exe /Run /TN $taskName 2>&1
$runText = ($runOutput | Out-String).Trim()

if ($LASTEXITCODE -ne 0) {
    throw "Scheduled task run failed: $runText"
}

if ($runText) {
    Write-Host $runText
}

Write-Host "Scheduled task triggered: $taskName"
