$ErrorActionPreference = "Stop"

$taskName = "codex-PYjiaoben-Launcher"
$projectRoot = Split-Path -Parent $PSScriptRoot
$launcherScript = Join-Path $PSScriptRoot "task_launcher.ps1"
$powershellExe = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"

function Test-IsAdministrator {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    Write-Host "正在申请管理员权限以注册计划任务..."
    $arguments = @(
        "-NoProfile"
        "-ExecutionPolicy"
        "Bypass"
        "-File"
        ('"{0}"' -f $PSCommandPath)
    )
    Start-Process -FilePath $powershellExe -ArgumentList $arguments -Verb RunAs | Out-Null
    exit 0
}

if (-not (Test-Path -LiteralPath $launcherScript)) {
    throw "未找到计划任务启动脚本：$launcherScript"
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

$description = "codex-PYjiaoben 固定高权限启动器。计划任务从本地配置读取目标目录并启动 main.py。"

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Principal $principal `
    -Settings $settings `
    -Description $description `
    -ErrorAction Stop `
    -Force | Out-Null

Write-Host "计划任务已创建或更新：$taskName"
Write-Host "计划任务启动脚本：$launcherScript"
Write-Host "默认回退目录：$projectRoot"
