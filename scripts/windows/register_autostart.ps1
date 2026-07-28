param(
    [string]$TaskName = "AI Job Search Copilot"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$startScript = (Resolve-Path (Join-Path $PSScriptRoot "start_job_copilot.ps1")).Path
$actionArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Job Copilot API, Telegram bot and n8n supervisor" `
    -Force | Out-Null

Write-Host "Автозапуск зарегистрирован: $TaskName"
