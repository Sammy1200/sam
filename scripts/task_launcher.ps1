$ErrorActionPreference = "Stop"

$taskName = "codex-PYjiaoben-Launcher"
$formalProjectRoot = Split-Path -Parent $PSScriptRoot
$configDir = Join-Path $env:LOCALAPPDATA "codex-PYjiaoben"
$targetFile = Join-Path $configDir "task_target_path.txt"
$targetRoot = $formalProjectRoot

if (Test-Path -LiteralPath $targetFile) {
    $savedPath = (Get-Content -LiteralPath $targetFile -Raw).Trim()
    if ($savedPath) {
        $targetRoot = $savedPath
    }
}

$pythonExe = Join-Path $targetRoot ".venv\Scripts\python.exe"
$mainScript = Join-Path $targetRoot "main.py"

Write-Host "[$taskName] Target root: $targetRoot"

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}

if (-not (Test-Path -LiteralPath $mainScript)) {
    throw "main.py not found: $mainScript"
}

Set-Location -LiteralPath $targetRoot
$env:FROM_SCHEDULED_TASK = "1"

Write-Host "[$taskName] Starting main.py"
& $pythonExe $mainScript
$exitCode = $LASTEXITCODE

if ($null -eq $exitCode) {
    $exitCode = 0
}

exit $exitCode
