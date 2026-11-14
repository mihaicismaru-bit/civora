param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\PARTENER.EU\local-research-agent-repo",
    [string]$DataRoot = "$env:LOCALAPPDATA\PARTENER.EU\research-agent",
    [string]$TaskName = 'PARTENER.EU Local Research Agent',
    [switch]$RemoveData,
    [switch]$RemoveRepositoryClone
)

$ErrorActionPreference = 'Stop'
schtasks.exe /Delete /TN $TaskName /F 2>$null | Out-Null
Write-Host "Removed scheduled task: $TaskName"
if ($RemoveData -and (Test-Path $DataRoot)) {
    Remove-Item -Recurse -Force $DataRoot
    Write-Host "Removed data: $DataRoot"
}
if ($RemoveRepositoryClone -and (Test-Path $InstallRoot)) {
    Remove-Item -Recurse -Force $InstallRoot
    Write-Host "Removed repository clone: $InstallRoot"
}
