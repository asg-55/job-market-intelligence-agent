param(
    [string]$PythonExecutable = "python",
    [switch]$SkipN8n,
    [switch]$ConfigureOnly,
    [switch]$RotateAutomationToken
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$envPath = Join-Path $projectRoot ".env"
$envExamplePath = Join-Path $projectRoot ".env.example"

function Initialize-LocalEnvironment {
    if (-not (Test-Path -LiteralPath $envPath)) {
        Copy-Item -LiteralPath $envExamplePath -Destination $envPath
        Write-Host ".env создан из .env.example. Заполните Telegram-параметры перед запуском бота."
    }

    $envContent = [System.IO.File]::ReadAllText($envPath)
    if ($envContent -notmatch '(?m)^AUTOMATION_API_TOKEN=') {
        $envContent = $envContent.TrimEnd() + "`r`nAUTOMATION_API_TOKEN=`r`n"
    }
    if ($RotateAutomationToken) {
        $envContent = [regex]::Replace(
            $envContent,
            '(?m)^AUTOMATION_API_TOKEN=.*\r?$',
            'AUTOMATION_API_TOKEN=',
            1
        )
    }
    $tokenPattern = '(?m)^AUTOMATION_API_TOKEN=[ \t]*\r?$'
    if ($envContent -match $tokenPattern) {
        $secretBytes = [byte[]]::new(32)
        $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $random.GetBytes($secretBytes)
        }
        finally {
            $random.Dispose()
        }
        $automationToken = -join ($secretBytes | ForEach-Object { $_.ToString("x2") })
        $envContent = [regex]::Replace(
            $envContent,
            $tokenPattern,
            "AUTOMATION_API_TOKEN=$automationToken",
            1
        )
        [System.IO.File]::WriteAllText(
            $envPath,
            $envContent,
            [System.Text.UTF8Encoding]::new($false)
        )
        Write-Host "В .env создан внутренний токен автоматизации (значение не выводится)."
    }
}

function Assert-LastCommandSucceeded {
    param([string]$Operation)

    if ($LASTEXITCODE -ne 0) {
        throw "$Operation завершилась с кодом $LASTEXITCODE."
    }
}

Push-Location $projectRoot
try {
    Initialize-LocalEnvironment

    if (-not $ConfigureOnly) {
        if (-not (Get-Command $PythonExecutable -ErrorAction SilentlyContinue)) {
            throw "Python не найден. Установите Python 3.12 x64 и повторите команду."
        }
        if (-not (Test-Path -LiteralPath $venvPython)) {
            & $PythonExecutable -m venv .venv
            Assert-LastCommandSucceeded "Создание виртуального окружения"
        }
        & $venvPython -m pip install --upgrade pip
        Assert-LastCommandSucceeded "Обновление pip"
        & $venvPython -m pip install -e .
        Assert-LastCommandSucceeded "Установка Job Copilot"
    }

    if (-not $ConfigureOnly -and -not $SkipN8n) {
        if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
            throw "npm.cmd не найден. Установите Node.js LTS и повторите команду."
        }
        & npm.cmd install --global n8n@2.32.5 `
            --maxsockets=3 `
            --fetch-retries=5 `
            --fetch-timeout=600000
        Assert-LastCommandSucceeded "Установка n8n"
    }
}
finally {
    Pop-Location
}

Write-Host "Нативное окружение готово. Следующий шаг: настройте .env и импортируйте n8n workflow."
