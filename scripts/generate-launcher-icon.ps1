param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$SourcePath = ''
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

if (-not $SourcePath) {
    $workspaceRoot = Split-Path (Split-Path (Split-Path $ProjectRoot -Parent) -Parent) -Parent
    $pcRoot = Get-ChildItem -LiteralPath $workspaceRoot -Directory | Where-Object { $_.Name -like '01-*' } | Select-Object -First 1
    if (-not $pcRoot) { throw 'Could not locate the PC source directory (expected a 01-* sibling).' }
    $SourcePath = Join-Path $pcRoot.FullName 'aa\branding\halocue-icon.png'
}
$SourcePath = (Resolve-Path $SourcePath).Path

function Write-ScaledPng {
    param(
        [System.Drawing.Image]$Source,
        [int]$Size,
        [string]$Path,
        [bool]$WithBackground,
        [double]$ContentScale = 1.0
    )

    $scale = 4
    $renderSize = $Size * $scale
    $sourceRender = [System.Drawing.Bitmap]::new($renderSize, $renderSize, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $sourceRender.SetResolution(96, 96)
    $graphics = [System.Drawing.Graphics]::FromImage($sourceRender)
    $graphics.Clear([System.Drawing.Color]::Transparent)
    $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
    $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

    if ($WithBackground) {
        $background = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
        $radius = $renderSize * 0.225
        $pathShape = [System.Drawing.Drawing2D.GraphicsPath]::new()
        $diameter = $radius * 2
        $pathShape.AddArc(0, 0, $diameter, $diameter, 180, 90)
        $pathShape.AddArc($renderSize - $diameter, 0, $diameter, $diameter, 270, 90)
        $pathShape.AddArc($renderSize - $diameter, $renderSize - $diameter, $diameter, $diameter, 0, 90)
        $pathShape.AddArc(0, $renderSize - $diameter, $diameter, $diameter, 90, 90)
        $pathShape.CloseFigure()
        $graphics.FillPath($background, $pathShape)
        $pathShape.Dispose()
        $background.Dispose()
    }

    $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceOver
    $contentSize = [float]($renderSize * $ContentScale)
    $contentOffset = [float](($renderSize - $contentSize) / 2)
    $graphics.DrawImage($Source, $contentOffset, $contentOffset, $contentSize, $contentSize)
    $graphics.Dispose()

    $result = [System.Drawing.Bitmap]::new($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $result.SetResolution(96, 96)
    $resize = [System.Drawing.Graphics]::FromImage($result)
    $resize.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
    $resize.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $resize.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $resize.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $resize.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $resize.DrawImage($sourceRender, 0, 0, $Size, $Size)
    $resize.Dispose()
    $sourceRender.Dispose()

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $result.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    $result.Dispose()
}

$source = [System.Drawing.Image]::FromFile($SourcePath)
$resRoot = Join-Path $ProjectRoot 'app\src\main\res'
$densitySizes = [ordered]@{
    'mipmap-mdpi' = 48
    'mipmap-hdpi' = 72
    'mipmap-xhdpi' = 96
    'mipmap-xxhdpi' = 144
    'mipmap-xxxhdpi' = 192
}

foreach ($entry in $densitySizes.GetEnumerator()) {
    $folder = Join-Path $resRoot $entry.Key
    Write-ScaledPng -Source $source -Size $entry.Value -Path (Join-Path $folder 'ic_launcher.png') -WithBackground $true
    Write-ScaledPng -Source $source -Size $entry.Value -Path (Join-Path $folder 'ic_launcher_round.png') -WithBackground $true
}

Write-ScaledPng -Source $source -Size 432 -Path (Join-Path $resRoot 'drawable-nodpi\ic_launcher_foreground.png') -WithBackground $false -ContentScale 0.60
Write-ScaledPng -Source $source -Size 64 -Path (Join-Path $ProjectRoot 'app\src\main\python\branding\halocue-favicon.png') -WithBackground $true
$source.Dispose()
