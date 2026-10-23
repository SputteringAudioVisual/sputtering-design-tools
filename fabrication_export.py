"""Create a fresh fabrication package, preserving the source archive."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile


def _safe_member(name):
    path = PurePosixPath(name)
    if (not name or '\\' in name or path.is_absolute() or '..' in path.parts
            or ':' in name or str(path) != name):
        raise ValueError(f'Ruta no válida en el paquete: {name}')
    return name


def _text_equal(first, second):
    def normalise(data):
        return data.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    try:
        return normalise(first) == normalise(second)
    except UnicodeError:
        return first == second


class FabricationExport:
    def __init__(self, destination, baseline, source_zip=None):
        self.destination = Path(destination)
        self.source_zip = Path(source_zip) if source_zip else None
        self.baseline = baseline

    def __enter__(self):
        self.destination.mkdir(parents=True, exist_ok=True)
        self._temporary = tempfile.TemporaryDirectory(prefix='.gerber-export-', dir=self.destination)
        self.work = Path(self._temporary.name)/'files'
        self.work.mkdir()
        self.original_manifest = {}
        self._paths = {}
        try:
            if self.source_zip:
                with zipfile.ZipFile(self.source_zip) as archive:
                    members = [m for m in archive.infolist() if not m.is_dir()]
                    seen = set()
                    if sum(m.file_size for m in members) > 200_000_000 or any(m.file_size > 30_000_000 for m in members):
                        raise ValueError('El paquete supera el tamaño máximo admitido.')
                    for member in members:
                        name = _safe_member(member.filename)
                        if name.casefold() in seen:
                            raise ValueError(f'Archivo duplicado en el ZIP: {name}')
                        seen.add(name.casefold())
                        data = archive.read(member)
                        target = self.work/name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(data)
                    manifest_path = self.work/'manifest.json'
                    if manifest_path.exists():
                        self.original_manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
                        for record in self.original_manifest.get('files', []):
                            data = (self.work/_safe_member(record['name'])).read_bytes()
                            if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                                raise ValueError(f'El ZIP original no coincide con su manifiesto: {record["name"]}')
            for file in self.work.rglob('*'):
                if file.is_file():
                    self._paths.setdefault(file.name.casefold(), []).append(file)
            for name, data in self.baseline.items():
                target = self.path_for(name)
                if target.exists():
                    if not _text_equal(target.read_bytes(), data):
                        raise ValueError(f'{name}: la capa cargada no coincide con el paquete original. Carga el mismo proyecto antes de exportar.')
                else:
                    target.write_bytes(data)
            return self
        except Exception:
            self._temporary.cleanup()
            raise

    def __exit__(self, *args):
        self._temporary.cleanup()

    def path_for(self, name):
        if PurePosixPath(_safe_member(name)).name != name:
            raise ValueError(f'El nombre de capa debe ser un archivo: {name}')
        if name.casefold() in {'manifest.json', 'leeme_fabricacion.txt'}:
            raise ValueError(f'Nombre de capa reservado: {name}')
        matches = self._paths.get(name.casefold(), [])
        if len(matches) > 1:
            raise ValueError(f'El paquete contiene más de un archivo llamado {name}.')
        if matches:
            return matches[0]
        target = self.work/name
        self._paths[name.casefold()] = [target]
        return target

    def _preserve_metadata(self, name):
        source = self.work/name
        if not source.exists():
            return
        history = self.work/'historial_editor'
        history.mkdir(exist_ok=True)
        count = 1
        target = history/f'{Path(name).stem}_original_{count:03d}{Path(name).suffix}'
        while target.exists():
            count += 1
            target = history/f'{Path(name).stem}_original_{count:03d}{Path(name).suffix}'
        source.rename(target)

    def finish(self, changes, settings, drill_formats=None):
        prefix = re.sub(r'[^\w.-]+', '_', self.source_zip.stem if self.source_zip else 'gerbers')
        prefix = re.sub(r'(?:_edit_v\d+)+$', '', prefix)
        source_hash = hashlib.sha256(self.source_zip.read_bytes()).hexdigest() if self.source_zip else None
        self._preserve_metadata('manifest.json')
        self._preserve_metadata('LEEME_FABRICACION.txt')
        note = ('PAQUETE MODIFICADO EN EL EDITOR GERBER\n\n'
                'Incluye las capas originales y las modificaciones seleccionadas.\n'
                'Los taladros y archivos no editados conservan el contenido de origen.\n'
                'El manifiesto contiene las sumas de este paquete. Los informes de\n'
                'Allegro y los documentos en historial_editor pertenecen al origen.\n'
                'La edicion requiere revision CAM antes de fabricar.\n\n'
                + 'Capas procesadas:\n' + ''.join(f'- {c["file"]}: {c["mode"]}\n' for c in changes))
        (self.work/'LEEME_FABRICACION.txt').write_text(note, encoding='utf-8')
        manifest = {
            'board': self.original_manifest.get('board', 'gerbers'),
            'fabrication_version': self.original_manifest.get('fabrication_version'),
            'editor': 'Sputtering Design Tools',
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'status': 'MODIFICADO_PENDIENTE_REVISION',
            'source_status': self.original_manifest.get('status'),
            'cam_review_required': True,
            'source_package': self.source_zip.name if self.source_zip else None,
            'source_sha256': source_hash,
            'changes': changes, 'conversion': settings,
            'drill_formats': drill_formats or {},
            'files': [],
        }
        for file in sorted(self.work.rglob('*')):
            if file.is_file():
                data = file.read_bytes()
                manifest['files'].append({'name': file.relative_to(self.work).as_posix(),
                                          'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        (self.work/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        staged_zip = Path(self._temporary.name)/'package.zip'
        with zipfile.ZipFile(staged_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(self.work.rglob('*')):
                if file.is_file(): archive.write(file, file.relative_to(self.work).as_posix())
        with zipfile.ZipFile(staged_zip) as archive:
            if archive.testzip() is not None:
                raise ValueError('No se pudo verificar el ZIP generado.')
            for record in manifest['files']:
                if hashlib.sha256(archive.read(record['name'])).hexdigest() != record['sha256']:
                    raise ValueError(f'No se pudo verificar {record["name"]}.')
        # Exclusive creation reserves a fresh name even for concurrent exports.
        revision = 1
        while True:
            folder = self.destination/f'{prefix}_edit_v{revision:03d}'
            output_zip = folder.parent/(folder.name+'.zip')
            if folder.exists() or output_zip.exists():
                revision += 1
                continue
            try:
                stream = output_zip.open('xb')
            except FileExistsError:
                revision += 1
                continue
            try:
                with stream, staged_zip.open('rb') as source:
                    shutil.copyfileobj(source, stream)
                self.work.rename(folder)
            except Exception:
                output_zip.unlink()  # Only the file created exclusively above.
                raise
            return folder, output_zip
