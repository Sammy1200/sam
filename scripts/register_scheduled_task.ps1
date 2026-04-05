$ErrorActionPreference = "Stop"

$taskName = "codex-PYjiaoben-Launcher"
$projectRoot = Split-Path -Parent $PSScriptRoot
$launcherScript = Join-Path $PSScriptRoot "task_launcher.ps1"
$powershellExe = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path -LiteralPath $launcherScript)) {
    throw "未找到任务启动脚本：$launcherScript"
}

$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$currentUser = $currentIdentity.Name

$action = New-ScheduledTaskAction `
    -Execute $powershellExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$launcherScript`""

$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -StartWhenAvailable

$description = "codex-PYjiaoben 固定高权限启动器。统一由计划任务读取本地目标目录并启动 main.py。"

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Principal $principal `
    -Settings $settings `
    -Description $description `
    -Force | Out-Null

Write-Host "计划任务已注册/更新：$taskName"
Write-Host "启动脚本：$launcherScript"
Write-Host "默认正式根目录：$projectRoot"
