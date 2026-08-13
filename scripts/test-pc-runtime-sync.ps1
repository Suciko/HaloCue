$ErrorActionPreference = "Stop"

$androidRoot = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $PSScriptRoot "pc-runtime-manifest.json"
$sourceRecordName = 'PC' + ([char]0x8FD0) + ([char]0x884C) + ([char]0x65F6) + ([char]0x6765) + ([char]0x6E90) + '.json'
$sourceRecordPath = Join-Path (Join-Path $androidRoot "app\src\main\python") $sourceRecordName

if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "Missing PC runtime manifest: $manifestPath"
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
foreach ($property in @("python", "directories", "static")) {
    if ($null -eq $manifest.$property) {
        throw "Manifest is missing the '$property' array"
    }
}

$required = @(
    'app/src/main/python/webui.py',
    'app/src/main/python/ui.html',
    'app/src/main/python/js/api.js',
    'app/src/main/python/js/app.js',
    'app/src/main/python/css/app.css',
    'app/src/main/python/annotate.py',
    'app/src/main/python/draft_store.py',
    'app/src/main/python/model_profiles.py',
    'app/src/main/python/asset_catalog.py',
    'app/src/main/python/spine_semantic_faces.py'
)
foreach ($relativePath in $required) {
    $path = Join-Path $androidRoot ($relativePath -replace '/', '\')
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required synchronized file is missing: $relativePath"
    }
}

$forbidden = @('out', 'output', '__pycache__', '.env', 'llm.json', 'assets.db')
$manifestPaths = [System.Collections.Generic.List[object]]::new()
foreach ($entry in @($manifest.python) + @($manifest.static) + @($manifest.overrides)) {
    $manifestPaths.Add($entry)
}
foreach ($directory in @($manifest.directories)) {
    foreach ($entry in @($directory.files)) {
        $manifestPaths.Add([PSCustomObject]@{
            path = (Join-Path ([string]$directory.path) ([string]$entry.path))
            sha256 = [string]$entry.sha256
        })
    }
}
foreach ($entry in $manifestPaths) {
    $relativePath = if ($entry -is [string]) { $entry } else { $entry.path }
    if ([string]::IsNullOrWhiteSpace($relativePath)) {
        throw "Manifest contains an empty path"
    }
    $segments = $relativePath -split '[\\/]'
    foreach ($segment in $segments) {
        if ($forbidden -contains $segment) {
            throw "Forbidden path segment '$segment' appears in manifest path '$relativePath'"
        }
    }
    if ($entry -isnot [string]) {
        $hash = [string]$entry.sha256
        if ($hash -notmatch '^[0-9A-F]{64}$') {
            throw "Manifest entry '$relativePath' must include an uppercase SHA-256 value"
        }
    }
}

foreach ($desktopOnly in @('install_manager.py', 'spine_face_analysis.py', 'spine_face_renderer.py')) {
    if (@($manifest.python | ForEach-Object { [string]$_.path }) -contains $desktopOnly) {
        throw "Desktop-only module must be supplied by an Android override: $desktopOnly"
    }
    if (@($manifest.overrides | ForEach-Object { [string]$_.path }) -notcontains $desktopOnly) {
        throw "Missing Android runtime override: $desktopOnly"
    }
}

if (-not (Test-Path -LiteralPath $sourceRecordPath -PathType Leaf)) {
    throw "Missing generated source record: $sourceRecordPath"
}
$sourceRecord = Get-Content -LiteralPath $sourceRecordPath -Raw -Encoding utf8 | ConvertFrom-Json
if ([string]$sourceRecord.source -ne [string]$manifest.source) {
    throw "Source record does not match the manifest source"
}
foreach ($entry in @($sourceRecord.files)) {
    if ([string]$entry.sha256 -notmatch '^[0-9A-F]{64}$') {
        throw "Source record entry '$($entry.path)' must include an uppercase SHA-256 value"
    }
}

Write-Output "PC runtime sync contract passed"
