param(
  [string]$RegistrationToken = "",
  [string]$Repository = "mihaicismaru-bit/civora",
  [string]$InstallDir = "C:\actions-runner-partener-mipe"
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$text) {
  Write-Host "`n=== $text ===" -ForegroundColor Cyan
}

function Ensure-Admin {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Se redeschide automat cu drepturi Administrator..." -ForegroundColor Yellow
    $args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$PSCommandPath`"")
    if ($RegistrationToken) { $args += @('-RegistrationToken',"`"$RegistrationToken`"") }
    $args += @('-Repository',"`"$Repository`"",'-InstallDir',"`"$InstallDir`"")
    Start-Process powershell.exe -Verb RunAs -ArgumentList ($args -join ' ')
    exit
  }
}

Ensure-Admin

Write-Host "PARTENER.EU — configurare colector MIPE România" -ForegroundColor Green
Write-Host "Această operațiune se face o singură dată. După aceea runnerul pornește automat cu Windows." -ForegroundColor Gray

if (-not $RegistrationToken) {
  Write-Host "`nAi nevoie de tokenul temporar de runner din GitHub:" -ForegroundColor Yellow
  Write-Host "Repository → Settings → Actions → Runners → New self-hosted runner → Windows/x64." -ForegroundColor Gray
  Write-Host "Copiază DOAR valoarea de după --token și lipește-o mai jos." -ForegroundColor Gray
  $RegistrationToken = Read-Host "Token runner"
}
if (-not $RegistrationToken) { throw 'Tokenul de înregistrare lipsește.' }

$repoUrl = "https://github.com/$Repository"
$runnerName = "PARTENER-MIPE-$env:COMPUTERNAME"

Write-Step "Pregătesc directorul"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Set-Location $InstallDir

if (Test-Path (Join-Path $InstallDir '.runner')) {
  Write-Step "Runnerul este deja configurat"
  $svc = Get-Service 'actions.runner.*' -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*PARTENER-MIPE*' } | Select-Object -First 1
  if (-not $svc) { $svc = Get-Service 'actions.runner.*' -ErrorAction SilentlyContinue | Select-Object -First 1 }
  if ($svc) {
    if ($svc.Status -ne 'Running') { Start-Service $svc.Name }
    Set-Service $svc.Name -StartupType Automatic
    Write-Host "OK — serviciul $($svc.Name) rulează și pornește automat." -ForegroundColor Green
    exit 0
  }
  throw 'Runner configurat, dar serviciul Windows nu a fost găsit. Elimină configurarea veche sau reconfigurează runnerul.'
}

Write-Step "Descarc ultima versiune GitHub Actions Runner"
$release = Invoke-RestMethod -Headers @{ 'User-Agent'='PARTENER.EU-MIPE-Setup' } -Uri 'https://api.github.com/repos/actions/runner/releases/latest'
$asset = $release.assets | Where-Object { $_.name -match '^actions-runner-win-x64-.*\.zip$' } | Select-Object -First 1
if (-not $asset) { throw 'Nu am găsit pachetul Windows x64 al GitHub Actions Runner.' }
$zip = Join-Path $env:TEMP $asset.name
Invoke-WebRequest -Headers @{ 'User-Agent'='PARTENER.EU-MIPE-Setup' } -Uri $asset.browser_download_url -OutFile $zip

Write-Step "Instalez runnerul"
Expand-Archive -Path $zip -DestinationPath $InstallDir -Force
Remove-Item $zip -Force -ErrorAction SilentlyContinue

$config = Join-Path $InstallDir 'config.cmd'
if (-not (Test-Path $config)) { throw 'config.cmd lipsește după extragere.' }

& $config `
  --unattended `
  --replace `
  --url $repoUrl `
  --token $RegistrationToken `
  --name $runnerName `
  --labels 'mipe-ro' `
  --work '_work' `
  --runasservice `
  --windowslogonaccount 'NT AUTHORITY\NETWORK SERVICE'
if ($LASTEXITCODE -ne 0) { throw "Configurarea runnerului a eșuat cu codul $LASTEXITCODE." }

Write-Step "Pornesc serviciul"
$svc = Get-Service 'actions.runner.*' -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "*$runnerName*" } | Select-Object -First 1
if (-not $svc) { $svc = Get-Service 'actions.runner.*' -ErrorAction SilentlyContinue | Select-Object -First 1 }
if (-not $svc) { throw 'Serviciul GitHub Actions Runner nu a fost găsit după configurare.' }
Set-Service $svc.Name -StartupType Automatic
if ($svc.Status -ne 'Running') { Start-Service $svc.Name }

Write-Step "Gata"
Write-Host "Runner: $runnerName" -ForegroundColor Green
Write-Host "Etichetă: mipe-ro" -ForegroundColor Green
Write-Host "Serviciu: $($svc.Name) — $((Get-Service $svc.Name).Status)" -ForegroundColor Green
Write-Host "`nPoți închide fereastra. De acum PARTENER.EU poate rula singur crawl-ul MIPE când calculatorul este pornit și conectat la internet." -ForegroundColor White
Write-Host "Dacă PC-ul este oprit, jobul așteaptă; la următoarea pornire runnerul revine automat." -ForegroundColor Gray
