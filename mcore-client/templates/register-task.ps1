# mcore-client Windows 登录自启（计划任务，用户态）
#
# 设计约束：受控电脑严禁注册系统服务；此处仅注册"当前用户登录时触发"的计划任务，
# 进程以当前用户身份在前台运行，不写注册表服务表、不要求管理员权限。
#
# 用法（PowerShell，普通权限即可）：
#   powershell -ExecutionPolicy Bypass -File register-task.ps1
# 卸载：
#   powershell -ExecutionPolicy Bypass -File register-task.ps1 -Uninstall

param(
    [switch]$Uninstall
)

$TaskName = "mcore-client"
$NodeExe  = (Get-Command node -ErrorAction SilentlyContinue).Source
$ScriptPath = Join-Path $env:USERPROFILE ".mcore\mcore-client.js"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "已移除计划任务: $TaskName"
    exit 0
}

if (-not $NodeExe) {
    Write-Error "未找到 node，请先安装 Node.js (>= 18)"
    exit 1
}
if (-not (Test-Path $ScriptPath)) {
    Write-Error "未找到客户端脚本: $ScriptPath"
    exit 1
}

$Action = New-ScheduledTaskAction -Execute $NodeExe `
    -Argument "`"$ScriptPath`" start" `
    -WorkingDirectory $env:USERPROFILE

# 登录时触发 + 失败自动重启（等价于守护）
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "MemoryCore 本地接入边车（用户态，登录自启）" `
    -Force | Out-Null

Write-Host "已注册计划任务: $TaskName"
Write-Host "  命令: $NodeExe `"$ScriptPath`" start"
Write-Host "  触发: 用户登录时（用户态，非系统服务）"
Write-Host ""
Write-Host "查看状态: Get-ScheduledTask -TaskName $TaskName"
Write-Host "立即启动: Start-ScheduledTask -TaskName $TaskName"
