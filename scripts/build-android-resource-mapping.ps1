param(
    [Parameter(Mandatory = $true)]
    [string]$PackageZip,
    [Parameter(Mandatory = $true)]
    [string]$Password,
    [string]$PcIndex = "app/src/main/python/aa_resources.json",
    [string]$Output = "app/src/main/python/android_resource_mapping.json"
)

$ErrorActionPreference = "Stop"

$packagePath = (Resolve-Path -LiteralPath $PackageZip).Path
$indexPath = (Resolve-Path -LiteralPath $PcIndex).Path
$outputPath = [IO.Path]::GetFullPath((Join-Path (Get-Location) $Output))
$temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$temporaryRoot = Join-Path $temporaryBase ("halocue-resource-map-" + [guid]::NewGuid().ToString("N"))
if (-not $temporaryRoot.StartsWith($temporaryBase, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Temporary extraction path escaped the system temporary directory"
}

$faceAliases = @{
    "embarassed" = "embarrassed"; "embrassed" = "embarrassed"
    "embarrased" = "embarrassed"; "emvarassed" = "embarrassed"
    "embarrass" = "embarrassed"; "nomal" = "normal"
    "defualt" = "default"; "deuflat" = "default"
    "depressde" = "depressed"; "deparaeesd" = "depressed"
    "repond" = "respond"; "sarcatic" = "sarcastic"
    "yarn" = "yawn"; "serioous" = "serious"
    "inocent" = "innocent"; "eyeclosed" = "eyeclose"
    "eye_close" = "eyeclose"; "thingking" = "thinking"
}

function Get-OutfitKey($row) {
    $path = [string]$row.SpinePortraitPath
    if (-not $path) { return "" }
    return [IO.Path]::GetFileName($path.Replace("\", "/"))
}

function Read-Faces([string]$atlasPath) {
    if (-not (Test-Path -LiteralPath $atlasPath -PathType Leaf)) { return @() }
    $faces = [ordered]@{}
    foreach ($line in [IO.File]::ReadAllLines($atlasPath, [Text.Encoding]::UTF8)) {
        if ($line -match '^(\d{2})_(\S+?)\s*$') {
            $raw = $Matches[2]
            $label = ($raw -replace '_\d+$|_0\d$', '').ToLowerInvariant()
            if ($faceAliases.ContainsKey($label)) { $label = $faceAliases[$label] }
            if (-not $faces.Contains($Matches[1])) {
                $faces[$Matches[1]] = [ordered]@{
                    id = $Matches[1]; raw = $raw; label = $label
                }
            }
        } elseif ($line -match '^(\d{2})\s*$' -and -not $faces.Contains($Matches[1])) {
            $faces[$Matches[1]] = [ordered]@{
                id = $Matches[1]; raw = $Matches[1]; label = ""
            }
        }
    }
    return @($faces.Values | Sort-Object { [int]$_.id })
}

New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
try {
    & bsdtar -xf $packagePath --passphrase $Password -C $temporaryRoot `
        '*/manifest.json' '*/characters/*/*.atlas'
    if ($LASTEXITCODE -ne 0) { throw "Unable to extract resource mapping metadata" }

    $manifestPath = Get-ChildItem -LiteralPath $temporaryRoot -Recurse -Filter manifest.json -File |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $manifestPath) { throw "Resource package manifest.json is missing" }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $packageRoot = Split-Path -Parent $manifestPath
    $pc = Get-Content -LiteralPath $indexPath -Raw -Encoding UTF8 | ConvertFrom-Json

    $pcByOutfit = @{}
    foreach ($row in $pc.characters) {
        $outfit = [string]$row.outfit_key
        if ($outfit -and -not $pcByOutfit.ContainsKey($outfit)) {
            $pcByOutfit[$outfit] = $row
        }
    }

    $aliases = [ordered]@{}
    $characters = @()
    $skipped = 0
    $manifestGroups = $manifest.CharacterOverrides | Group-Object { Get-OutfitKey $_ }
    foreach ($group in $manifestGroups) {
        $outfit = [string]$group.Name
        $pcRow = if ($outfit -and $pcByOutfit.ContainsKey($outfit)) {
            $pcByOutfit[$outfit]
        } else { $null }
        $row = if ($pcRow) {
            @($group.Group | Where-Object {
                [string]$_.Identifier -ceq [string]$pcRow.identifier
            } | Select-Object -First 1)[0]
        } else { $null }
        if ($null -eq $row) { $row = @($group.Group)[0] }
        $outfit = Get-OutfitKey $row
        $relative = [string]$row.SpinePortraitPath
        $atlasPath = if ($relative) {
            Join-Path $packageRoot ($relative.Replace("/", [IO.Path]::DirectorySeparatorChar) + ".atlas")
        } else { "" }
        if (-not $outfit -or -not (Test-Path -LiteralPath $atlasPath -PathType Leaf)) {
            $skipped += 1
            continue
        }
        $packageIdentifier = [string]$row.Identifier
        $pcIdentifier = if ($pcRow) { [string]$pcRow.identifier } else { $packageIdentifier }
        if ($pcIdentifier -cne $packageIdentifier) {
            if ($aliases.Contains($pcIdentifier) -and $aliases[$pcIdentifier] -cne $packageIdentifier) {
                throw "Conflicting package identifiers for PC identifier: $pcIdentifier"
            }
            $aliases[$pcIdentifier] = $packageIdentifier
        }
        $characters += [ordered]@{
            identifier = $pcIdentifier
            package_identifier = $packageIdentifier
            name = [string]$row.Name
            club = [string]$row.Nickname
            spine = $relative
            outfit_key = $outfit
            faces = @(Read-Faces $atlasPath)
            new_to_pc_index = ($null -eq $pcRow)
        }
    }

    $mapping = [ordered]@{
        schema_version = 1
        source_package = [IO.Path]::GetFileName($packagePath)
        pc_index_sha256 = (Get-FileHash -LiteralPath $indexPath -Algorithm SHA256).Hash.ToLowerInvariant()
        summary = [ordered]@{
            package_characters = @($manifest.CharacterOverrides).Count
            mapped_characters = $characters.Count
            identifier_aliases = $aliases.Count
            new_characters = @($characters | Where-Object new_to_pc_index).Count
            skipped_characters = $skipped
        }
        identifier_aliases = $aliases
        characters = $characters
    }
    $json = $mapping | ConvertTo-Json -Depth 12 -Compress
    $outputDirectory = Split-Path -Parent $outputPath
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    [IO.File]::WriteAllText($outputPath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    Write-Output ("Wrote {0}: {1} mapped, {2} aliases, {3} new, {4} skipped" -f `
        $outputPath, $characters.Count, $aliases.Count,
        @($characters | Where-Object new_to_pc_index).Count, $skipped)
} finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $resolvedTemporary = [IO.Path]::GetFullPath($temporaryRoot)
        if (-not $resolvedTemporary.StartsWith($temporaryBase, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove an unexpected temporary path"
        }
        Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
    }
}
