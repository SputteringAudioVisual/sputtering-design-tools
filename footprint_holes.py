"""Read-only Allegro placement extraction and mechanical hole proposals.

Anchors use actual board pin coordinates, so rotation and mirroring are already
accounted for by Allegro. No centroid of electrical pads is guessed.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

SCHEMA = 'sputtering.pcb-components.v1'
DEFAULT_RULES = {
    'SPTR_RK09_123': dict(hole_type='potentiometer', diameter_mm=8.128,
                         anchor='mechanical_pair', value='', side='TOP'),
    'SPTR_PJ301M': dict(hole_type='jack', diameter_mm=6.1,
                      anchor='padstack', value='C150_H300', side='TOP'),
    'SPTR_SPDT': dict(hole_type='spdt', diameter_mm=6.5,
                     anchor='pin', value='2', side='TOP'),
}
# Exact library names, with mechanical anchors checked against the .dra assets.
for _name in ('SPTR_RK09_321','SPTR_RK09_DOBLE','RK09_123','RK09_321'):
    DEFAULT_RULES[_name] = dict(DEFAULT_RULES['SPTR_RK09_123'])
DEFAULT_RULES['RK09D1130C1B'] = dict(hole_type='potentiometer',diameter_mm=8.128,
                                  anchor='pin_pair',value='MH1,MH2',side='TOP')
DEFAULT_RULES['PJ301M'] = dict(DEFAULT_RULES['SPTR_PJ301M'])
for _name in ('SPTR_MINISPDT','SPTR_SWITCHER_3POLOS','SPTR_TOOGLE_SWITCH_3POLOS'):
    DEFAULT_RULES[_name] = dict(DEFAULT_RULES['SPTR_SPDT'],review_required=True)
for _name in ('SPTR_DPDT','SPTR_SWITCHER_6POLES'):
    DEFAULT_RULES[_name] = dict(hole_type='dpdt',diameter_mm=6.5,anchor='pin_pair',
                              value='2,5',side='TOP',review_required=True)
ANCHORS = {'mechanical_pair', 'padstack', 'pin', 'pin_pair', 'origin'}
ANCHOR_HINTS = {
    'SPTR_LED_5MM':dict(anchor='pin_pair',value='1,2'),
    'SPTR_PUSHBUTTON':dict(anchor='pin_pair',value='1,2'),
}


def shared_library_path():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.config')))/'SputteringDesignTools'/'footprint-hole-rules.json'


def library_rules(path=None):
    rules=copy.deepcopy(DEFAULT_RULES);path=Path(path) if path is not None else shared_library_path()
    if path.exists():
        if path.stat().st_size>2_000_000:raise ValueError('La biblioteca común supera 2 MB.')
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        if data.get('schema')!='sputtering.footprint-hole-rules.v1':raise ValueError('Biblioteca común no reconocida.')
        rules.update(validate_rules(data['rules']))
    return rules


def save_shared_library(rules,path=None):
    from panel_model import atomic_write
    rules=validate_rules(rules);path=Path(path) if path is not None else shared_library_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    atomic_write(path,json.dumps(dict(schema='sputtering.footprint-hole-rules.v1',rules=rules),ensure_ascii=False,indent=2))


def library_coverage(data,rules):
    rows={};rules=validate_rules(rules)
    for c in validate_data(data)['components']:
        name=c['footprint'];row=rows.setdefault(name,dict(footprint=name,count=0,ready=0,review=0,problems=[]))
        row['count']+=1;rule=rules.get(name)
        if rule is None:
            row['problems'].append('Centro de referencia disponible; falta definir diámetro/corte' if name in ANCHOR_HINTS else 'Sin regla')
            continue
        if rule['side'] not in ('BOTH',c['side']):row['problems'].append('Otra cara');continue
        try:anchor_point(c,rule)
        except ValueError as error:row['problems'].append(str(error));continue
        row['ready']+=1
        if rule.get('review_required'):row['review']+=1
    return list(rows.values())
QUERIES = {
    'components': 'COMPONENT\nREFDES\nCOMP_PACKAGE\nSYM_X\nSYM_Y\nSYM_ROTATE\nSYM_MIRROR\nEND\n',
    'pins': 'COMPOSITE_PAD\nCLASS!="VIA CLASS"\nREFDES\nPIN_NUMBER\nPAD_STACK_NAME\nPIN_X\nPIN_Y\nEND\n',
    'outline': 'FULL_GEOMETRY\nCLASS="BOARD GEOMETRY"\nSUBCLASS="DESIGN_OUTLINE"\nOR\nCLASS="BOARD GEOMETRY"\nSUBCLASS="OUTLINE"\nGRAPHIC_DATA_NAME\nGRAPHIC_DATA_1\nGRAPHIC_DATA_2\nGRAPHIC_DATA_3\nGRAPHIC_DATA_4\nGRAPHIC_DATA_5\nGRAPHIC_DATA_6\nEND\n',
}


def finite(value):
    result = float(str(value).replace(',', '.'))
    if not math.isfinite(result):
        raise ValueError('Coordenada o diámetro no finito.')
    return result


def extract_rows(content, required):
    header, unit, rows = None, None, []
    factors = {'millimeters': 1, 'millimetres': 1, 'mils': .0254, 'inches': 25.4}
    for line in content.splitlines():
        fields = line.split('!')
        if fields[0] == 'A':
            header = fields[1:-1]
        elif fields[0] == 'J':
            unit = factors.get(fields[8].strip().lower()) if len(fields) > 8 else None
        elif fields[0] == 'S':
            if header is None or len(fields[1:-1]) != len(header):
                raise ValueError('Informe Extracta incompleto o sin cabecera.')
            rows.append(dict(zip(header, fields[1:-1])))
    if header is None or not set(required).issubset(header) or unit is None:
        raise ValueError('Faltan campos o unidades explícitas en el informe de la PCB.')
    return rows, unit


def parse_allegro_reports(reports, board_name='', source_sha256=''):
    components, factor = extract_rows(reports['components'],
        ['REFDES', 'COMP_PACKAGE', 'SYM_X', 'SYM_Y', 'SYM_ROTATE', 'SYM_MIRROR'])
    pins, pf = extract_rows(reports['pins'], ['REFDES', 'PIN_NUMBER', 'PAD_STACK_NAME', 'PIN_X', 'PIN_Y'])
    outlines, of = extract_rows(reports['outline'], ['GRAPHIC_DATA_NAME', 'GRAPHIC_DATA_1', 'GRAPHIC_DATA_2',
                                                  'GRAPHIC_DATA_3', 'GRAPHIC_DATA_4'])
    by_ref, skipped = {}, []
    for row in components:
        ref = row['REFDES'].strip()
        if not ref or ref in by_ref:
            raise ValueError('Referencias de componente vacías o duplicadas.')
        if not row['SYM_X'] or not row['SYM_Y']:
            skipped.append(ref)
            continue
        mirror = row['SYM_MIRROR'].strip().upper()
        if mirror not in {'YES', 'NO'}:
            raise ValueError(f'{ref}: cara o espejo no reconocido.')
        by_ref[ref] = dict(refdes=ref, footprint=row['COMP_PACKAGE'].strip().upper(),
            x_mm=finite(row['SYM_X'])*factor, y_mm=finite(row['SYM_Y'])*factor,
            rotation_deg=finite(row['SYM_ROTATE']), side='BOTTOM' if mirror == 'YES' else 'TOP', pins=[])
    for row in pins:
        if row['REFDES'] in by_ref and row['PIN_X'] and row['PIN_Y']:
            pin = dict(number=row['PIN_NUMBER'].strip(), padstack=row['PAD_STACK_NAME'].strip().upper(),
                       x_mm=finite(row['PIN_X'])*pf, y_mm=finite(row['PIN_Y'])*pf)
            target = by_ref[row['REFDES']]['pins']
            if pin not in target:
                target.append(pin)
    points = []
    for row in outlines:
        kind = row['GRAPHIC_DATA_NAME'].upper()
        if kind not in {'LINE','RECTANGLE'}:
            raise ValueError('Esta importación requiere un contorno Allegro formado por líneas; exporta una referencia de componentes compatible para contornos con arcos.')
        for xi, yi in [('GRAPHIC_DATA_1','GRAPHIC_DATA_2'), ('GRAPHIC_DATA_3','GRAPHIC_DATA_4')]:
            points.append((finite(row[xi])*of, finite(row[yi])*of))
    if not points:
        raise ValueError('No se encontró BOARD GEOMETRY/OUTLINE en la PCB.')
    bounds = [min(p[0] for p in points), min(p[1] for p in points),
              max(p[0] for p in points), max(p[1] for p in points)]
    return validate_data(dict(schema=SCHEMA, units='mm', board_name=board_name,
        source_sha256=source_sha256, outline_bounds_mm=bounds,
        components=list(by_ref.values()), unplaced=skipped))


def validate_data(data):
    data = copy.deepcopy(data)
    if not isinstance(data,dict) or data.get('schema') != SCHEMA or data.get('units') != 'mm':
        raise ValueError('Referencia de componentes no reconocida o sin unidades mm.')
    bounds = data.get('outline_bounds_mm', [])
    if len(bounds) != 4:
        raise ValueError('La referencia de componentes no contiene el contorno de su PCB.')
    bounds = data['outline_bounds_mm'] = [finite(x) for x in bounds]
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise ValueError('Contorno de referencia inválido.')
    components, seen = data.get('components', []), set()
    if not isinstance(components, list) or len(components) > 100000:
        raise ValueError('Lista de componentes inválida.')
    for c in components:
        ref = str(c['refdes']).strip()
        if not ref or ref in seen:
            raise ValueError('Referencias vacías o duplicadas.')
        seen.add(ref)
        c['refdes'], c['footprint'] = ref, str(c['footprint']).strip().upper()
        if c['side'] not in {'TOP', 'BOTTOM'}:
            raise ValueError(f'{ref}: cara desconocida.')
        for key in ('x_mm','y_mm','rotation_deg'):
            c[key] = finite(c[key])
        if not isinstance(c.get('pins'), list):
            raise ValueError(f'{ref}: falta la lista de pines.')
        for pin in c['pins']:
            pin['x_mm'], pin['y_mm'] = finite(pin['x_mm']), finite(pin['y_mm'])
            pin['number'] = str(pin['number']).strip()
            pin['padstack'] = str(pin['padstack']).strip().upper()
    return data


def find_extracta():
    found = shutil.which('extracta.exe')
    if found:
        return Path(found)
    root = Path('C:/Cadence')
    matches = sorted(root.glob('SPB_*/tools/bin/extracta.exe'), reverse=True) if root.exists() else []
    if not matches:
        raise ValueError('Para leer .brd se necesita Cadence Extracta. También puedes abrir una referencia .pcb-components.json ya exportada.')
    return matches[0]


def read_pcb(path, extracta=None):
    path = Path(path)
    if path.stat().st_size > 200_000_000:
        raise ValueError('Archivo de PCB demasiado grande.')
    if path.suffix.lower() == '.json':
        return validate_data(json.loads(path.read_text(encoding='utf-8-sig')))
    if path.suffix.lower() != '.brd':
        raise ValueError('Elige una PCB .brd o una referencia .pcb-components.json. Los Gerber no contienen las identidades de los footprints.')
    executable = Path(extracta) if extracta else find_extracta()
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    reports = {}
    with tempfile.TemporaryDirectory(prefix='pcb-panel-') as folder:
        root = Path(folder)
        # A snapshot also avoids Cadence's historical non-ASCII path limitations.
        snapshot = root/'board.brd'
        shutil.copyfile(path, snapshot)
        for name, query in QUERIES.items():
            command = root/(name+'.txt')
            command.write_text(query, encoding='ascii')
            result = subprocess.run([str(executable), '-q', '-w', '-l', str(root/(name+'.log')),
                                     str(snapshot), str(command)], cwd=root, capture_output=True,
                                    timeout=90, creationflags=0x08000000 if os.name == 'nt' else 0)
            if result.returncode:
                raise ValueError(f'Cadence no pudo extraer {name}. Guarda primero la PCB y comprueba que Extracta puede leerla.')
            reports[name] = result.stdout.decode('cp1252')
    if hashlib.sha256(path.read_bytes()).hexdigest() != source_hash:
        raise ValueError('La PCB cambió durante la lectura; vuelve a leerla.')
    return parse_allegro_reports(reports, path.name, source_hash)


def validate_rules(rules):
    if not isinstance(rules,dict) or len(rules)>10000:
        raise ValueError('Biblioteca de reglas inválida.')
    result = {}
    for name, value in rules.items():
        if not str(name).strip():
            raise ValueError('El nombre del footprint no puede estar vacío.')
        if not isinstance(value,dict) or not {'diameter_mm','anchor','hole_type','side'}.issubset(value):
            raise ValueError(f'{name}: regla incompleta.')
        rule = dict(value)
        rule['diameter_mm'] = finite(rule['diameter_mm'])
        if not .1 <= rule['diameter_mm'] <= 200 or rule['anchor'] not in ANCHORS:
            raise ValueError(f'{name}: regla o diámetro inválido.')
        if rule['hole_type'] not in {'potentiometer','jack','spdt','dpdt','custom'} or rule.get('side') not in {'TOP','BOTTOM','BOTH'}:
            raise ValueError(f'{name}: tipo de agujero o cara inválidos.')
        rule['value'] = str(rule.get('value','')).strip()
        if rule['anchor'] in {'pin','padstack','pin_pair'} and not rule['value']:
            raise ValueError(f'{name}: indica el pin o padstack de referencia.')
        if rule['anchor']=='pin_pair' and (len(rule['value'].split(','))!=2 or
                any(not p.strip() for p in rule['value'].split(',')) or
                len(set(p.strip() for p in rule['value'].split(',')))!=2):
            raise ValueError(f'{name}: indica dos pines distintos separados por coma.')
        if 'review_required' in rule and not isinstance(rule['review_required'],bool):raise ValueError('Revisión de regla inválida.')
        result[str(name).strip().upper()] = rule
    return result


def anchor_point(component, rule):
    pins, anchor = component['pins'], rule['anchor']
    if anchor == 'origin':
        return component['x_mm'], component['y_mm']
    if anchor == 'mechanical_pair':
        selected = [p for p in pins if not p['number']]
        expected = 2
    elif anchor == 'pin':
        selected = [p for p in pins if p['number'] == rule['value']]
        expected = 1
    elif anchor == 'pin_pair':
        names={p.strip() for p in rule['value'].split(',')}
        selected=[p for p in pins if p['number'] in names]
        expected=2
        if {p['number'] for p in selected}!=names:raise ValueError('Falta uno de los dos pines de anclaje.')
    else:
        selected = [p for p in pins if p['padstack'].upper() == rule['value'].upper()]
        expected = 1
    if len(selected) != expected:
        raise ValueError(f'Se esperaban {expected} anclajes y se encontraron {len(selected)}.')
    return sum(p['x_mm'] for p in selected)/expected, sum(p['y_mm'] for p in selected)/expected


def proposals(data, rules, bounds, drills=()):
    data, rules = validate_data(data), validate_rules(rules)
    if bounds is None or any(abs(a-b) > .05 for a,b in zip(bounds, data['outline_bounds_mm'])):
        raise ValueError('El contorno de esta PCB no coincide con la referencia del frontal. Carga primero sus Gerber y drills.')
    # Cross-check actual THT pins against loaded Excellon, when available.
    drill_points = {}
    for x,y in drills:
        drill_points.setdefault((round(x/.05),round(y/.05)),[]).append((x,y))
    def matches(x,y):
        return any(math.hypot(x-px,y-py)<=.05 for dx in (-1,0,1) for dy in (-1,0,1)
                   for px,py in drill_points.get((round(x/.05)+dx,round(y/.05)+dy),[]))
    result, skipped = [], []
    for c in data['components']:
        rule = rules.get(c['footprint'])
        if rule is None:
            continue
        if rule['side'] not in ('BOTH',c['side']):
            skipped.append((c['refdes'], 'Cara distinta de la configurada en la regla.'))
            continue
        if drill_points and any(not matches(p['x_mm'],p['y_mm']) for p in c['pins']):
            raise ValueError(f"{c['refdes']}: los pads no coinciden con los drills cargados. Puede ser otra versión de la PCB.")
        try:
            x,y = anchor_point(c, rule)
        except ValueError as error:
            skipped.append((c['refdes'], str(error)))
            continue
        if not (bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]):
            skipped.append((c['refdes'], 'Centro fuera del contorno de la PCB.'))
            continue
        result.append(dict(refdes=c['refdes'], footprint=c['footprint'], x_mm=x,y_mm=y,
                           diameter_mm=rule['diameter_mm'], hole_type=rule['hole_type'], side=c['side'],
                           review_required=rule.get('review_required',False)))
    return result, skipped
