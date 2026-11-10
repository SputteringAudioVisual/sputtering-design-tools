"""Portable editable silkscreen projects, also when starting from a loose ZIP."""
import hashlib
import json
from pathlib import Path
import re
from PIL import Image
from image_tuning import validate_tuning
from pcb_project import local_path
from panel_model import Reference,atomic_write,number

SCHEMA='sputtering.silkscreen-project.v1'
ALGORITHMS={'threshold','floyd','floyd_fast','atkinson','bayer2','bayer4','bayer8','clustered4','stucki','jarvis'}

def read_session(root,state):
    state=dict(state)
    if state.get('schema')!='sputtering.image-session.v1':raise ValueError('Sesión de imagen desconocida.')
    for recipe in state.get('preferences',{}).values():
        if recipe.get('window_shape','rectangle') not in ('rectangle','contour'):
            raise ValueError('Forma de ventana desconocida en el proyecto.')
    if not state.get('enabled'):return state
    for key in ('x_mm','y_mm','width_mm','height_mm','angle_deg'):state[key]=number(state[key])
    if state['width_mm']<=0 or state['height_mm']<=0:raise ValueError('Tamaño de imagen inválido.')
    if state['algorithm'] not in ALGORITHMS:raise ValueError('Conversión desconocida.')
    state['threshold']=int(number(state['threshold'],0,255))
    state['contrast']=number(state['contrast'],.3,3)
    state['pixel_mm']=number(state['pixel_mm'],.15,100)
    state['dot_mm']=number(state['dot_mm'],.15,100)
    state['tuning']=validate_tuning(state.get('tuning'))
    image=local_path(root,state['image'])
    with Image.open(image) as source:state['_image']=source.copy()
    state['_image_path']=str(image)
    state['_svg_path']=str(local_path(root,state['svg'])) if state.get('svg') else None
    if state['_svg_path'] and not Path(state['_svg_path']).is_file():raise ValueError('Falta el SVG del proyecto.')
    return state

def save(path,references,state,views,source_zip=None,view=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    data=dict(schema=SCHEMA,layers=[r.serialise() for r in references],image_session=state,
              layer_views=views,view=view or {})
    if source_zip:
        source=Path(source_zip);raw=source.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        original_name=re.sub(r'^(?:[0-9a-f]{16}_)+','',source.name)
        relative='fabricacion/'+digest[:16]+'_'+original_name
        target=local_path(path.parent,relative);target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if target.read_bytes()!=raw:raise ValueError('La copia local de fabricación ha cambiado.')
        else:
            with target.open('xb') as stream:stream.write(raw)
        data.update(fabrication_zip=relative,fabrication_sha256=digest)
        from release_contract import association
        data['fabrication_association']=association(target)
        from module_project import record_source
        record_source(path,target,data['fabrication_association'])
    from module_project import record_save,document_json
    atomic_write(path,document_json(data))
    record_save(path)
    return local_path(path.parent,data['fabrication_zip']) if source_zip else None

def load(path):
    path=Path(path);data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema')!=SCHEMA:raise ValueError('No es un proyecto de serigrafía.')
    refs=[Reference(**r) for r in data['layers']]
    if len({r.name for r in refs})!=len(refs):raise ValueError('El proyecto contiene capas duplicadas.')
    views=data.get('layer_views',{})
    for value in views.values():
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',value['color']):raise ValueError('Color de capa inválido.')
    source=local_path(path.parent,data['fabrication_zip']) if data.get('fabrication_zip') else None
    if source and hashlib.sha256(source.read_bytes()).hexdigest()!=data['fabrication_sha256']:
        raise ValueError('El ZIP local de fabricación ha cambiado.')
    if source:
        from release_contract import association
        current=association(source)
        if data.get('fabrication_association') and data['fabrication_association']!=current:
            raise ValueError('La asociación de liberación no coincide con el paquete guardado.')
    state=read_session(path.parent,data['image_session'])
    view=data.get('view',{})
    for key in ('zoom','pan_x','pan_y'):
        if key in view:view[key]=number(view[key],.001 if key=='zoom' else None)
    return refs,state,views,source,view
