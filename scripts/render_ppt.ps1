param([string]$InputPpt = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $InputPpt) {
    $InputPpt = (Get-ChildItem -LiteralPath (Join-Path $Root "artifacts\submission") -Filter "*.pptx" | Select-Object -First 1).FullName
}
$HadExisting = [bool](Get-Process -Name POWERPNT -ErrorAction SilentlyContinue)
$App = New-Object -ComObject PowerPoint.Application
$Presentation = $null
try {
    $Presentation = $App.Presentations.Open($InputPpt, -1, 0, 0)
    $Destination = Join-Path $Root "artifacts\submission\slides"
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $Presentation.Export($Destination, "PNG", 1600, 900)
    $Presentation.SaveAs((Join-Path $Root "artifacts\submission\SparkGuard-draft.pdf"), 32)
    Write-Host "Rendered $($Presentation.Slides.Count) slides."
} finally {
    if ($Presentation) { $Presentation.Close() }
    if (-not $HadExisting) { $App.Quit() }
}
