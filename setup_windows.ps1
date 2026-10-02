$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$venvPython = Join-Path $projectRoot '.venv-liv\Scripts\python.exe'
$runtimeWorks = $false
if (Test-Path -LiteralPath $venvPython) {
    & $venvPython -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>$null
    $runtimeWorks = ($LASTEXITCODE -eq 0)
}
if (-not $runtimeWorks) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw 'Install Python 3.11 or newer with Add Python to PATH, then run setup again.' }
    & $pythonCommand.Source -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required.' }
    & $pythonCommand.Source -m venv (Join-Path $projectRoot '.venv-liv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
& $venvPython -m pip install -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. See the error above and retry setup.' }
& $venvPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw 'Browser installation failed. Check your internet connection and retry setup.' }

$windowlessPython = Join-Path $projectRoot '.venv-liv\Scripts\pythonw.exe'
$launcher = Join-Path $projectRoot 'launch.py'
$launchArguments = '"' + $launcher + '"'
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
New-Item -Path $runKey -Force | Out-Null
New-ItemProperty -Path $runKey -Name 'JARVIS_AI' -Value ('"' + $windowlessPython + '" ' + $launchArguments) -PropertyType String -Force | Out-Null

$desktopFolder = [Environment]::GetFolderPath('Desktop')
$wscriptShell = New-Object -ComObject WScript.Shell
$shortcut = $wscriptShell.CreateShortcut((Join-Path $desktopFolder 'JARVIS Assistant.lnk'))
$shortcut.TargetPath = $windowlessPython
$shortcut.Arguments = $launchArguments
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = Join-Path $projectRoot 'config\jarvis.ico'
$shortcut.Save()

Write-Host 'Setup complete. JARVIS will open after you sign in to Windows.'
Write-Host 'A desktop shortcut is ready. Disable auto-start in the app settings if needed.'
Start-Process -FilePath $windowlessPython -ArgumentList $launchArguments -WorkingDirectory $projectRoot -WindowStyle Hidden
