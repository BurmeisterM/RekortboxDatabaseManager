$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Bitte zuerst Installieren.cmd ausführen.'
}
$appVersion = & $python -c "from rekordbox_manager import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0) { throw 'Die Anwendungsversion konnte nicht gelesen werden.' }
$outputExecutable = Join-Path $PSScriptRoot "dist\RekordboxDatabaseManager-$appVersion\RekordboxDatabaseManager.exe"
$runningApp = Get-Process -Name RekordboxDatabaseManager -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $outputExecutable }
if ($runningApp) { throw 'Die erstellte App bitte vor dem erneuten Build schließen, damit ihre Dateien nicht gesperrt sind.' }
& $python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Die Build-Abhängigkeiten konnten nicht installiert werden.' }
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Die Tests sind fehlgeschlagen.' }
& $python -m PyInstaller --noconfirm RekordboxManager.spec
if ($LASTEXITCODE -ne 0) { throw 'Der EXE-Build ist fehlgeschlagen.' }
Write-Host "Fertig: $outputExecutable. Den gesamten Ordner weitergeben."
