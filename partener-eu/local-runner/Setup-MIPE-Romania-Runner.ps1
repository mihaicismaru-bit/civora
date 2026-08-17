param(
  [string]$RegistrationToken = "",
  [string]$Repository = "mihaicismaru-bit/civora",
  [string]$InstallDir = "C:\actions-runner-partener-mipe"
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$Text) {
  Write-Host "`n=== $Text ===" -ForegroundColor Cyan
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

function Install-RunnerPackage {
  Write-Step "Descarc ultima versiune GitHub Actions Runner"
  $release = Invoke-RestMethod -Headers @{ 'User-Agent'='PARTENER.EU-MIPE-Setup' } -Uri 'https://api.github.com/repos/actions/runner/releases/latest'
  $asset = $release.assets | Where-Object { $_.name -match '^actions-runner-win-x64-.*\.zip$' } | Select-Object -First 1
  if (-not $asset) { throw 'Nu am găsit pachetul Windows x64 al GitHub Actions Runner.' }
  $zip = Join-Path $env:TEMP $asset.name
  Invoke-WebRequest -Headers @{ 'User-Agent'='PARTENER.EU-MIPE-Setup' } -Uri $asset.browser_download_url -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $InstallDir -Force
  Remove-Item $zip -Force -ErrorAction SilentlyContinue
}

function Ensure-AutostartTask([string]$RunnerName) {
  Write-Step "Configurez pornirea automată"
  $taskName = 'PARTENER.EU MIPE Runner'
  $starter = Join-Path $InstallDir 'Start-MIPE-Runner.ps1'
  @'
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
while ($true) {
  try {
    & (Join-Path $PSScriptRoot 'run.cmd')
  } catch {
    Write-Host $_
  }
  Start-Sleep -Seconds 20
}
'@ | Set-Content -Path $starter -Encoding UTF8

  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$starter`""
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650)
  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
  Start-ScheduledTask -TaskName $taskName
  Write-Host "OK — task-ul '$taskName' pornește runnerul automat la logon și îl repornește dacă se oprește." -ForegroundColor Green
}

Ensure-Admin

Write-Host "PARTENER.EU — configurare colector MIPE România" -ForegroundColor Green
Write-Host "Operațiunea se face o singură dată. După aceea runnerul pornește automat când te autentifici în Windows." -ForegroundColor Gray

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

if (-not (Test-Path (Join-Path $InstallDir 'config.cmd'))) {
  Install-RunnerPackage
}

$config = Join-Path $InstallDir 'config.cmd'
if (-not (Test-Path $config)) { throw 'config.cmd lipsește după instalare.' }

if (-not (Test-Path (Join-Path $InstallDir '.runner'))) {
  Write-Step "Înregistrez runnerul pentru repository"
  & $config `
    --unattended `
    --replace `
    --url $repoUrl `
    --token $RegistrationToken `
    --name $runnerName `
    --labels 'mipe-ro' `
    --work '_work'
  if ($LASTEXITCODE -ne 0) { throw "Configurarea runnerului a eșuat cu codul $LASTEXITCODE." }
} else {
  Write-Host "Runnerul este deja înregistrat; păstrez configurația existentă." -ForegroundColor Yellow
}

Ensure-AutostartTask -RunnerName $runnerName

Write-Step "Gata"
Write-Host "Runner: $runnerName" -ForegroundColor Green
Write-Host "Etichetă: mipe-ro" -ForegroundColor Green
Write-Host "Pornire: automată la autentificarea în Windows" -ForegroundColor Green
Write-Host "`nPoți închide fereastra. De acum PARTENER.EU poate cere singur crawl-ul MIPE la fiecare 3 ore." -ForegroundColor White
Write-Host "PC-ul trebuie să fie pornit, conectat la internet și să existe o sesiune Windows autentificată." -ForegroundColor Gray
