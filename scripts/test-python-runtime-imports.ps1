$ErrorActionPreference = "Stop"

$pythonRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\app\src\main\python")).Path
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $pythonRoot

try {
    $modules = @(
        "webui",
        "llm",
        "model_profiles",
        "draft_store",
        "annotate",
        "script2aap",
        "android_capabilities"
    )
    $moduleLiteral = ($modules | ForEach-Object { "'$_'" }) -join ","
    $code = "import importlib; [importlib.import_module(name) for name in [$moduleLiteral]]"
    & python -c $code
    if ($LASTEXITCODE -ne 0) {
        throw "Python runtime import contract failed"
    }
    Write-Output "Python runtime import contract passed: $($modules -join ', ')"
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
