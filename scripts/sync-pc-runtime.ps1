$ErrorActionPreference = "Stop"

$androidRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$manifestPath = Join-Path $PSScriptRoot "pc-runtime-manifest.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
$destinationRoot = Join-Path $androidRoot "app\src\main\python"
$androidProjectRoot = (Resolve-Path (Join-Path $androidRoot "..\..")).Path
$forbidden = @('out', 'output', '__pycache__', '.env', 'llm.json', 'assets.db')

function Get-FullPath([string]$path) {
    return [System.IO.Path]::GetFullPath($path)
}

function Assert-InRoot([string]$path, [string]$root, [string]$label) {
    $fullPath = (Get-FullPath $path).TrimEnd('\')
    $fullRoot = (Get-FullPath $root).TrimEnd('\')
    if (-not ($fullPath.Equals($fullRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
            $fullPath.StartsWith($fullRoot + '\', [System.StringComparison]::OrdinalIgnoreCase))) {
        throw "$label '$fullPath' escapes allowed root '$fullRoot'"
    }
}

function Assert-RelativePath([string]$relativePath) {
    if ([string]::IsNullOrWhiteSpace($relativePath) -or [System.IO.Path]::IsPathRooted($relativePath)) {
        throw "Manifest path must be a non-empty relative path: '$relativePath'"
    }
    $segments = $relativePath -split '[\\/]'
    if ($segments -contains '..' -or $segments -contains '.') {
        throw "Manifest path contains traversal: '$relativePath'"
    }
    foreach ($segment in $segments) {
        if ($forbidden -contains $segment) {
            throw "Forbidden path segment '$segment' appears in '$relativePath'"
        }
    }
}

$sourceCandidates = @(
    (Join-Path $androidRoot $manifest.source),
    (Join-Path (Split-Path $androidRoot -Parent) $manifest.source),
    (Join-Path (Split-Path (Split-Path $androidRoot -Parent) -Parent) $manifest.source)
)
$sourceRoot = $null
foreach ($candidate in $sourceCandidates) {
    if (Test-Path -LiteralPath $candidate -PathType Container) {
        $sourceRoot = (Resolve-Path -LiteralPath $candidate).Path
        break
    }
}
if ($null -eq $sourceRoot) {
    throw "PC source root was not found for manifest source '$($manifest.source)'"
}

Assert-InRoot $androidRoot $androidProjectRoot "Android worktree"
New-Item -ItemType Directory -Force -Path $destinationRoot | Out-Null
Assert-InRoot $destinationRoot $androidProjectRoot "Destination root"

$entries = [System.Collections.Generic.List[object]]::new()
foreach ($entry in @($manifest.python)) {
    Assert-RelativePath ([string]$entry.path)
    $entries.Add([PSCustomObject]@{ RelativePath = ([string]$entry.path).Replace('/', '\'); SourcePath = ([string]$entry.path).Replace('/', '\'); ManifestEntry = $entry })
}
foreach ($directory in @($manifest.directories)) {
    Assert-RelativePath ([string]$directory.path)
    foreach ($entry in @($directory.files)) {
        Assert-RelativePath ([string]$entry.path)
        $relative = Join-Path ([string]$directory.path) ([string]$entry.path)
        Assert-RelativePath $relative
        $entries.Add([PSCustomObject]@{ RelativePath = $relative.Replace('/', '\'); SourcePath = $relative.Replace('/', '\'); ManifestEntry = $entry })
    }
}
foreach ($entry in @($manifest.static)) {
    Assert-RelativePath ([string]$entry.path)
    $relative = ([string]$entry.path).Replace('/', '\')
    $entries.Add([PSCustomObject]@{ RelativePath = $relative; SourcePath = $relative; ManifestEntry = $entry })
}

$sourceRecordName = 'PC' + ([char]0x8FD0) + ([char]0x884C) + ([char]0x65F6) + ([char]0x6765) + ([char]0x6E90) + '.json'
$previousRecordPath = Join-Path $destinationRoot $sourceRecordName
$previousPaths = @()
if (Test-Path -LiteralPath $previousRecordPath -PathType Leaf) {
    try {
        $previous = Get-Content -LiteralPath $previousRecordPath -Raw -Encoding utf8 | ConvertFrom-Json
        $previousPaths = @($previous.files | ForEach-Object { [string]$_.path } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    } catch {
        throw "Unable to read previous generated source record: $previousRecordPath"
    }
}
$currentPaths = @($entries | ForEach-Object { $_.RelativePath })
foreach ($stale in $previousPaths | Where-Object { $currentPaths -notcontains $_ }) {
    Assert-RelativePath $stale
    $stalePath = Join-Path $destinationRoot $stale
    Assert-InRoot $stalePath $destinationRoot "Stale generated file"
    if (Test-Path -LiteralPath $stalePath -PathType Leaf) {
        Remove-Item -LiteralPath $stalePath -Force
    }
}

$recordFiles = [System.Collections.Generic.List[object]]::new()
foreach ($item in $entries) {
    $sourcePath = Join-Path $sourceRoot $item.SourcePath
    $destinationPath = Join-Path $destinationRoot $item.RelativePath
    Assert-InRoot $destinationPath $destinationRoot "Destination"
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Manifest source file is missing: $($item.SourcePath)"
    }
    $hash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToUpperInvariant()
    $item.ManifestEntry.sha256 = $hash
    New-Item -ItemType Directory -Force -Path (Split-Path $destinationPath -Parent) | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
    $recordFiles.Add([PSCustomObject]@{ path = $item.RelativePath.Replace('\', '/'); sha256 = $hash })
}

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$manifestJson = $manifest | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText([string]$manifestPath, [string]$manifestJson, $utf8NoBom)
$sourceRecord = [PSCustomObject]@{
    source = [string]$manifest.source
    files = @($recordFiles)
}
$sourceRecordJson = $sourceRecord | ConvertTo-Json -Depth 5
$recordPath = [System.IO.Path]::Combine([string]$destinationRoot, $sourceRecordName)
Set-Content -LiteralPath $recordPath -Value $sourceRecordJson -Encoding utf8

Write-Output "PC runtime synchronized: $($entries.Count) files"
