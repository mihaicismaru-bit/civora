@echo off
setlocal
title PARTENER.EU - Instaleaza colector MIPE Romania
set SCRIPT=%TEMP%\Setup-MIPE-Romania-Runner.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Headers @{'User-Agent'='PARTENER.EU-MIPE-Setup'} -Uri 'https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/partener-eu/local-runner/Setup-MIPE-Romania-Runner.ps1' -OutFile '%SCRIPT%'"
if errorlevel 1 (
  echo Nu am putut descarca installerul.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
if errorlevel 1 (
  echo.
  echo Configurarea nu s-a terminat corect. Trimite-mi mesajul de eroare afisat mai sus.
  pause
  exit /b 1
)
echo.
echo Gata. Poti inchide aceasta fereastra.
pause
