param(
    [switch]$NoPublish,
    [string[]]$SourceId = @()
)

$ErrorActionPreference = 'Stop'
$AgentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $AgentDir '..\..')).Path
$ConfigPath = Join-Path $AgentDir 'agent.local.json'
if (-not (Test-Path $ConfigPath)) {
    throw "Missing $ConfigPath. Run install.ps1 first."
}
$Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$Branch = [string]$Config.code_branch
if (-not $Branch) { throw 'agent.local.json: code_branch missing' }

# Self-update. Fail closed: if update fails, keep the installed LKG code and record the error,
# but do not reset/rebase/force-pull over local state.
try {
    git -C $RepoRoot fetch origin $Branch --quiet
    git -C $RepoRoot checkout $Branch --quiet
    git -C $RepoRoot pull --ff-only origin $Branch --quiet
} catch {
    Write-Warning "Self-update failed; continuing with installed LKG code: $($_.Exception.Message)"
}

$Venv = Join-Path $RepoRoot '.partener-research-venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $Python)) {
    py -3 -m venv $Venv
}

$Requirements = Join-Path $AgentDir 'requirements.txt'
$ReqHashFile = Join-Path $Venv '.requirements.sha256'
$ReqHash = (Get-FileHash -Algorithm SHA256 $Requirements).Hash.ToLowerInvariant()
$InstalledReqHash = if (Test-Path $ReqHashFile) { (Get-Content $ReqHashFile -Raw).Trim() } else { '' }
if ($ReqHash -ne $InstalledReqHash) {
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r $Requirements
    & $Python -m playwright install chromium
    Set-Content -Path $ReqHashFile -Value $ReqHash -Encoding ascii
}

$Args = @((Join-Path $AgentDir 'agent.py'), 'run')
if (-not $NoPublish) { $Args += '--publish' }
foreach ($sid in $SourceId) {
    $Args += '--source-id'
    $Args += $sid
}

& $Python @Args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Mirror the metadata manifest as plain JSON so connected GitHub readers can inspect
# the latest run without opening the binary ZIP evidence bundle.
if (-not $NoPublish) {
    & $Python (Join-Path $AgentDir 'publish_readable_manifest.py')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
