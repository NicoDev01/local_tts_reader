param([switch]$SkipDependencies)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
if (-not $SkipDependencies) {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'uv fehlt. Installiere uv und führe setup.ps1 erneut aus.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.venv\Scripts\python.exe'))) {
        uv venv --python 3.12 (Join-Path $projectRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Python-Umgebung konnte nicht erstellt werden.' }
    }
    uv pip sync --python (Join-Path $projectRoot '.venv\Scripts\python.exe') (Join-Path $projectRoot 'requirements.lock')
    if ($LASTEXITCODE -ne 0) { throw 'Abhängigkeiten konnten nicht installiert werden.' }
}
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$launcher = Join-Path $projectRoot 'TTS Vorleser.exe'
$icon = Join-Path $projectRoot 'assets\vorleser.ico'
& $compiler /nologo /target:winexe /optimize+ /reference:System.Windows.Forms.dll "/win32icon:$icon" "/out:$launcher" (Join-Path $projectRoot 'launcher.cs')
if ($LASTEXITCODE -ne 0) { throw 'Windows-Launcher konnte nicht erstellt werden.' }
& (Join-Path $projectRoot 'create_shortcut.ps1')
Write-Output 'Installation abgeschlossen. TTS Vorleser startet im Infobereich.'
