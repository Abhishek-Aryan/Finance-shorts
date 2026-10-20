# PowerShell convenience runner for Finance Shorts Pro
param (
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ArgsList
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
$PythonExe = Join-Path $ScriptDir ".venv\Scripts\python.exe"
$MainPy = Join-Path $ScriptDir "main.py"

& $PythonExe $MainPy @ArgsList
