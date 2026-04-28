# Syncs MPESA_CALLBACK_URL and ALLOWED_HOSTS in .env from a running ngrok tunnel.
# Prerequisite (one time): install ngrok from https://ngrok.com/download then:
#   ngrok config add-authtoken <your_token>
#
# Usage:
#   1. Start Django:  .\.venv\Scripts\python manage.py runserver
#   2. In another terminal:  powershell -ExecutionPolicy Bypass -File .\scripts\dev_with_ngrok.ps1
#   3. Restart Django so it reloads .env
#
# If ngrok is not already running, this script starts it in a new window (port 8000).

param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$EnvFile = Join-Path $ProjectRoot ".env"

function Get-NgrokHttpsUrl {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 3
        foreach ($t in $resp.tunnels) {
            if ($t.public_url -like "https://*") {
                return $t.public_url.TrimEnd("/")
            }
        }
    }
    catch {
        return $null
    }
    return $null
}

if (-not (Test-Path $EnvFile)) {
    Write-Error ".env not found at $EnvFile"
    exit 1
}

$ngrokCmd = Get-Command ngrok -ErrorAction SilentlyContinue
if (-not $ngrokCmd) {
    Write-Error @"
ngrok is not in PATH. For this school project:
  1. Download: https://ngrok.com/download
  2. Unzip ngrok.exe somewhere and add that folder to PATH, OR run this script from that folder.
  3. One-time: ngrok config add-authtoken <token from https://dashboard.ngrok.com/>
"@
    exit 1
}

$url = Get-NgrokHttpsUrl
if (-not $url) {
    Write-Host "Starting ngrok in a new window (http $Port)..." -ForegroundColor Cyan
    Start-Process -FilePath "ngrok" -ArgumentList @("http", "$Port") -WindowStyle Normal
    for ($i = 0; $i -lt 25; $i++) {
        Start-Sleep -Milliseconds 600
        $url = Get-NgrokHttpsUrl
        if ($url) { break }
    }
}

if (-not $url) {
    Write-Error "Could not read ngrok URL from http://127.0.0.1:4040/api/tunnels. Is ngrok authenticated? Run: ngrok config add-authtoken <token>"
    exit 1
}

$uri = [Uri]$url
$hostOnly = $uri.Host
$callback = "$url/sales/mpesa/callback/"
$allowed = "127.0.0.1,localhost,$hostOnly"

$lines = @(Get-Content -LiteralPath $EnvFile)
$newLines = foreach ($line in $lines) {
    if ($line -match '^\s*MPESA_CALLBACK_URL=') {
        "MPESA_CALLBACK_URL=$callback"
    }
    elseif ($line -match '^\s*ALLOWED_HOSTS=') {
        "ALLOWED_HOSTS=$allowed"
    }
    else {
        $line
    }
}

# If keys were missing, append (unlikely)
$hasCallback = $false
$hasHosts = $false
foreach ($line in $newLines) {
    if ($line -match '^\s*MPESA_CALLBACK_URL=') { $hasCallback = $true }
    if ($line -match '^\s*ALLOWED_HOSTS=') { $hasHosts = $true }
}
if (-not $hasCallback) { $newLines += "MPESA_CALLBACK_URL=$callback" }
if (-not $hasHosts) { $newLines += "ALLOWED_HOSTS=$allowed" }

$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllLines($EnvFile, @($newLines), $utf8NoBom)

Write-Host ""
Write-Host "Updated .env for this ngrok session:" -ForegroundColor Green
Write-Host "  MPESA_CALLBACK_URL=$callback"
Write-Host "  ALLOWED_HOSTS=$allowed"
Write-Host ""
Write-Host "Next: stop Django (Ctrl+C) and start again:" -ForegroundColor Yellow
Write-Host "  .\.venv\Scripts\python manage.py runserver"
Write-Host ""
Write-Host "Daraja: if your app validates the callback URL, set it to the line above." -ForegroundColor DarkGray
