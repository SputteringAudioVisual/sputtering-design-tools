"""Create a fresh fabrication package, preserving the source archive."""
from datetime import datetime, timezone
import hashlib
import io
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
        self.parent_manifest_bytes=None;self.source_archive_sha256=None;self.sealed_source=False
        self._paths = {}
        try:
            if self.source_zip:
                from package_integrity import read_archive
                from release_contract import validate_release
                raw=self.source_zip.read_bytes()
                payload,self.original_manifest=read_archive(io.BytesIO(raw))
                self.sealed_source=validate_release(self.original_manifest,payload)
                self.parent_manifest_bytes=payload.get('manifest.json')
                self.source_archive_sha256=hashlib.sha256(raw).hexdigest()
                for name,data in payload.items():
                    target=self.work/name
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(data)
            for file in self.work.rglob('*'):
                if file.is_file():
                    self._paths.setdefault(file.name.casefold(), []).append(file)
            for name, data in self.baseline.items():
                target = self.path_for(name)
                if target.exists():
                    if not _text_equal(target.read_bytes(), data):
                        raise ValueError(f'{name}: la capa cargada no coincide con el paquete original. Carga el mismo proyecto antes de exportar.')
                else:
                    from package_integrity import MANUFACTURING
                    if self.sealed_source and Path(name).suffix.lower() in MANUFACTURING:
                        raise ValueError('Capa ajena a la liberación sellada: '+name)
                    target.write_bytes(data)
            if not self.source_zip:
                buffer=io.BytesIO()
                with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
                    for file in sorted(self.work.rglob('*')):
                        if file.is_file():
                            info=zipfile.ZipInfo(file.relative_to(self.work).as_posix())
                            z.writestr(info,file.read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
                self.baseline_archive=buffer.getvalue()
                self.source_archive_sha256=hashlib.sha256(self.baseline_archive).hexdigest()
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
        from module_project import locked
        with locked(self.destination):return self._finish(changes,settings,drill_formats)

    def _finish(self,changes,settings,drill_formats=None):
        prefix = re.sub(r'[^\w.-]+', '_', self.source_zip.stem if self.source_zip else 'gerbers')
        prefix = re.sub(r'(?:_edit_v\d+)+$', '', prefix)
        prefix = re.sub(r'^(?:[0-9a-f]{12,16}_)+','',prefix)
        lineage=settings.get('lineage') or {}
        if lineage.get('module_name'):
            suffix={'panel_artwork':'frontal_arte','pcb_silkscreen':'pcb_serigrafia'}.get(lineage['stage'],'gerbers')
            prefix=re.sub(r'[^\w.-]+','_',lineage['module_name'])+'_'+suffix
        source_hash = hashlib.sha256(self.source_zip.read_bytes()).hexdigest() if self.source_zip else None
        if self.source_zip and source_hash!=self.source_archive_sha256:
            raise ValueError('El ZIP de origen cambió durante la edición; vuelve a importarlo.')
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
        from release_contract import derivative,inventory,validate_release,SCHEMA
        parent=self.original_manifest
        root_id=parent.get('base_fabrication_release_id') if self.sealed_source else None
        base_hash=parent.get('base_archive_sha256') or self.source_archive_sha256
        sequence=parent.get('fabrication_edit_sequence',0)+1 if self.sealed_source else 1
        for prior in self.destination.glob('*.zip'):
            try:
                with zipfile.ZipFile(prior) as z:old=json.loads(z.read('manifest.json'))
                if old.get('schema')==SCHEMA and old.get('release_kind')=='gerber_derived' and (
                    (root_id and old.get('base_fabrication_release_id')==root_id) or (not root_id and old.get('base_archive_sha256')==base_hash)):
                    sequence=max(sequence,int(old['fabrication_edit_sequence'])+1)
            except (OSError,ValueError,KeyError,zipfile.BadZipFile):continue
        profile=dict(conversion=settings,changes=changes)
        manifest.update(derivative(parent,self.source_archive_sha256,self.parent_manifest_bytes,sequence,profile,lineage.get('module_id')))
        if not self.source_zip:
            snapshot='historial_editor/base_sin_manifiesto.zip'
            (self.work/snapshot).parent.mkdir(parents=True,exist_ok=True)
            (self.work/snapshot).write_bytes(self.baseline_archive)
            manifest['parent_archive_member']=snapshot
        payload={file.relative_to(self.work).as_posix():file.read_bytes() for file in self.work.rglob('*')
                 if file.is_file() and file.relative_to(self.work).as_posix()!='manifest.json'}
        manifest['files']=inventory(payload,parent)
        validate_release(manifest,payload)
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
