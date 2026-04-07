$bypassEnvName = "CODEX_PYJIAOBEN_RUN_VIA_TASK_BYPASS"
$currentBypassMarker = [Environment]::GetEnvironmentVariable($bypassEnvName, "Process")
$powershellExe = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not $currentBypassMarker) {
    $processPolicy = Get-ExecutionPolicy -Scope Process
    if ($processPolicy -ne "Bypass" -and (Test-Path -LiteralPath $powershellExe)) {
        Write-Host "检测到当前 PowerShell 进程未显式使用 Bypass，正在切换到受控启动器进程..."
        [Environment]::SetEnvironmentVariable($bypassEnvName, "1", "Process")
        try {
            & $powershellExe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath @args
            $relayExitCode = $LASTEXITCODE
            if ($null -eq $relayExitCode) {
                $relayExitCode = 0
            }
            exit $relayExitCode
        }
        finally {
            [Environment]::SetEnvironmentVariable($bypassEnvName, $null, "Process")
        }
    }
}

$ErrorActionPreference = "Stop"

$taskName = "codex-PYjiaoben-Launcher"
$projectRoot = Split-Path -Parent $PSScriptRoot
$configDir = Join-Path $env:LOCALAPPDATA "codex-PYjiaoben"
$targetFile = Join-Path $configDir "task_target_path.txt"

if (-not (Test-Path -LiteralPath $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}

Set-Content -LiteralPath $targetFile -Value $projectRoot -Encoding UTF8
Write-Host "已写入本次启动目标目录：$projectRoot"
Write-Host "本地配置文件：$targetFile"

$taskExists = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $taskExists) {
    throw "未找到计划任务：$taskName。请先运行 .\scripts\register_scheduled_task.ps1"
}

$runOutput = & schtasks.exe /Run /TN $taskName 2>&1
$runText = ($runOutput | Out-String).Trim()

if ($LASTEXITCODE -ne 0) {
    throw "计划任务触发失败：$runText"
}

if ($runText) {
    Write-Host $runText
}

Write-Host "已触发计划任务：$taskName"
