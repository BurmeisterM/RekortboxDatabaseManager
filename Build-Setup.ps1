[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [string]$IsccPath
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Bitte zuerst Installieren.cmd ausführen.'
}

$appVersion = & $python -c "from rekordbox_manager import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0 -or $appVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw 'Die Anwendungsversion konnte nicht gelesen werden.'
}

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot 'Build.ps1')
}
$payloadDir = Join-Path $PSScriptRoot "dist\RekordboxDatabaseManager-$appVersion"
foreach ($relativePath in @('RekordboxDatabaseManager.exe', '_internal\README.md', '_internal\THIRD_PARTY_NOTICES.md', '_internal\PySide6\Qt6Core.dll')) {
    if (-not (Test-Path -LiteralPath (Join-Path $payloadDir $relativePath))) {
        throw "Der Anwendungs-Build ist unvollständig ($relativePath). Bitte Build.ps1 ausführen."
    }
}

if ($IsccPath) {
    $compiler = (Resolve-Path -LiteralPath $IsccPath).Path
} else {
    $compiler = $null
    $candidates = @(
        (Join-Path $PSScriptRoot '.artifacts\tools\inno-setup\ISCC.exe'),
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    $installedCompiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($installedCompiler) { $candidates += $installedCompiler.Source }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            $compiler = $candidate
            break
        }
    }
    if (-not $compiler) {
        throw 'Inno Setup 6 (ab 6.3) fehlt. Von https://jrsoftware.org/isdl.php installieren oder -IsccPath <Pfad zu ISCC.exe> übergeben.'
    }
}

& $compiler "/DAppVersion=$appVersion" "/DPayloadDir=$payloadDir" (Join-Path $PSScriptRoot 'installer\RekordboxDatabaseManager.iss')
if ($LASTEXITCODE -ne 0) { throw 'Der Setup-Build ist fehlgeschlagen.' }

$setupPath = Join-Path $PSScriptRoot "dist\Setup\RekordboxDatabaseManager-$appVersion-Setup-x64.exe"
if (-not (Test-Path -LiteralPath $setupPath)) { throw 'Die erwartete Setup-Datei wurde nicht erstellt.' }
$hash = (Get-FileHash -LiteralPath $setupPath -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $([System.IO.Path]::GetFileName($setupPath))" | Set-Content -LiteralPath "$setupPath.sha256" -Encoding ASCII
Write-Host "Fertig: $setupPath"
Write-Host 'Diese einzelne Setup-Datei enthält das Programm und alle Laufzeitabhängigkeiten.'
