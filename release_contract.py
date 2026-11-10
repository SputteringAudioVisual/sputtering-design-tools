"""Consumer/derivative implementation of docs/CONTRATO_TRAZABILIDAD_PCB.md.

Kept inside the editor so the standalone app has no runtime dependency on
the Allegro assistant, a workspace checkout or a schema-validation package.
"""
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import re
from types import SimpleNamespace
import uuid
from layer_identity import layer_role
from package_integrity import entry_name,validate_manifest,read_archive,MANUFACTURING

SCHEMA='sputtering.fabrication.v1'
ROLES={'TOP_COPPER':'copper.top','BOTTOM_COPPER':'copper.bottom',
       'TOP_MASK':'soldermask.top','BOTTOM_MASK':'soldermask.bottom',
       'TOP_SILK':'silkscreen.top','BOTTOM_SILK':'silkscreen.bottom',
       'OUTLINE':'profile','DRILL':'drill.plated_and_nonplated','NPTH':'drill.nonplated'}
ALLOWED=set(ROLES.values())|{'drill.plated','route.plated','route.nonplated','report','config','other'}
IDENTITY=('project_id','project_name','pcb_revision','fabrication_release_id','release_label',
          'release_kind','base_fabrication_release_id','parent_release_id','source_board_sha256',
          'provenance_status','release_status')


def sha(raw):return hashlib.sha256(raw).hexdigest()


def _uuid(value,nullable=False):
    if value is None and nullable:return
    try:
        if not isinstance(value,str) or str(uuid.UUID(value))!=value:raise ValueError()
    except (ValueError,AttributeError,TypeError):raise ValueError('Identificador de liberación o placa inválido.')


def _sha(value,nullable=False):
    if value is None and nullable:return
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('SHA-256 de procedencia inválido.')


def classify(name,raw=b''):
    header=SimpleNamespace(raw_lines=raw.decode('utf-8-sig',errors='replace').splitlines(True)[:40])
    role=layer_role(name,header) if Path(name).suffix.lower() in MANUFACTURING else None
    if role=='ROUTE':result='route.plated' if 'plated' in Path(name).stem.lower() and 'nonplated' not in Path(name).stem.lower() else 'route.nonplated'
    elif role in ROLES:result=ROLES[role]
    elif name.startswith(('informes/','historial_editor/')) or Path(name).suffix.lower() in {'.log','.md'} or Path(name).name=='LEEME_FABRICACION.txt':result='report'
    elif name.startswith('parametros/') or Path(name).suffix.lower() in {'.json','.il','.txt'}:result='config'
    else:result='other'
    layer='TOP' if result.endswith('.top') else 'BOTTOM' if result.endswith('.bottom') else None
    return result,layer


def validate_release(manifest,payload=None):
    schema=manifest.get('schema')
    if schema!=SCHEMA:
        if isinstance(schema,str) and schema.startswith('sputtering.fabrication.'):
            raise ValueError('Versión de manifiesto de fabricación no admitida.')
        return False
    required=set(IDENTITY)|{'schema','parent_archive_sha256','parent_manifest_sha256','created_utc','tools','profile','files'}
    if not required.issubset(manifest):raise ValueError('Faltan campos de trazabilidad de la liberación.')
    m=manifest
    for key in ('project_id','base_fabrication_release_id','parent_release_id','module_id'):
        _uuid(m.get(key),True)
    _uuid(m['fabrication_release_id'])
    for key in ('parent_archive_sha256','parent_manifest_sha256','source_board_sha256'):_sha(m[key],True)
    if m['project_name'] is not None and (not isinstance(m['project_name'],str) or not m['project_name'].strip()):raise ValueError('Nombre de placa inválido.')
    if m['pcb_revision'] is not None and (not isinstance(m['pcb_revision'],str) or not re.fullmatch(r'[1-9][0-9]*\.(0|[1-9][0-9]*)',m['pcb_revision'])):
        raise ValueError('Revisión PCB inválida; se requiere MAYOR.MENOR.')
    if m['release_status'] not in {'pending_cam_review','pending_cam_review_with_warnings'}:raise ValueError('Estado de liberación inválido.')
    if m['provenance_status'] not in {'verified','incomplete'}:raise ValueError('Estado de procedencia inválido.')
    try:
        date=datetime.fromisoformat(m['created_utc'].replace('Z','+00:00'))
        if date.utcoffset() is None or date.utcoffset().total_seconds()!=0:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise ValueError('Fecha de liberación inválida; se requiere UTC.')
    if m.get('source_saved_board_sha256') is not None:
        _sha(m['source_saved_board_sha256'])
        try:
            observed=datetime.fromisoformat(m['source_saved_board_observed_utc'].replace('Z','+00:00'))
            if observed.utcoffset() is None or observed.utcoffset().total_seconds()!=0 or m.get('source_saved_board_observation')!='export_requested':raise ValueError()
        except (KeyError,ValueError,TypeError,AttributeError):raise ValueError('La observación del BRD guardado no está declarada correctamente.')
    if not isinstance(m['profile'],dict) or not isinstance(m['tools'],list) or not m['tools']:raise ValueError('Falta perfil o herramientas de fabricación.')
    for tool in m['tools']:
        if not isinstance(tool,dict) or not isinstance(tool.get('name'),str) or not tool['name'].strip() or 'version' not in tool or (tool['version'] is not None and not isinstance(tool['version'],str)):
            raise ValueError('Herramienta de fabricación inválida.')
    kind=m['release_kind']
    if kind not in {'allegro_original','gerber_derived'}:raise ValueError('Productor de liberación desconocido.')
    sequence=m.get('fabrication_sequence' if kind=='allegro_original' else 'fabrication_edit_sequence')
    prefix='F' if kind=='allegro_original' else 'E'
    if type(sequence) is not int or sequence<1 or m['release_label']!=f'{prefix}{sequence:03d}':raise ValueError('Etiqueta y secuencia de liberación incoherentes.')
    if kind=='allegro_original':
        if m['base_fabrication_release_id']!=m['fabrication_release_id'] or any(m[k] is not None for k in ('parent_release_id','parent_archive_sha256','parent_manifest_sha256')):
            raise ValueError('Liberación original con raíz o padre incoherentes.')
        source=m.get('source_board')
        if not isinstance(source,dict) or not all(k in source for k in ('project_relative_path','sha256','bytes')):raise ValueError('Falta copia BRD de origen.')
        entry_name({'path':source['project_relative_path']});_sha(source['sha256'])
        if type(source['bytes']) is not int or source['bytes']<0 or source['sha256']!=m['source_board_sha256']:raise ValueError('Copia BRD y hash de origen discrepantes.')
        if m['provenance_status']!='verified':raise ValueError('Una liberación original debe declarar su procedencia verificada.')
    else:
        _sha(m['parent_archive_sha256'])
        if m['fabrication_release_id'] in {m['parent_release_id'],m['base_fabrication_release_id']}:raise ValueError('Una edición debe tener un ID propio.')
    if m['provenance_status']=='verified' and any(m.get(k) is None for k in ('project_id','project_name','pcb_revision','base_fabrication_release_id','source_board_sha256')):
        raise ValueError('La procedencia verificada requiere identidad y revisión de placa.')
    if kind=='gerber_derived' and m['provenance_status']=='verified' and any(m[k] is None for k in ('parent_release_id','parent_manifest_sha256')):
        raise ValueError('La edición verificada requiere el padre exacto.')
    if not isinstance(m['files'],list) or not m['files']:raise ValueError('Inventario de liberación vacío.')
    for item in m['files']:
        name=entry_name(item)
        if any(k not in item for k in ('path','name','role','layer')) or item['role'] not in ALLOWED:raise ValueError('Función de archivo no declarada: '+name)
        expected='TOP' if item['role'].endswith('.top') else 'BOTTOM' if item['role'].endswith('.bottom') else None
        if item['layer']!=expected:raise ValueError('Función y cara discrepantes: '+name)
        if payload is not None:
            actual,_=classify(name,payload.get(name,b''))
            if actual not in {'report','config','other'} and actual!=item['role']:
                if not (actual.startswith('drill.') and item['role'].startswith('drill.')):
                    raise ValueError('Contenido y función de capa discrepantes: '+name)
    if payload is not None:validate_manifest(payload,m,True)
    return True


def inventory(payload,previous=None):
    declarations={entry_name(e):e for e in (previous or {}).get('files',[])}
    result=[]
    for name,raw in sorted(payload.items()):
        if name=='manifest.json':continue
        role,layer=classify(name,raw)
        declared=declarations.get(name,{})
        if declared.get('role') in ALLOWED:role=declared['role'];layer=declared.get('layer')
        result.append(dict(path=name,name=name,bytes=len(raw),sha256=sha(raw),role=role,layer=layer))
    return result


def derivative(parent,parent_archive_sha256,parent_manifest_bytes,sequence,profile,module_id=None):
    known=parent if validate_release(parent) else {}
    verified=known.get('provenance_status')=='verified'
    warning=not verified or known.get('release_status')=='pending_cam_review_with_warnings'
    result=dict(schema=SCHEMA,project_id=known.get('project_id'),project_name=known.get('project_name'),
        pcb_revision=known.get('pcb_revision'),fabrication_release_id=str(uuid.uuid4()),release_kind='gerber_derived',
        release_label=f'E{sequence:03d}',fabrication_edit_sequence=sequence,
        base_fabrication_release_id=known.get('base_fabrication_release_id'),parent_release_id=known.get('fabrication_release_id'),
        parent_archive_sha256=parent_archive_sha256,parent_manifest_sha256=sha(parent_manifest_bytes) if parent_manifest_bytes is not None else None,
        source_board_sha256=known.get('source_board_sha256'),created_utc=datetime.now(timezone.utc).isoformat(),
        tools=[dict(name='Sputtering Design Tools · Gerber editor',version=None)],profile=profile,
        release_status='pending_cam_review_with_warnings' if warning else 'pending_cam_review',
        provenance_status='verified' if verified else 'incomplete')
    group=known.get('module_id') or module_id
    if group:result['module_id']=group
    if known.get('source_board'):result['source_board']=known['source_board']
    for key in ('source_saved_board_sha256','source_saved_board_observed_utc','source_saved_board_observation'):
        if key in known:result[key]=known[key]
    if parent.get('example_only') is True:result['example_only']=True
    result['base_archive_sha256']=known.get('base_archive_sha256') or parent_archive_sha256
    return result


def association(path):
    raw=Path(path).read_bytes()
    payload,m=read_archive(io.BytesIO(raw));known=validate_release(m,payload)
    result={key:m.get(key) if known else None for key in IDENTITY}
    result.update(archive_sha256=sha(raw),manifest_sha256=sha(payload['manifest.json']) if 'manifest.json' in payload else None,
                  provenance_status=m['provenance_status'] if known else 'incomplete',legacy=not known)
    if known and m.get('source_saved_board_sha256'):result['source_saved_board_sha256']=m['source_saved_board_sha256']
    return result


def compare_packages(before,after):
    a,_=read_archive(before);b,_=read_archive(after)
    a={k:sha(v) for k,v in a.items() if k!='manifest.json'};b={k:sha(v) for k,v in b.items() if k!='manifest.json'}
    return dict(added=sorted(b.keys()-a.keys()),removed=sorted(a.keys()-b.keys()),
                changed=sorted(k for k in a.keys()&b.keys() if a[k]!=b[k]),
                unchanged=sum(a[k]==b[k] for k in a.keys()&b.keys()))


def cad_binding(board):
    from module_project import cad_project_root,local
    board=Path(board).resolve();link=board.parent/'Asistente'/board.stem/'identidad_pcb.json'
    if not link.exists():return None
    binding=json.loads(link.read_text(encoding='utf-8'));_uuid(binding.get('project_id'))
    registry=json.loads(local(cad_project_root(board),binding['project_relative_path']).read_text(encoding='utf-8'))
    if registry.get('schema')!='sputtering.pcb-identity.v1' or registry.get('project_id')!=binding['project_id'] or binding.get('pcb_revision') not in registry.get('revisions',{}):
        raise ValueError('El vínculo de identidad PCB de Allegro no coincide con su registro.')
    return binding


def _cad_freshness(value,cad_root):
    from module_project import local
    index=Path(cad_root)/'Sputtering'/'pcb'/value['project_id']/'project.json'
    if not index.exists():return None
    registry=json.loads(index.read_text(encoding='utf-8'))
    if registry.get('schema')!='sputtering.pcb-identity.v1' or registry.get('project_id')!=value['project_id']:raise ValueError('El registro de Allegro mezcla identidades de placa.')
    revision=registry.get('latest_declared_revision')
    if revision and revision!=value['pcb_revision']:return 'Desfasado: Allegro declara PCB '+revision
    releases=[]
    for path in (index.parent/'releases').glob('*/release.json'):
        entry=json.loads(path.read_text(encoding='utf-8'))
        if entry.get('project_id')!=value['project_id']:raise ValueError('El índice de Allegro mezcla liberaciones de otra placa.')
        if type(entry.get('fabrication_sequence')) is int:releases.append(entry)
    if releases:
        latest=max(releases,key=lambda e:e['fabrication_sequence'])
        if latest.get('fabrication_release_id')!=value['base_fabrication_release_id']:
            return 'Liberación de origen anterior: Allegro tiene '+str(latest.get('release_label','otra F'))
    return None


def freshness(value,module_root=None,cad_root=None):
    if value.get('legacy'):return 'Histórico: identidad y revisión PCB sin declarar'
    if value.get('provenance_status')!='verified':return 'Procedencia incompleta · memoria de Allegro sin comprobar'
    if module_root and cad_root is None:
        from module_project import cad_project_root
        folder=Path(module_root)
        if folder.parent.name=='Sputtering':cad_root=cad_project_root(folder.parent.parent/'board.brd')
    if cad_root:
        try:
            state=_cad_freshness(value,cad_root)
            if state:return state
        except (OSError,ValueError,KeyError) as error:return 'Vigencia sin comprobar: '+str(error)
    if module_root:
        meta_path=Path(module_root)/'project.json'
        if meta_path.exists():
            meta=json.loads(meta_path.read_text(encoding='utf-8'))
            current=meta.get('fabrication_association') or {}
            if current.get('project_id') and current['project_id']!=value.get('project_id'):
                return 'Otra placa asociada en el módulo'
            if current.get('pcb_revision') and current['pcb_revision']!=value.get('pcb_revision'):
                return 'Desfasado: el módulo está asociado a PCB '+current['pcb_revision']
            expected=value.get('source_saved_board_sha256')
            original=Path(meta.get('source_board',''))
            if expected and original.is_file():
                if sha(original.read_bytes())!=expected:return 'Desfasado: BRD guardado cambiado desde la exportación'
                return 'Sin cambios detectados en disco · memoria de Allegro sin comprobar'
            if current.get('base_fabrication_release_id') and current['base_fabrication_release_id']!=value.get('base_fabrication_release_id'):
                return 'Liberación de origen diferente de la asociada al módulo'
    return 'Paquete comprobado · estado actual de Allegro sin comprobar'


def caption(value,module_root=None,cad_root=None):
    name=value.get('project_name') or 'Placa sin identidad declarada'
    revision=value.get('pcb_revision') or 'sin declarar'
    label=value.get('release_label') or 'histórica'
    return f"{name} · PCB {revision} · Liberación {label} · {freshness(value,module_root,cad_root)}"
