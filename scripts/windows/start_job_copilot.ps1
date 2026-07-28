param(
    [switch]$WithoutN8n
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$pythonExecutable = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logsDirectory = Join-Path $projectRoot "logs"
$n8nUserFolder = Join-Path $projectRoot "data\n8n"

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "Не найдено .venv. Сначала запустите scripts\windows\setup_native.ps1."
}

New-Item -ItemType Directory -Path $logsDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $n8nUserFolder -Force | Out-Null
$env:PYTHONUNBUFFERED = "1"
$env:N8N_USER_FOLDER = $n8nUserFolder
$env:N8N_HOST = "127.0.0.1"
$env:N8N_PORT = "5678"
$env:N8N_PROTOCOL = "http"
$env:N8N_DIAGNOSTICS_ENABLED = "false"
$env:N8N_PERSONALIZATION_ENABLED = "false"

$processSpecs = @(
    [pscustomobject]@{
        Name = "api"
        Executable = $pythonExecutable
        Arguments = @("-m", "uvicorn", "job_copilot.api:app", "--host", "127.0.0.1", "--port", "8000")
    },
    [pscustomobject]@{
        Name = "telegram-bot"
        Executable = $pythonExecutable
        Arguments = @("-m", "job_copilot.cli", "telegram-bot")
    }
)

if (-not $WithoutN8n) {
    $n8nCommand = Get-Command n8n.cmd -ErrorAction SilentlyContinue
    if ($null -eq $n8nCommand) {
        throw "n8n.cmd не найден. Запустите setup_native.ps1 или используйте -WithoutN8n."
    }
    $processSpecs += [pscustomobject]@{
        Name = "n8n"
        Executable = $n8nCommand.Source
        Arguments = @("start")
    }
}

$managed = @{}

function Start-ManagedProcess {
    param([pscustomobject]$Spec)

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $stdoutPath = Join-Path $logsDirectory "$($Spec.Name)-$timestamp.out.log"
    $stderrPath = Join-Path $logsDirectory "$($Spec.Name)-$timestamp.err.log"
    $process = Start-Process `
        -FilePath $Spec.Executable `
        -ArgumentList $Spec.Arguments `
        -WorkingDirectory $projectRoot `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -WindowStyle Hidden `
        -PassThru
    $managed[$Spec.Name] = $process
    Write-Host "Запущен $($Spec.Name), PID $($process.Id)"
}

try {
    foreach ($spec in $processSpecs) {
        Start-ManagedProcess $spec
    }
    while ($true) {
        Start-Sleep -Seconds 5
        foreach ($spec in $processSpecs) {
            $process = $managed[$spec.Name]
            if ($process.HasExited) {
                Write-Warning "$($spec.Name) завершился с кодом $($process.ExitCode); перезапуск."
                Start-ManagedProcess $spec
            }
        }
    }
}
finally {
    foreach ($process in $managed.Values) {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
        }
    }
}
