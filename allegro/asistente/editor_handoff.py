"""Open an exact Allegro fabrication release in the installed desktop editor."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


def _shortcut_details():
    if os.name != 'nt':
        raise OSError('La apertura directa del editor requiere Windows y el acceso «Apps de Luis» instalado.')
    script = r"""
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$desktop=[Environment]::GetFolderPath('Desktop')
$link=Join-Path $desktop 'Apps de Luis\Editor PCB y serigrafias.lnk'
if (-not (Test-Path -LiteralPath $link -PathType Leaf)) { throw "No se encuentra el acceso: $link" }
$shell=New-Object -ComObject WScript.Shell
$item=$shell.CreateShortcut($link)
[pscustomobject]@{target=$item.TargetPath;arguments=$item.Arguments;workingDirectory=$item.WorkingDirectory} | ConvertTo-Json -Compress
"""
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
        check=True, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=12,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    details=json.loads(result.stdout.lstrip('\ufeff'))
    if not details.get('target'):
        # Some existing desktop shortcuts contain the Python entry script but
        # an empty TargetPath. Reuse the interpreter running this assistant.
        details['target']=str(Path(sys.executable).with_name('pythonw.exe'))
    return details


def _split_shortcut_arguments(value):
    # WScript shortcut arguments are a Windows command-line fragment. The
    # installed app shortcut contains a quoted .py entry point and may add
    # ordinary flags such as --panel.
    return [part.strip('"') for part in shlex.split(value or '', posix=False)]


def editor_command(details, board, fabrication):
    target = Path(details['target'])
    board, fabrication = Path(board).resolve(), Path(fabrication).resolve()
    if not target.is_file():
        raise FileNotFoundError('El acceso del editor apunta a una aplicación que ya no existe: '+str(target))
    if not board.is_file():
        raise FileNotFoundError('No se encuentra la PCB guardada: '+str(board))
    if not fabrication.is_file() or fabrication.suffix.lower() != '.zip':
        raise FileNotFoundError('No se encuentra el ZIP de fabricación generado: '+str(fabrication))
    arguments = _split_shortcut_arguments(details.get('arguments', ''))
    if not arguments:
        raise ValueError('El acceso del editor no contiene la ruta de inicio de Sputtering Design Tools.')
    if any(arg in {'--board', '--fabrication'} for arg in arguments):
        raise ValueError('El acceso del editor ya contiene una liberación; actualízalo antes de continuar.')
    return [str(target), *arguments, '--board', str(board), '--fabrication', str(fabrication)]


def launch_editor(board, fabrication, *, details=None, popen=subprocess.Popen):
    details = details or _shortcut_details()
    command = editor_command(details, board, fabrication)
    working = details.get('workingDirectory') or str(Path(command[1]).parent)
    return popen(command, cwd=working, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
