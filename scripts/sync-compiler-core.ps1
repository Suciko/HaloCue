$ErrorActionPreference = "Stop"

$androidRoot = Split-Path -Parent $PSScriptRoot
$repositoryRoot = Split-Path -Parent $androidRoot
$sourceRoot = Join-Path $repositoryRoot "01-完整程序\aa"
$destinationRoot = Join-Path $androidRoot "app\src\main\python"

$files = @(
    "script2aap.py",
    "stage.py",
    "camera.py",
    "performance_rules.py",
    "tables.py",
    "aapaths.py",
    "aa_install_discovery.py",
    "background_requests.py",
    "aa_registry.py",
    "aa_project_assets.py",
    "asset_validation.py",
    "asset_models.py",
    "document.py",
    "diagnostics.py",
    "cast.json",
    "aa_resources.json"
)

foreach ($file in $files) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot $file) -Destination (Join-Path $destinationRoot $file) -Force
}

# Chaquopy's stdout object isn't guaranteed to expose CPython's reconfigure method.
$compiler = Join-Path $destinationRoot "script2aap.py"
$content = Get-Content -LiteralPath $compiler -Raw -Encoding utf8
$content = $content.Replace(
    'sys.stdout.reconfigure(encoding="utf-8")',
    'if hasattr(sys.stdout, "reconfigure"):' + [Environment]::NewLine + '    sys.stdout.reconfigure(encoding="utf-8")'
)
[System.IO.File]::WriteAllText($compiler, $content, [System.Text.UTF8Encoding]::new($false))

Write-Host "Compiler core synchronized into $destinationRoot"
