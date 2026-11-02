# agentkernel demo package: verify, extract, check manifest, run the fast gate.
# No source code, no network, no admin rights, no service install, no firewall changes.
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -ZipPath "C:\path\agentkernel-2026-10-19-win-x64.zip"
# Options:
#   -Target "D:\ak-demo"   extraction dir (default %TEMP%\agentkernel-demo-<8 hex>; non-empty dir is refused)
#   -ExpectedZipSha256 ""  empty string = print the zip hash without comparing
#   -SkipGate              verify and extract only; do not run kcheck
# ASCII-only on purpose: Windows PowerShell 5.1 reads BOM-less .ps1 as ANSI,
# and non-ASCII text can break the parser before any check runs.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ZipPath,
    [string]$Target,
    [string]$ExpectedZipSha256 = "236517a21d50ab9d3969c46354e477a881e2a1c58a4362245a104b15540abeab",
    [switch]$SkipGate
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Stop-Here([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    exit 1
}
function Say-Ok([string]$Message) {
    Write-Host "[OK]   $Message" -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) {
    Stop-Here "zip not found: $ZipPath"
}
$zip = (Resolve-Path -LiteralPath $ZipPath).Path
$actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "zip sha256 = $actual"
if ($ExpectedZipSha256) {
    if ($actual -ne $ExpectedZipSha256.ToLowerInvariant()) {
        Stop-Here "zip hash mismatch; expected $ExpectedZipSha256"
    }
    Say-Ok "zip hash matches"
}

if (-not $Target) {
    $Target = Join-Path $env:TEMP ("agentkernel-demo-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
}
if (Test-Path -LiteralPath $Target) {
    $existing = @(Get-ChildItem -LiteralPath $Target -Force)
    if ($existing.Count -gt 0) {
        Stop-Here "target dir is not empty; refusing to overwrite: $Target (use another -Target or clear it yourself)"
    }
} else {
    New-Item -ItemType Directory -Path $Target | Out-Null
}
$Target = (Resolve-Path -LiteralPath $Target).Path

Expand-Archive -LiteralPath $zip -DestinationPath $Target -Force
Say-Ok "extracted to $Target"

$manifest = Join-Path $Target "MANIFEST.sha256"
$root = $Target
if (-not (Test-Path -LiteralPath $manifest)) {
    # The release zip has a single top-level "agentkernel/" folder.
    $candidate = Join-Path $Target "agentkernel"
    if (Test-Path -LiteralPath (Join-Path $candidate "MANIFEST.sha256")) {
        $root = $candidate
        $manifest = Join-Path $root "MANIFEST.sha256"
    }
}
if (-not (Test-Path -LiteralPath $manifest)) {
    Stop-Here "MANIFEST.sha256 is missing from the package"
}

$ok = 0
$mismatch = @()
$missing = @()
$unparsed = @()
foreach ($line in Get-Content -LiteralPath $manifest -Encoding UTF8) {
    if ($line -match '^\s*#' -or $line -match '^\s*$') { continue }
    if ($line -notmatch '^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$') {
        $unparsed += $line
        continue
    }
    $want = $Matches[1].ToLowerInvariant()
    $rel = $Matches[2]
    $full = Join-Path $root ($rel -replace '/', '\')
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        $missing += $rel
        continue
    }
    $got = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($got -eq $want) { $ok++ } else { $mismatch += $rel }
}

$total = $ok + $mismatch.Count + $missing.Count + $unparsed.Count
Write-Host "manifest entries checked: $total; OK $ok / mismatch $($mismatch.Count) / missing $($missing.Count) / unparsed $($unparsed.Count)"
if ($mismatch.Count -gt 0) {
    $mismatch | ForEach-Object { Write-Host "  mismatch: $_" -ForegroundColor Red }
    Stop-Here "manifest check failed"
}
if ($missing.Count -gt 0) {
    $missing | ForEach-Object { Write-Host "  missing: $_" -ForegroundColor Red }
    Stop-Here "manifest check failed"
}
if ($unparsed.Count -gt 0) {
    $unparsed | ForEach-Object { Write-Host "  unparsed: $_" -ForegroundColor Red }
    Stop-Here "manifest check failed"
}
Say-Ok "MANIFEST.sha256 verified ($ok/$total)"

if (-not $SkipGate) {
    $gate = Join-Path $root "bin\kcheck.exe"
    if (-not (Test-Path -LiteralPath $gate -PathType Leaf)) {
        Stop-Here "bin\kcheck.exe is missing from the package"
    }
    Write-Host ""
    Write-Host "== kcheck (fast gate; it carries its own criteria and does not read source from the cwd)"
    & $gate
    $rc = $LASTEXITCODE
    Write-Host ""
    Write-Host "kcheck exit code = $rc"
    if ($rc -ne 0) {
        Stop-Here "fast gate exited non-zero"
    }
    Say-Ok "fast gate exit code 0; it still contains 'cannot verify' lines, read them line by line"
}

Write-Host ""
Write-Host "Next:"
Write-Host "  cd `"$root`""
Write-Host "  .\bin\kaudit.exe -journal `"<path to demo-ledger.jsonl>`" -listen 127.0.0.1:8788"
Write-Host "Output dir: $root"
exit 0
