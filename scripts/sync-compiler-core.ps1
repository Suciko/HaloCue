$ErrorActionPreference = "Stop"

$worktreeRoot = Split-Path -Parent $PSScriptRoot
$commonGitDir = (& git -C $worktreeRoot rev-parse --path-format=absolute --git-common-dir).Trim()
if (-not $commonGitDir) {
    throw "无法定位 Git 公共目录"
}

# Source files live beside the primary Android worktree, while this script may
# run from any linked worktree.
$androidRoot = Split-Path -Parent $commonGitDir
$repositoryRoot = Split-Path -Parent $androidRoot
$sourceRoot = Get-ChildItem -LiteralPath $repositoryRoot -Directory |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "aa\script2aap.py") } |
    ForEach-Object { Join-Path $_.FullName "aa" } |
    Select-Object -First 1
if (-not $sourceRoot) {
    throw "找不到包含 aa\\script2aap.py 的电脑端源码目录"
}
$destinationRoot = Join-Path $worktreeRoot "app\src\main\python"

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
    "spine_semantic_faces.py",
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
