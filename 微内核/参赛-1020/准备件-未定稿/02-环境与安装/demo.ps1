# agentkernel 3-minute demo driver (ASCII-only on purpose).
# It starts the read-only audit service, checks two endpoints, proves the write
# path is closed, then proves a tampered ledger is refused at load time.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\demo.ps1 `
#     -PackageDir "C:\...\agentkernel" -Ledger "C:\...\demo-ledger.jsonl"
#
# Exit code 0 = every expected reading matched; 1 = at least one mismatch.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PackageDir,
    [Parameter(Mandatory = $true)][string]$Ledger,
    [int]$Port = 8788
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$kaudit = Join-Path $PackageDir "bin\kaudit.exe"
if (-not (Test-Path -LiteralPath $kaudit -PathType Leaf)) { Write-Host "[FAIL] missing $kaudit"; exit 1 }
if (-not (Test-Path -LiteralPath $Ledger -PathType Leaf)) { Write-Host "[FAIL] missing $Ledger"; exit 1 }

$fail = 0
function Check([string]$Name, [bool]$Ok, [string]$Detail) {
    if ($Ok) {
        Write-Host "[PASS] $Name -- $Detail" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $Name -- $Detail" -ForegroundColor Red
        $script:fail++
    }
}

function Wait-Port([int]$P, [int]$TimeoutMs = 8000) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $TimeoutMs) {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $client.Connect("127.0.0.1", $P)
            if ($client.Connected) { return $true }
        } catch {
        } finally {
            $client.Close()
        }
        Start-Sleep -Milliseconds 100
    }
    return $false
}

$token = [Guid]::NewGuid().ToString("N")
$env:KAUDIT_TOKEN = $token
$auth = "Authorization: Bearer $token"
$base = "http://127.0.0.1:$Port"
$outLog = Join-Path $env:TEMP ("kaudit-demo-" + $token + ".out.txt")
$errLog = Join-Path $env:TEMP ("kaudit-demo-" + $token + ".err.txt")

Write-Host ""
Write-Host "== 1/4 start the read-only audit service on $base"
$proc = Start-Process -FilePath $kaudit `
    -ArgumentList @('-journal', ('"' + (Resolve-Path -LiteralPath $Ledger).Path + '"'), '-listen', "127.0.0.1:$Port") `
    -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
try {
    $up = Wait-Port -P $Port
    Check "service listening" $up "pid=$($proc.Id)"
    if (-not $up) {
        Write-Host "--- server stderr ---"
        if (Test-Path -LiteralPath $errLog) { Get-Content -LiteralPath $errLog }
        exit 1
    }

    Write-Host ""
    Write-Host "== 2/4 GET /v1/verify (chain + preimage)"
    $verifyRaw = & curl.exe -s -H $auth "$base/v1/verify"
    Write-Host $verifyRaw
    $verify = $verifyRaw | ConvertFrom-Json
    Check "verify.state" ($verify.state -eq "green") "state=$($verify.state)"
    Check "verify.checked" ($verify.checked -eq 100 -and $verify.entries -eq 100) "checked=$($verify.checked) entries=$($verify.entries)"

    Write-Host ""
    Write-Host "== 3/4 GET /v1/read_back + POST /v1/read_back"
    $readbackRaw = & curl.exe -s -H $auth "$base/v1/read_back?session=mount-check&call=1&side=input"
    $readback = $readbackRaw | ConvertFrom-Json
    $measured = @($readback.cells | Where-Object { $_.basis -eq "measured" }).Count
    $estimated = @($readback.cells | Where-Object { $_.basis -eq "estimated" }).Count
    Check "read_back.cells" ($readback.cells.Count -eq 20) "cells=$($readback.cells.Count) measured=$measured estimated=$estimated"
    Check "read_back.absent" (@($readback.absent).Count -eq 0) "absent=$(@($readback.absent).Count)"

    $postCode = & curl.exe -s -o NUL -w "%{http_code}" -H $auth -X POST "$base/v1/read_back"
    $postBody = & curl.exe -s -H $auth -X POST "$base/v1/read_back"
    Check "POST is refused" ($postCode -eq "405") "HTTP $postCode"
    Write-Host "  body: $postBody"
} finally {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
}

Write-Host ""
Write-Host "== 4/4 a tampered ledger must not load"
$badLedger = Join-Path $env:TEMP ("demo-ledger-tampered-" + $token + ".jsonl")
Copy-Item -LiteralPath $Ledger -Destination $badLedger -Force
$lines = [System.IO.File]::ReadAllLines($badLedger, [System.Text.Encoding]::UTF8)
$lines[49] = $lines[49] -replace '"claim":"[^"]*"', '"claim":"tampered"'
[System.IO.File]::WriteAllLines($badLedger, $lines, (New-Object System.Text.UTF8Encoding($false)))
$oldEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$tamperOut = & $kaudit -journal $badLedger -listen "127.0.0.1:$($Port + 2)" 2>&1
$tamperRc = $LASTEXITCODE
$ErrorActionPreference = $oldEap
$tamperText = ($tamperOut | Out-String).Trim()
Write-Host $tamperText
Check "tampered ledger refused" ($tamperRc -ne 0) "rc=$tamperRc"
Check "refusal names record 50" ($tamperText -match "50") "looked for '50' in refusal text"
Remove-Item -LiteralPath $badLedger -Force -ErrorAction SilentlyContinue

Write-Host ""
if ($fail -eq 0) {
    Write-Host "RESULT: all expected readings matched." -ForegroundColor Green
    exit 0
} else {
    Write-Host "RESULT: $fail check(s) failed." -ForegroundColor Red
    exit 1
}
