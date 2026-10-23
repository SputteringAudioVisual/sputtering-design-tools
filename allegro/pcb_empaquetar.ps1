# Called by Allegro from a fresh export directory. Uses Windows/.NET only.
[CmdletBinding()]
param([string]$Directory = (Get-Location).Path)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
function Get-PcbSha256([string]$Path) {
    $fileStream = [IO.File]::OpenRead($Path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hasher.ComputeHash($fileStream)).Replace('-','').ToLowerInvariant() }
    finally { $hasher.Dispose(); $fileStream.Dispose() }
}
$folder = (Resolve-Path -LiteralPath $Directory).Path
$archivePath = $folder + '.zip'
$temporaryPath = $null
try {
    $info = @{}
    foreach ($line in [IO.File]::ReadAllLines((Join-Path $folder 'pcb_export_info.txt'))) {
        $pair = $line -split '=', 2
        if ($pair.Count -eq 2) { $info[$pair[0]] = $pair[1] }
    }
    foreach ($key in @('artwork_status', 'ncdrill_status')) {
        if ($info[$key] -notin @('0','1')) { throw "Export failed: $key=$($info[$key])" }
    }
    $name = Split-Path -Leaf $folder
    if ($name -notmatch '^(?<board>.+)_fab_v(?<version>\d+)$') {
        throw 'The export directory must end with _fab_vNNN.'
    }
    $boardName = $Matches.board
    $version = [int]$Matches.version
    $payload = @()
    foreach ($film in @('COPPER_TOP','COPPER_BOTTOM','MASK_TOP','MASK_BOTTOM','OUTLINE','SILK_TOP','SILK_BOTTOM')) {
        $path = Join-Path $folder ($film + '.art')
        $content = [IO.File]::ReadAllText($path)
        if ($content -notmatch '(?s)%[^%]*MOMM\*[^%]*%' -or
            $content -notmatch '(?s)%[^%]*FSLAX55Y55\*[^%]*%' -or
            $content -notmatch 'M02\*\s*\z') { throw "Invalid or incomplete Gerber: $film" }
        $payload += [pscustomobject]@{ Path=$path; Entry=($film + '.art') }
    }
    $drills = @(Get-ChildItem -LiteralPath $folder -Filter '*.drl' -File)
    if ($drills.Count -eq 0) { throw 'No NC Drill file was generated.' }
    foreach ($drill in $drills) {
        $content = [IO.File]::ReadAllText($drill.FullName)
        if ($content -notmatch '\AM48\s' -or $content -notmatch 'METRIC,' -or
            $content -notmatch 'M30\s*\z') { throw "Invalid or incomplete NC Drill: $($drill.Name)" }
        $payload += [pscustomobject]@{ Path=$drill.FullName; Entry=$drill.Name }
    }
    foreach ($file in @('photoplot.log','ncdrill.log','pcb_export_info.txt','art_param.txt','nc_param.txt','nc_tools_auto.txt','config_utilidades.il')) {
        $path = Join-Path $folder $file
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $prefix = if ($file -like '*.log') {'informes/'} else {'parametros/'}
            $payload += [pscustomobject]@{ Path=$path; Entry=($prefix + $file) }
        }
    }
    $warnings = ($info.artwork_status -eq '1' -or $info.ncdrill_status -eq '1')
    $manifest = [ordered]@{
        board=$boardName; fabrication_version=$version; tools_version=$info.tools_version
        created_utc=[DateTime]::UtcNow.ToString('o')
        status=$(if ($warnings) {'REQUIERE_REVISION_AVISOS'} else {'EXPORTADO_SIN_AVISOS'})
        artwork_status=[int]$info.artwork_status; ncdrill_status=[int]$info.ncdrill_status
        source='Current Allegro database in memory; no original PCB is included.'
        cam_review_required=$true
        files=@($payload | ForEach-Object {
            [ordered]@{ name=$_.Entry; bytes=(Get-Item -LiteralPath $_.Path).Length
                sha256=(Get-PcbSha256 $_.Path) }
        })
    }
    $manifestPath = Join-Path $folder 'manifest.json'
    [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
    $report = @(
        "Placa: $boardName", "Version de fabricacion: v$('{0:D3}' -f $version)",
        "Version de utilidades: $($info.tools_version)", "Estado: $($manifest.status)",
        "Artwork: $($info.artwork_status); NC Drill: $($info.ncdrill_status) (0=sin avisos, 1=con avisos).",
        'Incluye Gerber RS-274X metricos 5.5 y NC Drill Excellon metrico.',
        'Revisar siempre DRC y alineacion de capas/contorno/taladros en un visor CAM.',
        'Los avisos figuran en informes/photoplot.log y en informes/ncdrill.log.',
        'El paquete representa el estado en memoria al exportar; no certifica fabricabilidad.'
    )
    $reportPath = Join-Path $folder 'LEEME_FABRICACION.txt'
    [IO.File]::WriteAllLines($reportPath, $report, (New-Object Text.UTF8Encoding($false)))
    $payload += [pscustomobject]@{ Path=$manifestPath; Entry='manifest.json' }
    $payload += [pscustomobject]@{ Path=$reportPath; Entry='LEEME_FABRICACION.txt' }
    # Write to a unique temporary file, then rename without replacing any ZIP.
    $temporaryPath = $archivePath + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    $stream = [IO.File]::Open($temporaryPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try {
        $zip = New-Object IO.Compression.ZipArchive($stream, [IO.Compression.ZipArchiveMode]::Create, $true)
        try {
            foreach ($entry in $payload) {
                [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $entry.Path, $entry.Entry,
                    [IO.Compression.CompressionLevel]::Optimal) | Out-Null
            }
        } finally { $zip.Dispose() }
    } finally { $stream.Dispose() }
    $check = [IO.Compression.ZipFile]::OpenRead($temporaryPath)
    try {
        if ($check.Entries.Count -ne $payload.Count) { throw 'Incomplete ZIP.' }
        foreach ($entry in $check.Entries) {
            $entryStream = $entry.Open()
            $hasher = [Security.Cryptography.SHA256]::Create()
            try {
                $actual = [BitConverter]::ToString($hasher.ComputeHash($entryStream)).Replace('-','').ToLowerInvariant()
                $original = Get-PcbSha256 (($payload | Where-Object Entry -eq $entry.FullName).Path)
                if ($actual -ne $original) { throw "ZIP checksum mismatch: $($entry.FullName)" }
            } finally { $hasher.Dispose(); $entryStream.Dispose() }
        }
    } finally { $check.Dispose() }
    [IO.File]::Move($temporaryPath, $archivePath)
    Write-Output "ZIP: $archivePath"
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 2
} finally {
    if ($temporaryPath -and [IO.File]::Exists($temporaryPath)) { [IO.File]::Delete($temporaryPath) }
}
