"""Local, portable PCB projects. Sources are copied, never edited in place."""
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile

from panel_model import PanelDocument, load_references, atomic_write
from footprint_holes import read_pcb, library_rules, proposals

SCHEMA = 'sputtering.pcb-project.v1'


def projects_root():
    folder = Path(__file__).resolve().parent
    if folder.name == 'gerber_silkscreen_editor' and folder.parent.name == 'tools':
        folder = folder.parent.parent
    return folder/'panel-projects'


def local_path(root, name):
    path = (Path(root)/name).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('El proyecto contiene una ruta fuera de su carpeta.')
    return path


def project_info(panel_path):
    if not panel_path: return None
    path = Path(panel_path).parent/'project.json'
    if not path.exists(): return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != SCHEMA: raise ValueError('Metadatos de proyecto no reconocidos.')
    return data


def fabrication_source(panel_path):
    if not panel_path: return None
    root = Path(panel_path).parent
    info = project_info(panel_path)
    if info: return local_path(root, info['fabrication_zip'])
    old = root/'REFERENCIAS_ACTUALES.json'
    if old.exists():
        name = json.loads(old.read_text(encoding='utf-8')).get('source_zip')
        if name: return Path(name) if Path(name).is_absolute() else local_path(root, name)
    return None


def export_folder(panel_path, kind):
    if not panel_path:return None
    from module_project import destination
    unified=destination(panel_path,kind)
    if unified:return unified
    folder = Path(panel_path).resolve().parent/'exports'/kind
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def load_project(panel_path):
    """Open using the project's pinned local sources, retaining manual layout."""
    document=PanelDocument.load(panel_path)
    info=project_info(panel_path)
    if info is None:return document
    root=Path(panel_path).parent
    package=fabrication_source(panel_path)
    if hashlib.sha256(package.read_bytes()).hexdigest()!=info['fabrication_sha256']:
        raise ValueError('El paquete local de fabricación ha cambiado; recupera su copia original.')
    refs,errors=load_references([package])
    if errors:raise ValueError('; '.join(errors))
    visibility={Path(r.name).name:r.visible for r in document.layers}
    for ref in refs:ref.visible=visibility.get(Path(ref.name).name,ref.coord_format is not None)
    document.layers=refs;document.choose_outline()
    from footprint_holes import validate_data
    data=validate_data(json.loads(local_path(root,info['components']).read_text(encoding='utf-8')))
    if data.get('source_sha256')!=info['pcb_sha256']:raise ValueError('Las posiciones guardadas corresponden a otra PCB.')
    points=[(p['x'],p['y']) for ref in refs if ref.coord_format for p in ref.layer.drawables]
    proposals(data,document.footprint_rules,document.reference_bounds(),points)
    document.component_data=data
    return document


def _payload(path):
    """Bounded, checked package; retain reports and milling files as well."""
    path = Path(path)
    if path.is_file():
        with zipfile.ZipFile(path) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if len(members)>2000 or sum(m.file_size for m in members)>200_000_000:
                raise ValueError('Paquete de fabricación demasiado grande.')
            names = [m.filename for m in members]
            if len({n.casefold() for n in names}) != len(names): raise ValueError('Archivos duplicados en el ZIP.')
            payload = {m.filename:archive.read(m) for m in members}
    else:
        cad_folder=any(p.is_file() and p.suffix.lower() in {'.brd','.dsn','.opj'} for p in path.iterdir())
        if cad_folder:
            # Native Allegro often writes artwork next to the BRD. Only take
            # manufacturing files here; never pack Capture/Allegro sources.
            from panel_model import GERBER_EXTENSIONS,DRILL_EXTENSIONS
            files=[p for p in path.iterdir() if p.is_file() and
                (p.suffix.lower() in GERBER_EXTENSIONS|DRILL_EXTENSIONS or p.name.lower() in {'nc_param.txt','manifest.json'})]
            params=path/'parametros'/'nc_param.txt'
            if params.is_file():files.append(params)
        else:files = [p for p in path.rglob('*') if p.is_file()]
        if len(files)>2000 or sum(p.stat().st_size for p in files)>200_000_000:
            raise ValueError('Carpeta de fabricación demasiado grande.')
        payload = {p.relative_to(path).as_posix():p.read_bytes() for p in files}
    for name, raw in payload.items():
        pure = PurePosixPath(name)
        if pure.is_absolute() or '..' in pure.parts or ':' in name or '\\' in name or len(raw)>30_000_000:
            raise ValueError('Ruta o tamaño no válido en la fabricación.')
    manifest = json.loads(payload.get('manifest.json',b'{}').decode('utf-8-sig'))
    from package_integrity import validate_manifest
    validate_manifest(payload,manifest)
    if isinstance(manifest.get('schema'),str) and manifest['schema'].startswith('sputtering.fabrication.'):
        from release_contract import validate_release
        validate_release(manifest,payload)
    return payload, manifest


def _archive(payload):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(payload.items()): archive.writestr(name,raw)
    return buffer.getvalue()


def _candidates(board):
    board = Path(board)
    from release_contract import cad_binding,SCHEMA
    binding=cad_binding(board)
    folders = {board.parent}
    # Only neighbouring project directories; never search the entire desktop.
    for parent in (board.parent,board.parent.parent):
        for child in parent.iterdir():
            if child.is_dir() and re.search(r'fabricaci[oó]n|fabrication|gerber',child.name,re.I):
                folders.add(child)
    candidates = set()
    for folder in sorted(folders):
        if any(p.is_file() and p.suffix.lower() in {'.art','.gbr','.ger','.gto','.gko','.gm1'} for p in folder.iterdir()):
            candidates.add(folder)
        for child in folder.iterdir():
            if '_edit_v' in child.name.lower() or child.name in {'panel-projects','.git','historial'}: continue
            if child.is_file() and child.suffix.lower()=='.zip': candidates.add(child)
            if child.is_dir() and any(p.suffix.lower() in {'.art','.gbr','.gto','.gko','.gm1'} for p in child.iterdir() if p.is_file()):
                candidates.add(child)
    ranked = []
    for candidate in sorted(candidates):
        try:
            if candidate.is_file():
                with zipfile.ZipFile(candidate) as z:
                    manifest = json.loads(z.read('manifest.json')) if 'manifest.json' in z.namelist() else {}
            else:
                path = candidate/'manifest.json'
                manifest = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
            if manifest.get('schema')==SCHEMA:
                # A renamed BRD is associated by Allegro's explicit UUID link,
                # never inferred from its filename or matching binary hash.
                if not binding or manifest.get('project_id')!=binding['project_id'] or manifest.get('pcb_revision')!=binding['pcb_revision']:continue
                name=binding['project_id'];version=manifest.get('fabrication_sequence',0)
                if manifest.get('release_kind')!='allegro_original':continue
            else:
                if binding:continue
                name = str(manifest.get('board',''))
                if name and Path(name).stem.casefold()!=board.stem.casefold(): continue
                version = manifest.get('fabrication_version',0)
            version = int(version) if str(version).isdigit() else 0
            exact = bool(name) or candidate.stem.casefold().startswith(board.stem.casefold())
            ranked.append((exact,version,candidate.stat().st_mtime,candidate.suffix.lower()=='.zip',candidate))
        except (OSError,ValueError,KeyError,zipfile.BadZipFile): continue
    return sorted(ranked,reverse=True)


def discover_fabrication(board, data, rules, explicit=None):
    ranked = [(True,0,0,True,Path(explicit))] if explicit else _candidates(board)
    if not ranked:
        from release_contract import cad_binding
        if not explicit and cad_binding(board):
            raise ValueError('No hay una liberación Allegro para la identidad y revisión PCB vinculadas. Genera una nueva liberación desde el asistente Allegro.')
        raise ValueError('No se encuentra fabricación junto a la PCB. Exporta Gerber, taladros y ranuras en una carpeta Fabricacion junto al .brd.')
    # A newer identified revision must not silently fall back to an older one.
    if not explicit and ranked[0][0]:
        best = ranked[0][:2]
        ranked = [r for r in ranked if r[:2]==best]
    failures = []
    from release_contract import SCHEMA
    binding = None
    try:
        from release_contract import cad_binding
        binding = cad_binding(board)
    except (OSError, ValueError, KeyError, TypeError) as error:
        if not explicit:
            raise ValueError('No se puede leer el vínculo de identidad Allegro: '+str(error)) from error
    for _,_,_,_,source in ranked:
        try:
            payload, manifest = _payload(source)
            packed = source.read_bytes() if source.is_file() else _archive(payload)
            if binding and manifest.get('schema') == SCHEMA and manifest.get('release_kind') == 'allegro_original':
                if manifest.get('project_id') != binding.get('project_id') or manifest.get('pcb_revision') != binding.get('pcb_revision'):
                    raise ValueError('La liberación pertenece a otra identidad o revisión PCB.')
            identity_link = bool(manifest.get('schema') == SCHEMA
                and manifest.get('release_kind') == 'allegro_original'
                and (not binding or (manifest.get('project_id') == binding.get('project_id')
                                     and manifest.get('pcb_revision') == binding.get('pcb_revision'))))
            exact_identity = bool(manifest.get('schema') == SCHEMA
                and manifest.get('release_kind') == 'allegro_original'
                and manifest.get('source_saved_board_sha256') == data.get('source_sha256')
                and (not binding or (manifest.get('project_id') == binding.get('project_id')
                                     and manifest.get('pcb_revision') == binding.get('pcb_revision'))))
            with tempfile.TemporaryDirectory(prefix='pcb-fabrication-') as temporary:
                package = Path(temporary)/'fabrication.zip'; package.write_bytes(packed)
                refs, errors = load_references([package])
            if errors: raise ValueError('; '.join(errors[:2]))
            document = PanelDocument(layers=refs)
            if not refs or not document.choose_outline(): raise ValueError('Falta un contorno Gerber identificable.')
            outline = document.reference_bounds()
            expected = data.get('outline_bounds_mm', [])
            outline_matches = len(expected) == 4 and all(abs(float(a)-float(b)) <= .05 for a,b in zip(outline, expected))
            points = [(p['x'],p['y']) for ref in refs if ref.coord_format for p in ref.layer.drawables]
            items=[]
            if points:
                items,_ = proposals(data,rules,document.reference_bounds(),points)
            if not items and not outline_matches:
                raise ValueError('El contorno Gerber no coincide con la PCB guardada.')
            if not items and not exact_identity and not (identity_link or explicit):
                if not points: raise ValueError('Faltan taladros o ranuras para comprobar el registro.')
                raise ValueError('No hay componentes reconocidos para comprobar automáticamente el registro. Selecciona explícitamente el ZIP correcto para importarlo como histórico.')
            check=('registration' if items else 'identity_and_source_hash' if exact_identity else
                   'identity_revision_outline' if identity_link else 'explicit_outline_only')
            return dict(source=source,payload=payload,manifest=manifest,packed=packed,layers=refs,
                        verified_components=len(items),
                        fabrication_check=check)
        except (OSError,ValueError,KeyError,zipfile.BadZipFile) as error:
            failures.append(source.name+': '+str(error))
    raise ValueError('No se ha cambiado el proyecto. La fabricación encontrada no coincide o no se puede leer:\n'+'\n'.join(failures[:4]))


def prepare_project(board, document=None, project_path=None, root=None, data=None, fabrication=None, cancel=None):
    board = Path(board).resolve()
    if project_path is None and root is None:
        from module_project import from_board
        existing=from_board(board)
        if existing:
            project_path=existing;document=load_project(existing)
    initial_panel_bytes=Path(project_path).read_bytes() if project_path and Path(project_path).exists() else None
    board_bytes = board.read_bytes()
    board_hash = hashlib.sha256(board_bytes).hexdigest()
    data = read_pcb(board) if data is None else copy.deepcopy(data)
    if data.get('source_sha256')!=board_hash: raise ValueError('La PCB cambió durante la preparación; vuelve a cargarla.')
    rules = library_rules()
    if document is not None: rules.update(document.footprint_rules)
    if project_path:
        panel_path = Path(project_path).resolve()
        info = project_info(panel_path)
        previous = info.get('source_board') if info else (document.component_data.get('board_name') if document and document.component_data else None)
        if previous and Path(previous).stem.casefold()!=board.stem.casefold():
            from release_contract import cad_binding
            binding=cad_binding(board)
            known=(info or {}).get('fabrication_association',{}).get('project_id')
            if not binding or not known or binding['project_id']!=known:
                raise ValueError('Es otra PCB. Inicia un módulo nuevo para mantener separados los proyectos.')
        if info and board==local_path(panel_path.parent,info['pcb']) and fabrication is None:
            fabrication=fabrication_source(panel_path)
    else:
        from module_project import cad_project_root
        name = re.sub(r'[^\w.-]+','_',board.stem).strip('._') or 'modulo'
        project_dir = Path(root or cad_project_root(board)/'Sputtering')/name
        panel_path = project_dir/(name+'.panel.json')
        if panel_path.exists():
            raise ValueError('Este módulo ya tiene un proyecto. Abre su archivo .panel.json para continuar sin sustituirlo.')
    selected = discover_fabrication(board,data,rules,fabrication)
    from release_contract import association
    if selected['source'].is_file():selected_association=association(selected['source'])
    else:
        with tempfile.TemporaryDirectory(prefix='pcb-release-') as temp:
            probe=Path(temp)/'source.zip';probe.write_bytes(selected['packed']);selected_association=association(probe)
    if project_path:
        previous_identity=(project_info(panel_path) or {}).get('fabrication_association',{}).get('project_id')
        incoming_identity=selected_association.get('project_id')
        if previous_identity and incoming_identity and previous_identity!=incoming_identity:
            raise ValueError('La liberación pertenece a otra placa (project_id diferente). No se sustituye el módulo.')
        from module_project import validate_source
        validate_source(panel_path,selected_association)
    candidate = copy.deepcopy(document) if document is not None else PanelDocument()
    old_bounds = candidate.reference_bounds()
    if old_bounds and candidate.elements and any(abs(a-b)>.05 for a,b in zip(old_bounds,data['outline_bounds_mm'])):
        raise ValueError('La nueva PCB tiene otro contorno. Inicia un módulo nuevo para no mezclar los objetos existentes.')
    visibility = {Path(r.name).name:r.visible for r in candidate.layers}
    candidate.layers = selected['layers']
    candidate.choose_outline()
    for ref in candidate.layers:
        ref.visible = visibility.get(Path(ref.name).name,ref.coord_format is not None or
            bool(re.search(r'outline|silk.top|\.gto$',ref.name,re.I)))
    if not old_bounds: candidate.center_pcb()
    candidate.component_data, candidate.footprint_rules = data,rules
    if cancel is not None and cancel.is_set():raise ValueError('Lectura cancelada.')
    project_dir = panel_path.parent
    project_dir.mkdir(parents=True,exist_ok=True)
    original = initial_panel_bytes
    if panel_path.exists() and panel_path.read_bytes()!=original:raise ValueError('El frontal cambió durante la lectura; vuelve a importar.')
    if original is not None:
        history = project_dir/'historial'/datetime.now(timezone.utc).strftime('antes_importar_%Y%m%d_%H%M%S_%f')
        history.mkdir(parents=True)
        for name in (panel_path.name,'project.json','REFERENCIAS_ACTUALES.json'):
            path = project_dir/name
            if path.exists(): shutil.copy2(path,history/name)
    package_hash = hashlib.sha256(selected['packed']).hexdigest()
    pcb_rel = f'pcb/{board_hash[:12]}/{board.name}'
    package_rel = f'fabricacion/{package_hash[:12]}/{selected["source"].stem}.zip'
    for relative, raw in {pcb_rel:board_bytes,package_rel:selected['packed']}.items():
        target = local_path(project_dir,relative); target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and target.read_bytes()!=raw: raise ValueError('Una copia local tiene otro contenido: '+relative)
        if not target.exists(): target.write_bytes(raw)
    unpacked = local_path(project_dir,package_rel).parent/'archivos'
    for name,raw in selected['payload'].items():
        target = local_path(unpacked,name);target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists(): target.write_bytes(raw)
        elif target.read_bytes()!=raw: raise ValueError('Archivo local alterado: '+name)
    for kind in ('frontal','serigrafia'): (project_dir/'exports'/kind).mkdir(parents=True,exist_ok=True)
    (project_dir/'assets').mkdir(exist_ok=True)
    atomic_write(project_dir/'components.json',json.dumps(data,ensure_ascii=False,indent=2))
    atomic_write(project_dir/'biblioteca_agujeros.json',json.dumps(dict(schema='sputtering.footprint-hole-rules.v1',rules=rules),ensure_ascii=False,indent=2))
    metadata = dict(schema=SCHEMA,pcb=pcb_rel,pcb_sha256=board_hash,fabrication_zip=package_rel,
        fabrication_sha256=package_hash,fabrication_version=selected['manifest'].get('fabrication_version'),
        fabrication_check=selected['fabrication_check'],
        panel=panel_path.name,components='components.json',exports=dict(frontal='exports/frontal',serigrafia='exports/serigrafia'),
        source_board=str(board),source_fabrication=str(selected['source']),verified_components=selected['verified_components'])
    metadata['fabrication_association']=selected_association
    if hashlib.sha256(board.read_bytes()).hexdigest()!=board_hash: raise ValueError('La PCB cambió durante la copia; no se guarda el proyecto.')
    if cancel is not None and cancel.is_set():raise ValueError('Lectura cancelada.')
    if panel_path.exists() and panel_path.read_bytes()!=original: raise ValueError('El frontal cambió durante la lectura; vuelve a importar para conservar tu edición.')
    candidate.save(panel_path,track=False)
    atomic_write(project_dir/'project.json',json.dumps(metadata,ensure_ascii=False,indent=2))
    atomic_write(project_dir/'REFERENCIAS_ACTUALES.json',json.dumps(dict(source_zip=package_rel,
        fabrication_version=metadata['fabrication_version'],zip_sha256=package_hash),ensure_ascii=False,indent=2))
    atomic_write(project_dir/'ABRIR_PROYECTO.txt',f'Proyecto PCB: {board.stem}\n\n'
        'Para continuar, usa Abrir proyecto y elige modulo.module.json.\n'
        f'Frontal editable: {panel_path.name}.\n'
        'pcb/: copia del circuito original. fabricacion/: paquete comprobado y sus archivos.\n'
        'components.json: posiciones leídas. biblioteca_agujeros.json: reglas de este módulo.\n'
        'serigrafia_pcb/: imagen y ajustes de la PCB. arte_frontal/: imagen y ajustes del panel.\n'
        'exports/serigrafia, exports/frontal y exports/arte_frontal: exportaciones numeradas.\n'
        'versiones/: guardados recuperables desde el menú Módulo.\n'
        'Puedes mover toda esta carpeta: las referencias usadas son locales y relativas.\n')
    from module_project import create,record_save,record_source
    create(project_dir,board.stem,panel_path,board.name)
    record_source(panel_path,local_path(project_dir,package_rel),selected_association)
    from loading_guide import copy_guide
    copy_guide(project_dir)
    record_save(panel_path,'panel')
    return dict(document=candidate,project_path=str(panel_path),data=data,metadata=metadata)
