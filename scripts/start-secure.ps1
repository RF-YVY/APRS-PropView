# Launch the project's isolated runtime without changing shared Python packages.
$PropViewRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$PropViewPython = Join-Path $PropViewRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $PropViewPython)) {
    throw 'Create .venv and install requirements.txt before launching APRS PropView.'
}
Push-Location -LiteralPath $PropViewRoot
try {
    & $PropViewPython (Join-Path $PropViewRoot 'main.py') @args
    if ($LASTEXITCODE -ne 0) { throw "APRS PropView exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
