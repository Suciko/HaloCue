param(
    [string]$SourceRoot = "",
    [string]$DestinationRoot = ""
)

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
if (-not $SourceRoot) {
    $SourceRoot = Join-Path $repositoryRoot "01-完整程序\aa"
}
if (-not $DestinationRoot) {
    $DestinationRoot = Join-Path $androidRoot "app\src\main\python"
}

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
$compiler = Join-Path $DestinationRoot "script2aap.py"
$content = Get-Content -LiteralPath $compiler -Raw -Encoding utf8
$content = $content -replace "`r`n?", "`n"
$content = $content.Replace(
    'sys.stdout.reconfigure(encoding="utf-8")',
    'if hasattr(sys.stdout, "reconfigure"):' + "`n" + '    sys.stdout.reconfigure(encoding="utf-8")'
)
$aliasHelper = @'


def apply_identifier_aliases(scenes, aliases):
    """Translate canonical PC identifiers only at the serialized AAP boundary."""
    aliases = aliases or {}
    if not aliases:
        return scenes
    for _title, scripts in scenes:
        for script in scripts:
            for character in script.get("characters", {}).get("$values", []):
                identifier = str(character.get("name") or "")
                if identifier in aliases:
                    character["name"] = str(aliases[identifier])
    return scenes


def identifier_aliases_for_cast(index, cast_config):
    """Select package aliases only when the chosen portrait variant proves them."""
    rows_by_identifier = {}
    for row in index.get("characters") or []:
        identifier = str(row.get("identifier") or "")
        if identifier:
            rows_by_identifier.setdefault(identifier, []).append(row)
    entries = cast_config.get("cast", cast_config) if isinstance(cast_config, dict) else {}
    selected = {}
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        identifier = str(entry.get("id") or "")
        if not identifier:
            continue
        rows = rows_by_identifier.get(identifier, [])
        outfit_key = str(entry.get("outfit_key") or "")
        if outfit_key:
            rows = [row for row in rows if str(row.get("outfit_key") or "") == outfit_key]
        targets = {str(row.get("android_package_identifier") or identifier) for row in rows}
        if len(targets) == 1:
            target = next(iter(targets))
            if target and target != identifier:
                selected[identifier] = target
    return selected
'@
$restoreMarker = "`ndef restore_registered_cast_assets(cast, aa_data):"
if (-not $content.Contains($restoreMarker)) {
    throw "Unable to locate restore_registered_cast_assets in synchronized script2aap.py"
}
$content = $content.Replace(
    $restoreMarker,
    $aliasHelper + "`n`ndef restore_registered_cast_assets(cast, aa_data):"
)
$buildMarker = '        scenes = build(events, cfg, cast, idx, project)' + "`n" + '        flat ='
if (-not $content.Contains($buildMarker)) {
    throw "Unable to locate the serialized AAP build boundary in synchronized script2aap.py"
}
$content = $content.Replace(
    $buildMarker,
    '        scenes = build(events, cfg, cast, idx, project)' + "`n" + '        apply_identifier_aliases(scenes, identifier_aliases_for_cast(idx, cfg))' + "`n" + '        flat ='
)
[System.IO.File]::WriteAllText($compiler, $content, [System.Text.UTF8Encoding]::new($false))

Write-Host "Compiler core synchronized into $DestinationRoot"
