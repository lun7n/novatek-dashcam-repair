# Publish to GitHub (run after: gh auth login)
# https://github.com/login/device

$ErrorActionPreference = "Stop"
$gh = "C:\Program Files\GitHub CLI\gh.exe"
$git = "C:\Program Files\Git\cmd\git.exe"
$repo = "lun7n/novatek-dashcam-repair"

Set-Location $PSScriptRoot

& $gh auth status

if (-not (Test-Path ".git")) {
    & $git init
    & $git add -A
    & $git -c user.name="lun7n" -c user.email="lun7n@users.noreply.github.com" commit -m "Initial release: Novatek dashcam MP4 index repair"
}

& $gh repo create $repo `
    --public `
    --source=. `
    --remote=origin `
    --description "Fix corrupted MP4 index (stco) in Novatek dashcam recordings. For full-size files that stop playing early." `
    --push 2>$null

if ($LASTEXITCODE -ne 0) {
    & $git branch -M main
    & $git remote remove origin 2>$null
    & $git remote add origin "https://github.com/$repo.git"
    & $git push -u origin main
}

& $gh repo edit $repo `
    --add-topic novatek `
    --add-topic dashcam `
    --add-topic mp4 `
    --add-topic video-repair `
    --add-topic stco `
    --add-topic data-recovery `
    --add-topic python `
    --add-topic dashcam-repair

Write-Host ""
Write-Host "Published: https://github.com/$repo"
