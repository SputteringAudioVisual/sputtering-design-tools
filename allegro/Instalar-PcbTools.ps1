# One runtime installation; old entrypoints become forwarding loaders.
[CmdletBinding()]
param(
    [string]$InstallRoot = 'C:\SPB_Data\pcbenv\pcb_tools',
    [string[]]$LegacyDirectories = @(),
    [string[]]$LegacyFiles = @()
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$destination = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\','/')
if ($destination -match '[^\x20-\x7e]' -or $destination -match '["%]') {
    throw 'The Allegro installation path must use ASCII characters and cannot contain quotes or percent signs.'
}
$profileRoot = Split-Path -Parent $destination
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$backup = Join-Path $profileRoot ('pcb_tools_backups\' + $stamp)
New-Item -ItemType Directory -Path $destination,$backup -Force | Out-Null
$records = @()
function Get-PcbSha256([string]$Path) {
    $fileStream = [IO.File]::OpenRead($Path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hasher.ComputeHash($fileStream)).Replace('-','').ToLowerInvariant() }
    finally { $hasher.Dispose(); $fileStream.Dispose() }
}
function Save-Previous([string]$Path) {
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $saved = Join-Path $backup (([Guid]::NewGuid().ToString('N')) + '_' + (Split-Path -Leaf $Path))
        Copy-Item -LiteralPath $Path -Destination $saved
        $script:records += [pscustomobject]@{ original=$Path; backup=$saved; sha256=(Get-PcbSha256 $saved) }
    }
}
foreach ($item in Get-ChildItem -LiteralPath $PSScriptRoot -File) {
    if ($item.Extension -in @('.il','.ps1','.md') -and $item.Name -ne 'pcb_local.il') {
        $targetFile = Join-Path $destination $item.Name
        if ([IO.Path]::GetFullPath($item.FullName) -eq [IO.Path]::GetFullPath($targetFile)) { continue }
        Save-Previous $targetFile
        Copy-Item -LiteralPath $item.FullName -Destination $targetFile -Force
    }
}
$asciiRoot = $destination.Replace('\','/')
$entry = "load(`"$asciiRoot/pcb_utilidades.il`")`r`npcbCargar(`"$asciiRoot`")`r`n"
[IO.File]::WriteAllText((Join-Path $destination 'pcb_cargar.il'), $entry, [Text.Encoding]::ASCII)
$init = Join-Path $profileRoot 'allegro.ilinit'
Save-Previous $init
$initEncoding = [Text.Encoding]::GetEncoding(28591) # Preserve existing bytes outside the managed ASCII lines.
$lines = if (Test-Path -LiteralPath $init) { [IO.File]::ReadAllLines($init, $initEncoding) } else { @() }
# Retain unrelated startup code; replace only known utility load lines.
$kept = @($lines | Where-Object {
    $_ -notmatch '^\s*load\(.*(?:fx_mascara\.il|fx_cargar_todo\.il|pcb_cargar\.il|pcb_utilidades\.il)' -and
    $_ -notmatch '^\s*pcbCargar\(' -and
    $_ -notmatch '^\s*;\s*(FX: comandos reutilizables de soldermask|PCB_TOOLS_MANAGED)'
})
$kept += '; PCB_TOOLS_MANAGED: single runtime; loading does not modify a board.'
$kept += "load(`"$asciiRoot/pcb_cargar.il`")"
[IO.File]::WriteAllLines($init, $kept, $initEncoding)
$forward = "; Deprecated entrypoint: use the central PCB tools installation.`r`nload(`"$asciiRoot/pcb_cargar.il`")`r`n"
$known = @('fx_anchos_pistas.il','fx_textos_silk.il','fx_mascara.il','fx_fabricacion.il','fx_cargar_todo.il')
$oldFiles = @($LegacyFiles)
foreach ($oldDirectory in $LegacyDirectories) {
    foreach ($name in $known) {
        $candidate = Join-Path $oldDirectory $name
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { $oldFiles += $candidate }
    }
    if (Test-Path -LiteralPath $oldDirectory -PathType Container) {
        $notice = "UTILIDADES CENTRALIZADAS`r`nInstalacion: $asciiRoot`r`nCargar en Allegro: skill load(`"$asciiRoot/pcb_cargar.il`")`r`nLos .il de esta carpeta solo redirigen; no son copias de las utilidades.`r`n"
        [IO.File]::WriteAllText((Join-Path $oldDirectory 'LEEME_RUTA_UNICA.txt'), $notice, [Text.Encoding]::ASCII)
    }
}
foreach ($oldFile in @($oldFiles | Sort-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $oldFile -PathType Leaf)) { continue }
    if ([IO.Path]::GetFullPath($oldFile).StartsWith($destination + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'A legacy entrypoint cannot be inside the active installation.'
    }
    Save-Previous $oldFile
    [IO.File]::WriteAllText($oldFile, $forward, [Text.Encoding]::ASCII)
}
$records | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $backup 'restauracion.json') -Encoding UTF8
$manifest = @(Get-ChildItem -LiteralPath $destination -File | Where-Object Extension -in @('.il','.ps1') | ForEach-Object {
    [ordered]@{ file=$_.Name; sha256=(Get-PcbSha256 $_.FullName) }
})
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $destination 'instalacion.json') -Encoding UTF8
Write-Output "INSTALLED: $destination"
Write-Output "BACKUP: $backup"
Write-Output "STARTUP: $init"
