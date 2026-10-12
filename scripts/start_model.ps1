param(
    [string]$PythonExe = "python",
    [string]$OllamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
    [int]$Port = 11435,
    [ValidateSet("1.7b", "4b")][string]$Size = "1.7b",
    [switch]$Check
)
$ErrorActionPreference = "Stop"
$Arguments = @((Join-Path $PSScriptRoot "start_model.py"), "--size", $Size, "--port", $Port, "--ollama-exe", $OllamaExe)
if ($Check) { $Arguments += "--check" }
& $PythonExe @Arguments
exit $LASTEXITCODE
