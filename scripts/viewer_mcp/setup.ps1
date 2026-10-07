$ErrorActionPreference = 'Stop'
$mcpRoot = $PSScriptRoot
$viewerRoot = (Resolve-Path (Join-Path $mcpRoot '../..')).Path
$mcpPython = Join-Path $mcpRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $mcpPython)) {
    py -3.12 -m venv (Join-Path $mcpRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python 3.12 environment' }
}
& $mcpPython -m pip install -r (Join-Path $mcpRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install MCP dependencies' }
& $mcpPython (Join-Path $mcpRoot 'configure.py')
if ($LASTEXITCODE -ne 0) { throw 'Could not configure project MCP' }
Write-Output 'Prism MCP is configured for this checkout. Reconnect MCP servers or open a new Codex session to load it.'
