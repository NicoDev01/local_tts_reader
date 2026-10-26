$ErrorActionPreference = 'Stop'
$launcher = Join-Path $PSScriptRoot 'TTS Vorleser.exe'
if (-not (Test-Path -LiteralPath $launcher)) { throw 'Zuerst setup.ps1 ausführen.' }
$desktopPath = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $desktopPath 'TTS Vorleser.lnk'))
$shortcut.TargetPath = $launcher
$shortcut.Arguments = ''
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'TTS Vorleser im Infobereich – Strg + Alt + V'
$shortcut.IconLocation = 'shell32.dll,168'
$shortcut.Save()
