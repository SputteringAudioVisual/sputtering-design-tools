[CmdletBinding()]
param(
    [string]$Destination = 'C:/SPB_Data/pcbenv/pcb_assistant',
    [string]$PythonPath = '',
    [switch]$NoShortcut
)
$ErrorActionPreference = 'Stop'
$source = [IO.Path]::GetFullPath($PSScriptRoot)
$target = [IO.Path]::GetFullPath($Destination).TrimEnd('\','/')
$core = [IO.Path]::GetFullPath('C:/SPB_Data/pcbenv/pcb_tools').TrimEnd('\','/')
if ($target -match '[^\x00-\x7F]') { throw 'La carpeta del asistente debe tener una ruta sin acentos para Allegro 17.2.' }
if ($target -eq $source -or $target -eq $core -or $core.StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase) -or $target.StartsWith($core + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'El asistente debe instalarse en una carpeta independiente de las utilidades y del codigo fuente.'
}
if (-not (Test-Path -LiteralPath (Join-Path $core 'pcb_cargar.il') -PathType Leaf)) {
    throw 'Primero instala las utilidades Allegro existentes en C:/SPB_Data/pcbenv/pcb_tools.'
}
if (-not $PythonPath) {
    $PythonPath = (Get-Command python -ErrorAction Stop).Source
}
$PythonPath = [IO.Path]::GetFullPath($PythonPath)
& $PythonPath -c 'import sys,tkinter; assert sys.version_info >= (3,10); tkinter.Tcl()'
if ($LASTEXITCODE -ne 0) { throw 'Se necesita Python 3.10 o posterior con Tkinter funcionando.' }
Write-Output 'Python y biblioteca grafica: OK'
$pythonWindow = Join-Path (Split-Path -Parent $PythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonWindow -PathType Leaf)) { throw 'No se encuentra pythonw.exe junto a Python.' }
$files = @('app.py','iniciar.pyw','workflow.py','transport.py','saved_board.py','package_report.py','traceability.py','editor_handoff.py','README.md','VALIDACION.md','core_baseline.json','bridge/pcb_assistant_bridge.il',
    'documentacion/CONTRATO_TRAZABILIDAD_PCB.md','documentacion/fabrication-manifest-v1.schema.json','documentacion/fabrication-manifest-v1.example.json')
$before = @{}
Get-ChildItem -LiteralPath $core -File | ForEach-Object { $before[$_.Name] = (Get-FileHash -LiteralPath $_.FullName).Hash }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
New-Item -ItemType Directory -Path $target -Force | Out-Null
foreach ($relative in $files) {
    $from = Join-Path $source $relative
    if ($relative.StartsWith('documentacion/')) {
        $sharedDocs = Join-Path (Split-Path -Parent (Split-Path -Parent $source)) 'docs'
        $from = Join-Path $sharedDocs (Split-Path -Leaf $relative)
    }
    $to = Join-Path $target $relative
    if (-not (Test-Path -LiteralPath $from -PathType Leaf)) { throw "Falta el archivo de instalacion: $relative" }
    if (Test-Path -LiteralPath $to -PathType Leaf) {
        if ((Get-FileHash -LiteralPath $from).Hash -eq (Get-FileHash -LiteralPath $to).Hash) { continue }
        $backup = Join-Path $target ('Backups/' + $stamp + '/' + $relative)
        New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
        Copy-Item -LiteralPath $to -Destination $backup
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $to) -Force | Out-Null
    Copy-Item -LiteralPath $from -Destination $to -Force
}
$newFiles = @(Get-ChildItem -LiteralPath $core -File)
if ($newFiles.Count -ne $before.Count) { throw 'La carpeta de utilidades ha cambiado durante la instalacion. Revisar antes de continuar.' }
foreach ($entry in $newFiles) {
    if ($before[$entry.Name] -ne (Get-FileHash -LiteralPath $entry.FullName).Hash) {
        throw "Ha cambiado una utilidad existente durante la instalacion: $($entry.Name)"
    }
}
if (-not $NoShortcut) {
    $shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'PCB - Asistente.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $pythonWindow
    $shortcut.Arguments = '"' + (Join-Path $target 'iniciar.pyw') + '"'
    $shortcut.WorkingDirectory = $target
    $shortcut.Description = 'Asistente opcional de PCB. No sustituye las utilidades Allegro existentes.'
    $shortcut.Save()
    Write-Output "Acceso directo: $shortcutPath"
}
Write-Output "Instalado en: $target"
Write-Output 'Utilidades existentes verificadas: ningun archivo ha cambiado. No se modifica allegro.ilinit.'
