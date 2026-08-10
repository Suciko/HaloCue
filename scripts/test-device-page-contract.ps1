$ErrorActionPreference = "Stop"

$adbPath = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
if (-not (Test-Path -LiteralPath $adbPath)) {
    throw "ADB not found at $adbPath"
}

& $adbPath shell am force-stop com.halocue.android | Out-Null
& $adbPath shell monkey -p com.halocue.android -c android.intent.category.LAUNCHER 1 | Out-Null
Start-Sleep -Seconds 2
& $adbPath shell uiautomator dump /sdcard/halocue-page-contract.xml | Out-Null
$xmlText = & $adbPath exec-out cat /sdcard/halocue-page-contract.xml
$document = [xml]$xmlText
$expectedButton = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("55Sf5oiQ5bm25a+85YWl5Y6f54mIIEFB"))
$expectedStatus = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5bCa5pyq5aSE55CG"))
$expectedExplanation = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6Ieq5Yqo5a+85YWl6L6F5Yqp5Yqf6IO9"))

function Get-NodeText([string]$resourceId) {
    $node = $document.SelectSingleNode("//*[@resource-id='$resourceId']")
    if ($null -eq $node) {
        throw "Missing rendered node: $resourceId"
    }
    return [string]$node.text
}

$buttonText = Get-NodeText "compile-aap"
if ($buttonText -ne $expectedButton) {
    throw "Primary button mismatch: '$buttonText'"
}

$statusText = Get-NodeText "compile-status"
if ($statusText -ne $expectedStatus) {
    throw "Initial status mismatch: '$statusText'"
}

$explanationText = Get-NodeText "accessibility-card"
if (-not $explanationText.Contains($expectedExplanation)) {
    throw "Missing first-use accessibility explanation"
}

Write-Output "Device page contract passed"
