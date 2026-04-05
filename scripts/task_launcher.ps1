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

Write-Host "[$taskName] 当前目标目录：$targetRoot"

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "未找到 Python 解释器：$pythonExe"
}

if (-not (Test-Path -LiteralPath $mainScript)) {
    throw "未找到主脚本：$mainScript"
}

Set-Location -LiteralPath $targetRoot
$env:FROM_SCHEDULED_TASK = "1"

Write-Host "[$taskName] 正在启动 main.py"
& $pythonExe $mainScript
$exitCode = $LASTEXITCODE

if ($null -eq $exitCode) {
    $exitCode = 0
}

exit $exitCode
