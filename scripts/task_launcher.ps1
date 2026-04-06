$ErrorActionPreference = "Stop"

$taskName = "codex-PYjiaoben-Launcher"
$formalProjectRoot = Split-Path -Parent $PSScriptRoot
$configDir = Join-Path $env:LOCALAPPDATA "codex-PYjiaoben"
$targetFile = Join-Path $configDir "task_target_path.txt"
$targetRoot = $formalProjectRoot

if (Test-Path -LiteralPath $targetFile) {
    $savedPath = (Get-Content -LiteralPath $targetFile -Raw).Trim()
    if ($savedPath -and (Test-Path -LiteralPath $savedPath -PathType Container)) {
        $targetRoot = $savedPath
    } elseif ($savedPath) {
        Write-Host "[$taskName] 本地配置目录不存在，已回退到正式项目根目录：$formalProjectRoot"
    }
}

$pythonExe = Join-Path $targetRoot ".venv\Scripts\python.exe"
$mainScript = Join-Path $targetRoot "main.py"

Write-Host "[$taskName] 当前启动目录：$targetRoot"

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "[$taskName] 未找到 Python 解释器：$pythonExe"
}

if (-not (Test-Path -LiteralPath $mainScript)) {
    throw "[$taskName] 未找到入口脚本：$mainScript"
}

Set-Location -LiteralPath $targetRoot
$env:FROM_SCHEDULED_TASK = "1"

Write-Host "[$taskName] 已设置环境标记 FROM_SCHEDULED_TASK=1"
Write-Host "[$taskName] 准备启动 main.py"

& $pythonExe $mainScript
$exitCode = $LASTEXITCODE

if ($null -eq $exitCode) {
    $exitCode = 0
}

Write-Host "[$taskName] main.py 已退出，退出码：$exitCode"
exit $exitCode
