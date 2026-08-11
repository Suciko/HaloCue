$ErrorActionPreference = "Stop"

$pythonRoot = Join-Path $PSScriptRoot "..\app\src\main\python"
$uiPath = Join-Path $pythonRoot "ui.html"
$uiHtml = Get-Content -Raw -LiteralPath $uiPath

$requiredScripts = @(
    '/js/api.js',
    '/js/story.js',
    '/js/story_picker.js',
    '/js/assets.js',
    '/js/history.js',
    '/js/library_preview.js',
    '/js/library_transfer.js',
    '/js/library_copies.js',
    '/js/library_faces.js',
    '/js/library_import.js',
    '/js/library.js',
    '/js/model.js',
    '/js/cards.js',
    '/js/player.js',
    '/js/app.js'
)
foreach ($scriptPath in $requiredScripts) {
    $scriptTag = 'src="' + $scriptPath + '"'
    if ($uiHtml -notmatch [regex]::Escape($scriptTag)) {
        throw "ui.html is missing required script: $scriptPath"
    }
}

$requiredRoots = @('storyContextBar', 'view-create', 'modelSettings', 'reviewPhase', 'rvCards', 'assetWorkbench')
foreach ($rootId in $requiredRoots) {
    $rootTag = 'id="' + $rootId + '"'
    if ($uiHtml -notmatch [regex]::Escape($rootTag)) {
        throw "ui.html is missing required feature root: $rootId"
    }
}
if ($uiHtml -match 'HALOCUE\s+FOR\s+ANDROID|window\.HaloCueApp\.bootstrap') {
    throw "ui.html still contains the Android MVP bootstrap surface"
}

$layoutCss = Get-Content -Raw -LiteralPath (Join-Path $pythonRoot "css\layout.css")
$finalMobileMarker = "/* Final narrow-screen overrides must follow full-screen workbench component rules. */"
$finalMobileStart = $layoutCss.IndexOf($finalMobileMarker)
if ($finalMobileStart -lt 0) {
    throw "layout.css is missing the final mobile override block"
}
$finalMobileCss = $layoutCss.Substring($finalMobileStart)
$requiredMobileTouchSelectors = @(
    '.story-picker-commandbar .icon-button',
    '.story-picker-footer button',
    '.face-card-actions button',
    '.face-card-editor button'
)
foreach ($selector in $requiredMobileTouchSelectors) {
    if (-not $finalMobileCss.Contains($selector)) {
        throw "Final mobile overrides are missing touch target: $selector"
    }
}

$adbPath = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
if (-not (Test-Path -LiteralPath $adbPath)) {
    throw "ADB not found at $adbPath"
}
$deviceLines = & $adbPath devices
$hasDevice = @($deviceLines | Where-Object { $_ -match '^\S+\s+device$' }).Count -gt 0
if (-not $hasDevice) {
    throw "No connected Android device or emulator is available"
}

& $adbPath shell am force-stop com.halocue.android | Out-Null
$ErrorActionPreference = "Continue"
$monkeyOutput = & $adbPath shell monkey -p com.halocue.android -c android.intent.category.LAUNCHER 1 2>&1
$monkeyExitCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($monkeyExitCode -ne 0) {
    throw "Failed to launch HaloCue: $($monkeyOutput -join ' ')"
}
$document = $null
for ($attempt = 0; $attempt -lt 12; $attempt++) {
    Start-Sleep -Milliseconds 250
    & $adbPath shell uiautomator dump /sdcard/halocue-page-contract.xml | Out-Null
    $xmlText = & $adbPath exec-out cat /sdcard/halocue-page-contract.xml
    $candidate = [xml]$xmlText
    if ($null -ne $candidate.SelectSingleNode("//*[@resource-id='view-create']")) {
        $document = $candidate
        break
    }
}
if ($null -eq $document) {
    throw "Full PC WebUI did not become ready within the device contract timeout"
}

$requiredRenderedRoots = @('appShell', 'view-create', 'welcomePanel', 'workflowProgress', 's1')
foreach ($rootId in $requiredRenderedRoots) {
    $node = $document.SelectSingleNode("//*[@resource-id='$rootId']")
    if ($null -eq $node) {
        throw "Missing rendered feature root: $rootId"
    }
}

$renderedText = (($document.SelectNodes("//*[@text]") | ForEach-Object { [string]$_.text }) -join "`n")
if ($renderedText -match 'HALOCUE\s+FOR\s+ANDROID') {
    throw "Android MVP copy is still rendered"
}

Write-Output "Full PC WebUI device contract passed"
