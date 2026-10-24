# Fail-closed Authenticode publication gate for *PUBLIC* NSIS setup binaries.
# Signing is not simulated: the Windows trust chain and expected owner
# certificate must both verify, otherwise nothing can be published.
param(
  [Parameter(Mandatory=$true)][string]$InstallerPath,
  [Parameter(Mandatory=$true)][string]$ExpectedThumbprint,
  [string]$ReceiptPath = "$env:RUNNER_TEMP\jarvis-release-signature-proof.json"
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$receipt = [ordered]@{
  schema = "jarvis-windows-authenticode-release-v1"
  status = "blocked"
  installer_sha256 = $null
  authenticated_signer_thumbprint = $null
  signature_status = "NotChecked"
  valid_certificate_chain = $false
  signer_matches_expected = $false
  physical_power_loss_certified = $false
  success = $false
}
try {
  if ($ExpectedThumbprint -cnotmatch '^[a-fA-F0-9]{40}$') {
    Throw "Trusted publisher thumbprint missing or invalid; deny public release"
  }
  $installer = (Resolve-Path -LiteralPath $InstallerPath -ErrorAction Stop).Path
  if (-not (Test-Path -LiteralPath $installer -PathType Leaf) -or
      [IO.Path]::GetExtension($installer) -ne ".exe") {
    Throw "Expected one existing NSIS .exe installer"
  }
  $receipt.installer_sha256 = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
  $signature = Get-AuthenticodeSignature -LiteralPath $installer
  $receipt.signature_status = $signature.Status.ToString()
  if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
      $null -eq $signature.SignerCertificate) {
    Throw "Unsigned, expired, untrusted or tampered installer cannot be published"
  }
  $receipt.valid_certificate_chain = $true
  $actual = $signature.SignerCertificate.Thumbprint.ToUpperInvariant().Replace(" ", "")
  $receipt.authenticated_signer_thumbprint = $actual
  $expected = $ExpectedThumbprint.ToUpperInvariant()
  $receipt.signer_matches_expected = ($actual -ceq $expected)
  if (-not $receipt.signer_matches_expected) {
    Throw "Authenticode publisher did not match the pinned owner signing certificate"
  }
  $receipt.status = "verified"
  $receipt.success = $true
} finally {
  # Evidence survives a rejected release without leaking signing credentials.
  $receipt | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $ReceiptPath -Encoding utf8
}
if (-not $receipt.success) { Throw "Signed Windows release is not certified" }
Write-Host "PASS: release setup Authenticode chain + pinned publisher; SHA256=$($receipt.installer_sha256)"
