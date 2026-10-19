param()

$ErrorActionPreference = 'Stop'
$Secure = Read-Host 'Paste fine-grained GitHub token (Contents: Read and write, repo mihaicismaru-bit/civora only)' -AsSecureString
$Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
try {
    $Plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
    if ([string]::IsNullOrWhiteSpace($Plain)) { throw 'Empty token.' }
    [Environment]::SetEnvironmentVariable('PARTENER_RESEARCH_GITHUB_TOKEN', $Plain, 'User')
    $env:PARTENER_RESEARCH_GITHUB_TOKEN = $Plain
    Write-Host 'PARTENER_RESEARCH_GITHUB_TOKEN configured for the current Windows user.'
} finally {
    if ($Bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr) }
    $Plain = $null
}
