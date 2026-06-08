param(
    [string]$RepairedDir = "",
    [int]$TimeoutSec = 1800
)

$ErrorActionPreference = "Stop"

if (-not $RepairedDir) {
    $RepairedDir = Join-Path $PSScriptRoot "_repaired"
}

if (-not (Test-Path -LiteralPath $RepairedDir)) {
    throw "Repaired folder not found: $RepairedDir"
}

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    throw "ffmpeg not found on PATH. Install ffmpeg or add it to PATH."
}

$files = Get-ChildItem -LiteralPath $RepairedDir -File | Where-Object {
    $_.Extension -match '^\.(mp4|mov|m4v|3gp)$'
} | Sort-Object Name

if (-not $files) {
    throw "No video files in $RepairedDir"
}

$logPath = Join-Path $RepairedDir "verify_results.txt"
"Verify run $(Get-Date -Format o)" | Set-Content -Path $logPath -Encoding UTF8

$pass = 0
$fail = 0

foreach ($f in $files) {
    Write-Host "Checking $($f.Name) ..."
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ffmpeg.Source
    $psi.Arguments = "-nostdin -hide_banner -v error -i `"$($f.FullName)`" -map 0:v:0 -f null -"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $proc = [System.Diagnostics.Process]::Start($psi)
    if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
        $proc.Kill()
        $line = "$($f.Name)`tTIMEOUT"
        $fail++
    }
    elseif ($proc.ExitCode -eq 0) {
        $line = "$($f.Name)`tPASS"
        $pass++
    }
    else {
        $err = $proc.StandardError.ReadToEnd().Trim() -replace '\s+', ' '
        if ($err.Length -gt 120) { $err = $err.Substring(0, 120) + "..." }
        $line = "$($f.Name)`tFAIL`t$err"
        $fail++
    }
    Add-Content -Path $logPath -Value $line -Encoding UTF8
}

Write-Host ""
Write-Host "PASS: $pass  FAIL: $fail"
Write-Host "Log: $logPath"
