# Rasterises PDF pages to PNG with the Windows built-in PDF renderer (Windows.Data.Pdf).
# An independent renderer from ReportLab, used to inspect shaping and layout visually.
#   powershell -NoProfile -ExecutionPolicy Bypass -File rasterise-pdf.ps1 -Pdf in.pdf -OutDir out -Pages "1,2" -Width 1654
param(
    [Parameter(Mandatory = $true)][string]$Pdf,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string]$Pages = "1",
    [int]$Width = 1654,
    [string]$Prefix = "page"
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFolder, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfPageRenderOptions, Windows.Data.Pdf, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]

$asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
$asTaskAction = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction'
} | Select-Object -First 1

function Await($op, [Type]$resultType) {
    $task = $asTaskGeneric.MakeGenericMethod($resultType).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    return $task.Result
}
function AwaitAction($action) {
    $task = $asTaskAction.Invoke($null, @($action))
    $task.Wait(-1) | Out-Null
}

$pdfPath = (Resolve-Path $Pdf).Path
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$outPath = (Resolve-Path $OutDir).Path
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($pdfPath)) ([Windows.Storage.StorageFile])
$doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
$folder = Await ([Windows.Storage.StorageFolder]::GetFolderFromPathAsync($outPath)) ([Windows.Storage.StorageFolder])
Write-Output "pages=$($doc.PageCount)"
foreach ($n in ($Pages -split "[,; ]+" | Where-Object { $_ } | ForEach-Object { [int]$_ })) {
    if ($n -lt 1 -or $n -gt $doc.PageCount) { throw "page $n out of range 1..$($doc.PageCount)" }
    $page = $doc.GetPage($n - 1)
    $name = "$Prefix-$n.png"
    $target = Await ($folder.CreateFileAsync($name, [Windows.Storage.CreationCollisionOption]::ReplaceExisting)) ([Windows.Storage.StorageFile])
    $stream = Await ($target.OpenAsync([Windows.Storage.FileAccessMode]::ReadWrite)) ([Windows.Storage.Streams.IRandomAccessStream])
    $options = New-Object Windows.Data.Pdf.PdfPageRenderOptions
    $options.DestinationWidth = $Width
    AwaitAction ($page.RenderToStreamAsync($stream, $options))
    $stream.Dispose()
    $page.Dispose()
    Write-Output (Join-Path $outPath $name)
}
# WinRT keeps background threads alive; end the host explicitly once every page is written.
[System.Environment]::Exit(0)
