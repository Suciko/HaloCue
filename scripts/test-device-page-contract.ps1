$ErrorActionPreference = "Stop"

$adbPath = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
if (-not (Test-Path -LiteralPath $adbPath)) {
    throw "ADB not found at $adbPath"
}

& $adbPath shell am force-stop com.halocue.android | Out-Null
& $adbPath shell monkey -p com.halocue.android -c android.intent.category.LAUNCHER 1 | Out-Null
$document = $null
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Seconds 1
    & $adbPath shell uiautomator dump /sdcard/halocue-page-contract.xml | Out-Null
    $xmlText = & $adbPath exec-out cat /sdcard/halocue-page-contract.xml
    $candidate = [xml]$xmlText
    if ($null -ne $candidate.SelectSingleNode("//*[@resource-id='compile-aap']")) {
        $document = $candidate
        break
    }
}
if ($null -eq $document) {
    throw "HaloCue page did not become ready within 30 seconds"
}
$expectedButton = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("55Sf5oiQ5bel56iL5paH5Lu2"))
$expectedStatus = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5bCa5pyq55Sf5oiQ"))
$expectedShare = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5YiG5Lqr5bel56iL5paH5Lu2"))
$forbiddenTexts = @(
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6Ieq5Yqo5a+85YWl6L6F5Yqp5Yqf6IO9")),
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("57un57ut5a+85YWl")),
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("55Sf5oiQ5bm25a+85YWl5Y6f54mIIEFB"))
)

function Get-RenderedNode([string]$resourceId) {
    $node = $document.SelectSingleNode("//*[@resource-id='$resourceId']")
    if ($null -eq $node) {
        throw "Missing rendered node: $resourceId"
    }
    return $node
}

$buttonText = [string](Get-RenderedNode "compile-aap").text
if ($buttonText -ne $expectedButton) {
    throw "Primary button mismatch: '$buttonText'"
}

$statusText = [string](Get-RenderedNode "compile-status").text
if ($statusText -ne $expectedStatus) {
    throw "Initial status mismatch: '$statusText'"
}

$shareNode = Get-RenderedNode "share-aap"
if ([string]$shareNode.text -ne $expectedShare) {
    throw "Share button mismatch: '$([string]$shareNode.text)'"
}
if ([string]$shareNode.enabled -ne "false") {
    throw "Share button must start disabled"
}

$renderedText = (($document.SelectNodes("//*[@text]") | ForEach-Object { [string]$_.text }) -join "`n")
foreach ($forbiddenText in $forbiddenTexts) {
    if ($renderedText.Contains($forbiddenText)) {
        throw "Unsupported assisted-import copy is still rendered: '$forbiddenText'"
    }
}

Write-Output "Device page contract passed"
