param(
    [string]$Repository = 'mihaicismaru-bit/civora',
    [string]$Branch = 'partener/local-research-agent-v1-20260903',
    [string]$InstallRoot = "$env:LOCALAPPDATA\PARTENER.EU\local-research-agent-repo",
    [string]$DailyAt = '07:15',
    [string]$TaskName = 'PARTENER.EU Local Research Agent'
)

$ErrorActionPreference = 'Stop'

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

Require-Command git
if (-not (Get-Command py -ErrorAction SilentlyContinue) -and -not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Python 3 is required. Install Python 3.11+ and re-run this installer.'
}

$Parent = Split-Path -Parent $InstallRoot
New-Item -ItemType Directory -Force -Path $Parent | Out-Null
if (-not (Test-Path (Join-Path $InstallRoot '.git'))) {
    git clone --branch $Branch --single-branch "https://github.com/$Repository.git" $InstallRoot
} else {
    git -C $InstallRoot fetch origin $Branch
    git -C $InstallRoot checkout $Branch
    git -C $InstallRoot pull --ff-only origin $Branch
}

$AgentDir = Join-Path $InstallRoot 'partener-eu\local-research-agent'
$Config = [ordered]@{
    schema = 'PARTENER_EU_LOCAL_RESEARCH_AGENT_CONFIG_V1'
    repository = $Repository
    code_branch = $Branch
    evidence_branch = 'partener-local-research-evidence'
    evidence_base_branch = 'main'
    data_root = "$env:LOCALAPPDATA\PARTENER.EU\research-agent"
    daily_at = $DailyAt
}
$Config | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $AgentDir 'agent.local.json') -Encoding utf8

$Venv = Join-Path $InstallRoot '.partener-research-venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $Python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m venv $Venv
    } else {
        python -m venv $Venv
    }
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $AgentDir 'requirements.txt')
& $Python -m playwright install chromium
$ReqHash = (Get-FileHash -Algorithm SHA256 (Join-Path $AgentDir 'requirements.txt')).Hash.ToLowerInvariant()
Set-Content -Path (Join-Path $Venv '.requirements.sha256') -Value $ReqHash -Encoding ascii

# Register a daily task in the current user's context. Microsoft documents /SC DAILY and /ST HH:mm.
$Runner = Join-Path $AgentDir 'run.ps1'
$TaskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Runner`""
schtasks.exe /Create /SC DAILY /MO 1 /ST $DailyAt /TN $TaskName /TR $TaskCommand /F /RL LIMITED | Out-Host

& $Python (Join-Path $AgentDir 'agent.py') doctor

Write-Host ''
Write-Host 'PARTENER.EU Local Research Agent installed.'
Write-Host "Repository clone: $InstallRoot"
Write-Host "Daily task: $TaskName at $DailyAt"
Write-Host 'Publishing is fail-closed until PARTENER_RESEARCH_GITHUB_TOKEN is configured in the Windows user environment.'
Write-Host 'The token should be a fine-grained GitHub token limited to this repository with Contents: Read and write.'
Write-Host "Manual run: powershell -ExecutionPolicy Bypass -File `"$Runner`""
