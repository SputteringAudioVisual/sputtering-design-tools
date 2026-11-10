"""One portable module, with immutable editing revisions and linked outputs."""
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time
import uuid
import re

INDEX='modulo.module.json'
SCHEMA='sputtering.module.v1'
STAGES={'panel':'Frontal','pcb_silkscreen':'Serigrafía PCB','panel_artwork':'Imagen del frontal'}
DEFAULTS={'panel':'frontal.panel.json','pcb_silkscreen':'serigrafia_pcb/pcb.silk.json',
          'panel_artwork':'arte_frontal/frontal.silk.json'}
OUTPUTS={'panel':'exports/frontal','pcb_silkscreen':'exports/serigrafia',
         'panel_artwork':'exports/arte_frontal'}


def cad_project_root(board):
    """Use the enclosing Capture/Allegro project, without moving CAD files."""
    folder=Path(board).resolve().parent
    for ancestor in (folder,*list(folder.parents)[:2]):
        if ancestor.name.casefold()=='allegro':return ancestor.parent
    if folder.name.casefold() in {'fabricacion','fabricación','fabrication','gerbers'}:return folder.parent
    return folder


def digest(raw):return hashlib.sha256(raw).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()


def document_json(value):
    # Loading a JSON document normalises e.g. 0 to 0.0 in the geometry model.
    # That is not a design revision. Use a stable representation on every save.
    def normalise(v):
        if isinstance(v,float) and v.is_integer():return int(v)
        if isinstance(v,dict):return {k:normalise(x) for k,x in v.items()}
        if isinstance(v,(list,tuple)):return [normalise(x) for x in v]
        return v
    return json.dumps(normalise(value),ensure_ascii=False,indent=2,sort_keys=True)


def local(root,name):
    root=Path(root).resolve();path=(root/name).resolve()
    if not path.is_relative_to(root):raise ValueError('Referencia fuera de la carpeta del módulo.')
    return path


def find_root(path):
    if not path:return None
    path=Path(path).resolve()
    start=path if path.is_dir() else path.parent
    for root in (start,*start.parents):
        if (root/INDEX).is_file():return root
    return None


def read(root):
    root=Path(root);data=json.loads((root/INDEX).read_text(encoding='utf-8'))
    if data.get('schema')!=SCHEMA:raise ValueError('Proyecto de módulo no reconocido.')
    for entry in data['stages'].values():
        if entry.get('project'):local(root,entry['project'])
    return data


@contextmanager
def locked(root):
    # OS locks are released even if an editor crashes. The persistent byte is
    # not a stale lock flag. Both application processes share this transaction.
    path=Path(root)/'.module.lock'
    with path.open('a+b') as stream:
        stream.seek(0,2)
        if not stream.tell():stream.write(b'0');stream.flush()
        deadline=time.monotonic()+8
        if __import__('os').name=='nt':
            import msvcrt
            def lock():stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            def unlock():stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            def lock():fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            def unlock():fcntl.flock(stream,fcntl.LOCK_UN)
        while True:
            try:lock();break
            except OSError:
                if time.monotonic()>deadline:raise ValueError('Otra ventana está guardando el módulo. Vuelve a guardar en unos segundos.')
                time.sleep(.05)
        try:yield
        finally:unlock()


def write(root,data):
    from panel_model import atomic_write
    atomic_write(Path(root)/INDEX,json.dumps(data,ensure_ascii=False,indent=2))


def create(root,name,panel=None,board_name=None):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    with locked(root):
        if (root/INDEX).exists():return read(root)
        data=dict(schema=SCHEMA,id=str(uuid.uuid4()),name=name,created_utc=now(),
                  source_board_name=board_name,stages={},artifacts=[])
        for stage,path in DEFAULTS.items():
            if stage=='panel' and panel:path=Path(panel).resolve().relative_to(root).as_posix()
            data['stages'][stage]=dict(project=path,revision=0,exports=OUTPUTS[stage])
        write(root,data)
    return data


def stage_for(path,data=None):
    root=find_root(path)
    if root is None:return None
    data=data or read(root);relative=Path(path).resolve().relative_to(root).as_posix()
    for stage,entry in data['stages'].items():
        if entry.get('project')==relative:return stage
    return 'panel' if relative.endswith('.panel.json') else 'panel_artwork' if 'arte_frontal' in relative.split('/') else 'pcb_silkscreen'


def stage_path(root,stage):return local(root,read(root)['stages'][stage]['project'])


def destination(path,kind=None):
    root=find_root(path)
    if root is None:return None
    data=read(root);stage=stage_for(path,data)
    if kind=='frontal':stage='panel'
    folder=local(root,data['stages'][stage]['exports']);folder.mkdir(parents=True,exist_ok=True)
    return folder


def reserve_output(project,output):
    """An explicitly requested external copy keeps its filename; module
    outputs always receive an unused version, including individual layers."""
    root=find_root(project);output=Path(output).resolve()
    if root is None or not output.is_relative_to(root):return output,False
    stem=re.sub(r'_v\d+$','',output.stem)
    for number in range(1,10000):
        candidate=output.with_name(f'{stem}_v{number:03d}'+output.suffix)
        try:
            with candidate.open('xb'):pass
            return candidate,True
        except FileExistsError:continue
    raise ValueError('No queda un número libre para esta exportación.')


def _document_files(path,root):
    """Editable JSON and its real local dependencies, never provenance paths."""
    raw=Path(path).read_bytes();data=json.loads(raw)
    files={Path(path).resolve().relative_to(root).as_posix():raw}
    state=data.get('image_session',data if data.get('schema')=='sputtering.image-session.v1' else {})
    names=[state.get('image'),state.get('svg'),data.get('fabrication_zip')]
    for name in names:
        if name:
            item=local(Path(path).parent,name)
            if not item.is_relative_to(root):raise ValueError('Recurso fuera del módulo.')
            files[item.relative_to(root).as_posix()]=item.read_bytes()
    if data.get('schema')=='sputtering.front-panel.v1' and (Path(path).parent/'project.json').exists():
        meta_path=Path(path).parent/'project.json';meta=json.loads(meta_path.read_text(encoding='utf-8'))
        files[meta_path.relative_to(root).as_posix()]=meta_path.read_bytes()
        for key in ('pcb','fabrication_zip','components'):
            dep=local(meta_path.parent,meta[key]);files[dep.relative_to(root).as_posix()]=dep.read_bytes()
    return files


def record_save(path,stage=None):
    root=find_root(path)
    if root is None:return None
    path=Path(path).resolve();files=_document_files(path,root)
    hashes={name:digest(raw) for name,raw in sorted(files.items())}
    fingerprint=digest(json.dumps(hashes,sort_keys=True).encode())
    with locked(root):
        data=read(root);stage=stage or stage_for(path,data);entry=data['stages'][stage]
        if entry.get('fingerprint')==fingerprint:return dict(stage=stage,revision=entry['revision'],sha256=hashes[path.relative_to(root).as_posix()])
        revision=entry['revision']+1
        folder=root/'versiones'/stage/f'v{revision:04d}'
        while folder.exists():revision+=1;folder=root/'versiones'/stage/f'v{revision:04d}'
        folder.mkdir(parents=True,exist_ok=False)
        # JSON documents are small enough to snapshot. Hash-addressed binary
        # inputs remain immutable in the module, shared by all revisions.
        snapshots={}
        for name,raw in files.items():
            if name.endswith('.json'):
                target=folder/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
                snapshots[name]=target.relative_to(root).as_posix()
        record=dict(stage=stage,revision=revision,created_utc=now(),project=path.relative_to(root).as_posix(),
                    sha256=hashes[path.relative_to(root).as_posix()],files=hashes,snapshots=snapshots,
                    previous=entry.get('checkpoint'))
        from panel_model import atomic_write
        checkpoint=folder/'revision.json';atomic_write(checkpoint,json.dumps(record,ensure_ascii=False,indent=2))
        entry.update(project=record['project'],revision=revision,fingerprint=fingerprint,
                     checkpoint=checkpoint.relative_to(root).as_posix(),sha256=record['sha256'])
        write(root,data)
        return dict(stage=stage,revision=revision,sha256=record['sha256'])


def lineage(path):
    root=find_root(path)
    if root is None:return None
    data=read(root);stage=stage_for(path,data);entry=data['stages'][stage]
    return dict(module_id=data['id'],module_name=data['name'],stage=stage,project=entry['project'],revision=entry['revision'],
                project_sha256=entry.get('sha256'),checkpoint=entry.get('checkpoint'))


def record_output(project,output,source=None,details=None):
    root=find_root(project)
    if root is None:return None
    output=Path(output).resolve();relative=output.relative_to(root).as_posix()
    value=dict(path=relative,sha256=digest(output.read_bytes()),created_utc=now(),
               lineage=lineage(project),details=details or {})
    if output.suffix.lower()=='.zip':
        from release_contract import association
        value['fabrication_association']=association(output)
    if source:
        source=Path(source).resolve()
        if not source.is_relative_to(root):raise ValueError('El origen de exportación está fuera del módulo.')
        value['source']=dict(path=source.relative_to(root).as_posix(),sha256=digest(source.read_bytes()))
    with locked(root):
        data=read(root)
        _check_release_identity(data,value.get('fabrication_association'))
        for prior in data['artifacts']:
            if prior['path']==relative:
                if prior['sha256']!=value['sha256']:raise ValueError('Una exportación registrada ha cambiado.')
                return prior
        data['artifacts'].append(value);write(root,data)
    return value


def _check_release_identity(data,association):
    if not association or not association.get('fabrication_release_id'):return
    for item in data.get('fabrication_sources',[])+data.get('artifacts',[]):
        prior=item.get('fabrication_association') or {}
        if prior.get('fabrication_release_id')==association['fabrication_release_id'] and prior.get('archive_sha256')!=association['archive_sha256']:
            raise ValueError('El ID de una liberación sellada se ha reutilizado con otro ZIP.')


def validate_source(project,association):
    root=find_root(project)
    if root is not None:
        with locked(root):_check_release_identity(read(root),association)


def record_source(project,source,association):
    root=find_root(project)
    if root is None:return
    path=Path(source).resolve().relative_to(root).as_posix()
    with locked(root):
        data=read(root);_check_release_identity(data,association)
        records=data.setdefault('fabrication_sources',[])
        if any(r['fabrication_association']['archive_sha256']==association['archive_sha256'] for r in records):return
        records.append(dict(path=path,fabrication_association=association));write(root,data)


def adopt_package(package):
    """Opening an original package exported by this module resumes its stage."""
    root=find_root(package)
    if root is None:return None
    relative=Path(package).resolve().relative_to(root).as_posix()
    data=read(root)
    for item in data['artifacts']:
        if item['path']!=relative:continue
        stage=(item.get('lineage') or {}).get('stage')
        if stage=='panel':return continue_panel_artwork(stage_path(root,'panel'),package)
        if stage in ('panel_artwork','pcb_silkscreen'):
            path=stage_path(root,stage)
            if path.exists():return path
    return None


def verify(root):
    """Check portability and the hashes of every registered revision/output."""
    root=Path(root).resolve();data=read(root);checked=set()
    for source in data.get('fabrication_sources',[]):
        from release_contract import association
        if association(local(root,source['path']))!=source['fabrication_association']:
            raise ValueError('La asociación de liberación de origen ha cambiado.')
    for stage,entry in data['stages'].items():
        if not entry.get('checkpoint'):continue
        if digest(local(root,entry['project']).read_bytes())!=entry['sha256']:
            raise ValueError('El proyecto actual no coincide con su revisión: '+entry['project'])
        checkpoint=local(root,entry['checkpoint'])
        while checkpoint:
            record=json.loads(checkpoint.read_text(encoding='utf-8'))
            for name,expected in record['files'].items():
                item=local(root,record['snapshots'].get(name,name))
                pair=(str(item),expected)
                if pair in checked:continue
                if digest(item.read_bytes())!=expected:raise ValueError('Revisión alterada: '+name)
                checked.add(pair)
            checkpoint=local(root,record['previous']) if record.get('previous') else None
    for item in data['artifacts']:
        if digest(local(root,item['path']).read_bytes())!=item['sha256']:raise ValueError('Exportación alterada: '+item['path'])
        if item.get('source') and digest(local(root,item['source']['path']).read_bytes())!=item['source']['sha256']:
            raise ValueError('Origen de exportación alterado.')
    return dict(revisions_files=len(checked),artifacts=len(data['artifacts']))


def last_panel_package(panel):
    root=find_root(panel)
    if root is None:return None
    sha=digest(Path(panel).read_bytes())
    for item in reversed(read(root)['artifacts']):
        source=item.get('lineage') or {}
        if source.get('stage')=='panel' and source.get('project_sha256')==sha and item['path'].lower().endswith('.zip'):
            path=local(root,item['path'])
            if digest(path.read_bytes())!=item['sha256']:raise ValueError('La exportación del frontal ha cambiado.')
            return path
    return None


def revisions(root):
    records=[]
    for entry in read(root)['stages'].values():
        path=entry.get('checkpoint')
        while path:
            record=json.loads(local(root,path).read_text(encoding='utf-8'))
            records.append(dict(record,checkpoint=path));path=record.get('previous')
    return sorted(records,key=lambda r:r['created_utc'],reverse=True)


def restore_revision(root,checkpoint):
    """Restore JSON documents; referenced binary inputs remain pinned in root."""
    root=Path(root).resolve()
    record=next((r for r in revisions(root) if r['checkpoint']==checkpoint),None)
    if record is None:raise ValueError('Revisión no registrada en el módulo.')
    restored={}
    for name,sha in record['files'].items():
        source=local(root,record['snapshots'].get(name,name));raw=source.read_bytes()
        if digest(raw)!=sha:raise ValueError('No se puede restaurar: recurso alterado '+name)
        if name in record['snapshots']:restored[local(root,name)]=raw
    from panel_model import atomic_write
    with locked(root):
        previous={path:path.read_bytes() if path.exists() else None for path in restored}
        try:
            for path,raw in restored.items():atomic_write(path,raw.decode('utf-8'))
        except OSError:
            for path,raw in previous.items():
                if raw is not None:atomic_write(path,raw.decode('utf-8'))
            raise
    project=local(root,record['project']);record_save(project,record['stage'])
    return project


def continue_panel_artwork(panel,package):
    """Keep one artwork editor, pinning the exact newly exported front panel."""
    root=find_root(panel)
    if root is None:
        create(Path(panel).parent,Path(panel).name.removesuffix('.panel.json'),panel)
        root=find_root(panel)
    path=stage_path(root,'panel_artwork');path.parent.mkdir(parents=True,exist_ok=True)
    from panel_model import load_references,geometry_bounds
    from layer_identity import layer_role
    from silkscreen_project import load,save
    refs,errors=load_references([package])
    if errors:raise ValueError('; '.join(errors))
    state=dict(schema='sputtering.image-session.v1',enabled=False);views={};view={}
    if path.exists():
        old,state,views,_,view=load(path)
        def bounds(items):return geometry_bounds(next(r.layer for r in items if layer_role(r.name,r.layer)=='OUTLINE'),outline=True)
        if bounds(old)!=bounds(refs):raise ValueError('El tamaño del frontal ha cambiado. Conserva una variante antes de adaptar su imagen.')
        state={k:v for k,v in state.items() if not k.startswith('_')}
    save(path,refs,state,views,package,view)
    return path


def module_panel(path):
    root=find_root(path)
    return stage_path(root,'panel') if root else None


def from_board(board):
    board=Path(board).resolve()
    from release_contract import cad_binding
    binding=cad_binding(board)
    # Keep existing modules beside the BRD compatible with the shared CAD root.
    folders={cad_project_root(board)/'Sputtering',board.parent/'Sputtering'}
    matches=[]
    for folder in sorted(folders):
        if not folder.is_dir():continue
        for index in folder.glob('*/'+INDEX):
            data=read(index.parent)
            metadata=index.parent/'project.json'
            identity=(json.loads(metadata.read_text(encoding='utf-8')).get('fabrication_association') or {}).get('project_id') if metadata.exists() else None
            if binding and identity:
                matched=identity==binding['project_id']
            else:matched=(data.get('source_board_name') or '').casefold()==board.name.casefold()
            if matched:matches.append(stage_path(index.parent,'panel'))
    if len(matches)>1:raise ValueError('Hay varios módulos para esta PCB. Abre el proyecto que quieras continuar.')
    return matches[0] if matches else None
