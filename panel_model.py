"""Millimetre geometry and portable documents for the Eurorack front-panel editor."""
from dataclasses import dataclass, field, asdict
import json
import math
from pathlib import Path
import re
import tempfile
from xml.sax.saxutils import escape
import zipfile

from gerber_silkscreen_editor import GerberLayer
from drill import DrillLayer, parameter_format

HEIGHT_MM = 128.5
HP_MM = 5.08
SCHEMA = "sputtering.front-panel.v1"
# Starting templates, not a claim that every part in a family has this bushing.
HOLE_PRESETS = {
    'potentiometer': ('Potenciómetro · Ø7 mm', 7.0, 'Potenciómetro'),
    'jack': ('Jack 3,5 mm · Ø6 mm', 6.0, 'Jack'),
    'spdt': ('SPDT mini · Ø6,5 mm', 6.5, 'SPDT'),
    'rack': ('Tornillo de rack · Ø3,2 mm', 3.2, 'Tornillo rack'),
    'custom': ('Personalizado', None, 'Agujero'),
}
GERBER_EXTENSIONS = {'.gbr', '.ger', '.art', '.gto', '.gbo', '.gko', '.gm1',
                     '.gtl', '.gbl', '.gts', '.gbs', '.pho'}
DRILL_EXTENSIONS = {'.drl', '.xln', '.exc'}


def number(value, minimum=None, maximum=None):
    result = float(str(value).replace(',', '.'))
    if not math.isfinite(result):
        raise ValueError("Introduce un número finito.")
    if minimum is not None and result < minimum:
        raise ValueError(f"El valor mínimo es {minimum}.")
    if maximum is not None and result > maximum:
        raise ValueError(f"El valor máximo es {maximum}.")
    return result


def atomic_write(path, text):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def geometry_bounds(layer, outline=False):
    """Include curves and apertures; outlines use their centreline, not pen width."""
    boxes = []
    for item in layer.drawables:
        if item['type'] == 'line':
            r = 0 if outline else item['width'] / 2
            boxes.append((min(item['x1'], item['x2'])-r, min(item['y1'], item['y2'])-r,
                          max(item['x1'], item['x2'])+r, max(item['y1'], item['y2'])+r))
        elif item['type'] == 'flash':
            boxes.append((item['x']-item['sx']/2, item['y']-item['sy']/2,
                          item['x']+item['sx']/2, item['y']+item['sy']/2))
        elif item['type'] == 'region' and item['path']:
            xs, ys = zip(*item['path'])
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
    if not boxes:
        raise ValueError("La capa no contiene geometría Gerber reconocida.")
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


@dataclass
class Reference:
    name: str
    content: str
    visible: bool = True
    coord_format: tuple = None
    layer: GerberLayer = field(init=False, repr=False)

    def __post_init__(self):
        if Path(self.name).suffix.lower() in DRILL_EXTENSIONS:
            self.layer = DrillLayer(self.content, self.coord_format)
            self.coord_format = self.layer.format_x
            return
        # Do not silently display unsupported constructs at misleading dimensions.
        unsupported = [
            (r'%\s*AM', 'macros de apertura'), (r'%\s*SR(?!\s*\*)', 'repetición de bloques'),
            (r'%\s*FS[LT]I', 'coordenadas incrementales'),
            (r'%\s*FST', 'supresión de ceros finales'),
            (r'(?:^|[\s*])G74\*', 'arcos de cuadrante único'),
            (r'(?:^|[\s*])G91\*', 'coordenadas incrementales'),
        ]
        for pattern, label in unsupported:
            if re.search(pattern, self.content):
                raise ValueError(f"{self.name}: todavía no se admite {label} en la referencia.")
        # Allegro groups identity transforms in one %...% block. Check every
        # command, not only the first command after the opening percent sign.
        for command in re.split(r'[%*]', self.content):
            command = command.strip()
            if command.startswith(('OF', 'MI', 'SF')):
                match = re.fullmatch(r'(OF|MI|SF)A([+-]?[\d.]+)B([+-]?[\d.]+)', command)
                identity = 1 if command.startswith('SF') else 0
                if not match or any(number(match.group(i)) != identity for i in (2, 3)):
                    raise ValueError(f'{self.name}: transformación no admitida: {command}.')
            elif command.startswith(('IR', 'LR', 'LS')):
                identity = 1 if command.startswith('LS') else 0
                try:
                    valid = number(command[2:]) == identity
                except ValueError:
                    valid = False
                if not valid:
                    raise ValueError(f'{self.name}: transformación no admitida: {command}.')
            elif command.startswith(('LM', 'AS', 'IP')):
                if command not in {'LMN', 'ASAXBY', 'IPPOS'}:
                    raise ValueError(f'{self.name}: transformación no admitida: {command}.')
        for shape in re.findall(r'%\s*ADD\d+([A-Za-z_][\w]*)', self.content):
            if shape not in {'C', 'R', 'O'}:
                raise ValueError(f"{self.name}: apertura {shape} todavía no admitida.")
        if not re.search(r'%\s*FSLAX\d\dY\d\d\*', self.content):
            raise ValueError(f"{self.name}: se necesita formato Gerber absoluto FSLAX/Y explícito.")
        for region in re.findall(r'G36\*(.*?)G37\*', self.content, re.S):
            if len(re.findall(r'D0?2\*', region)) > 1:
                raise ValueError(f"{self.name}: regiones con varios contornos todavía no admitidas.")
        self.layer = GerberLayer()
        self.layer.raw_lines = self.content.splitlines(keepends=True)
        self.layer._parse()
        if self.layer.drawables:
            self.layer.bounds = geometry_bounds(self.layer)
        else:
            # Una serigrafía exportada vacía sigue siendo un destino Gerber válido.
            # Aceptar solo un cuerpo de configuración/fin, nunca geometría ignorada.
            body = re.sub(r'G0?4[^*]*\*', '', self.content)
            body = re.sub(r'%[^%]*%', '', body)
            commands = [command.strip() for command in body.split('*') if command.strip()]
            if (not commands or commands[-1] not in {'M02', 'M2'} or
                    any(not re.fullmatch(r'M0?2|G0?1|G75|D\d+', command) for command in commands)):
                raise ValueError(f'{self.name}: la capa vacía contiene comandos no reconocidos o está incompleta.')
            self.layer.bounds = None

    def serialise(self):
        return {'name': self.name, 'content': self.content, 'visible': self.visible,
                'coord_format': list(self.coord_format) if self.coord_format else None}


def load_references(paths):
    references, errors = [], []
    explicit_params = next((Path(p) for p in paths if Path(p).name.lower() == 'nc_param.txt'), None)
    for path in paths:
        path = Path(path)
        if path.name.lower() == 'nc_param.txt':
            continue
        try:
            if path.suffix.lower() == '.zip':
                with zipfile.ZipFile(path) as archive:
                    for member in archive.infolist():
                        if member.is_dir() or Path(member.filename).suffix.lower() not in GERBER_EXTENSIONS | DRILL_EXTENSIONS:
                            continue
                        if member.file_size > 30_000_000:
                            errors.append(f"{member.filename}: supera 30 MB.")
                            continue
                        try:
                            fmt = None
                            if Path(member.filename).suffix.lower() in DRILL_EXTENSIONS:
                                params_name = str(Path(member.filename).with_name('nc_param.txt')).replace('\\', '/')
                                for candidate in (params_name, 'parametros/nc_param.txt'):
                                    if candidate in archive.namelist():
                                        fmt = parameter_format(archive.read(candidate).decode('utf-8-sig'))
                                        break
                            references.append(Reference(member.filename, archive.read(member).decode('utf-8-sig'), coord_format=fmt))
                        except (ValueError, UnicodeError) as error:
                            errors.append(str(error))
            else:
                fmt = None
                if path.suffix.lower() in DRILL_EXTENSIONS:
                    params = explicit_params or path.with_name('nc_param.txt')
                    if params.exists():
                        fmt = parameter_format(params.read_text(encoding='utf-8-sig'))
                references.append(Reference(path.name, path.read_text(encoding='utf-8-sig'), coord_format=fmt))
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            errors.append(f"{path.name}: {error}")
    return references, errors


@dataclass
class Element:
    kind: str
    x: float
    y: float
    size: float
    text: str = ''
    hole_type: str = ''
    source_ref: str = ''
    source_footprint: str = ''
    board_x: float | None = None
    board_y: float | None = None

    def __post_init__(self):
        if self.kind not in {'hole', 'text'}:
            raise ValueError("Tipo de objeto no reconocido.")
        self.x, self.y = number(self.x), number(self.y)
        self.size = number(self.size, 0.1, 200)
        self.text = str(self.text)
        if self.hole_type not in ('', *HOLE_PRESETS):
            raise ValueError('Tipo de agujero no reconocido.')
        if self.kind != 'hole' and self.hole_type:
            raise ValueError('Solo los agujeros pueden tener un tipo de montaje.')
        if self.kind == 'text' and not self.text.strip():
            raise ValueError("Escribe un texto.")
        if self.source_ref:
            if not self.source_footprint:
                raise ValueError('Referencia de footprint incompleta.')
            self.board_x, self.board_y = number(self.board_x), number(self.board_y)

    @property
    def is_rack_mount(self):
        # The original projects identified generated mounts only by this name.
        return self.kind == 'hole' and (self.hole_type == 'rack' or
               (not self.hole_type and self.text.strip().casefold() == 'tornillo rack'))


@dataclass
class PanelDocument:
    hp: int = 16
    gap: float = 0.34
    layers: list = field(default_factory=list)
    reference_index: int = 0
    pcb_dx: float = 0
    pcb_dy: float = 0
    elements: list = field(default_factory=list)
    component_data: dict | None = None
    footprint_rules: dict = field(default_factory=dict)

    def __post_init__(self):
        hp = number(self.hp, 2, 168)
        if not hp.is_integer():
            raise ValueError("El ancho debe ser un número entero de HP.")
        self.hp = int(hp)
        self.gap = number(self.gap, 0, 1)
        self.pcb_dx, self.pcb_dy = number(self.pcb_dx), number(self.pcb_dy)
        if self.layers and not (isinstance(self.reference_index, int) and 0 <= self.reference_index < len(self.layers)):
            raise ValueError("La capa de referencia no existe.")
        if self.component_data is not None or self.footprint_rules:
            from footprint_holes import validate_data, validate_rules
            if self.component_data is not None:
                self.component_data = validate_data(self.component_data)
            self.footprint_rules = validate_rules(self.footprint_rules)

    @property
    def width(self):
        return self.hp * HP_MM - self.gap

    def reference_bounds(self):
        if not self.layers:
            return None
        return geometry_bounds(self.layers[self.reference_index].layer, outline=True)

    def choose_outline(self):
        for index, ref in enumerate(self.layers):
            if re.search(r'outline|board.?outline|profile|edge.?cuts|\.gko$|\.gm1$', ref.name, re.I):
                self.reference_index = index
                return True
        self.reference_index = 0
        return False

    def center_pcb(self):
        bounds = self.reference_bounds()
        if bounds:
            self.pcb_dx = self.width / 2 - (bounds[0] + bounds[2]) / 2
            self.pcb_dy = HEIGHT_MM / 2 - (bounds[1] + bounds[3]) / 2
            self.sync_footprint_holes()

    def sync_footprint_holes(self):
        # Both generated holes and refdes labels share the PCB translation.
        for e in self.elements:
            if e.source_ref:
                e.x, e.y = e.board_x+self.pcb_dx, e.board_y+self.pcb_dy

    def detach_footprint_holes(self):
        self.component_data = None
        for e in self.elements:
            e.source_ref, e.source_footprint = '', ''
            e.board_x = e.board_y = None

    def apply_footprint_holes(self, data, rules, selected_refs):
        from footprint_holes import proposals, validate_data, validate_rules
        data, rules = validate_data(data), validate_rules(rules)
        drills = [(p['x'],p['y']) for r in self.layers if r.coord_format for p in r.layer.drawables]
        items, skipped = proposals(data, rules, self.reference_bounds(), drills)
        selected = set(selected_refs)
        if not selected.issubset({item['refdes'] for item in items}):
            raise ValueError('Hay componentes seleccionados sin una propuesta válida.')
        updates, collisions = [], []
        for item in items:
            if item['refdes'] not in selected:
                continue
            x,y = item['x_mm']+self.pcb_dx, item['y_mm']+self.pcb_dy
            radius=item['diameter_mm']/2
            if not (radius <= x <= self.width-radius and radius <= y <= HEIGHT_MM-radius):
                raise ValueError(f"{item['refdes']}: el agujero queda fuera del frontal.")
            owned = [e for e in self.elements if e.kind == 'hole' and e.source_ref == item['refdes']]
            if not owned and any(e.kind == 'hole' and not e.source_ref and
                                 math.hypot(e.x-x,e.y-y) < .05 for e in self.elements):
                collisions.append(item['refdes'])
                continue
            if any(e.kind == 'hole' and not e.source_ref and
                   math.hypot(e.x-x,e.y-y) < (e.size+item['diameter_mm'])/2 for e in self.elements):
                raise ValueError(f"{item['refdes']}: se solapa con un agujero manual. Revisa o retira ese agujero antes de generar este centro.")
            updates.append(Element('hole',x,y,item['diameter_mm'],item['refdes'],item['hole_type'],
                                   item['refdes'],item['footprint'],item['x_mm'],item['y_mm']))
        replaced = {e.source_ref for e in updates}
        self.elements = [e for e in self.elements if e.kind != 'hole' or e.source_ref not in replaced]+updates
        self.component_data, self.footprint_rules = data, rules
        return len(updates), collisions, skipped

    def refdes_labels(self, data, rules, size=2.5, gap=1.0, position='above'):
        """Propose labels for the same mechanically registered components as holes."""
        from footprint_holes import proposals
        size, gap = number(size, .5, 20), number(gap, 0, 50)
        if position not in {'above', 'below'}:
            raise ValueError('Elige encima o debajo del agujero.')
        drills = [(p['x'],p['y']) for r in self.layers if r.coord_format for p in r.layer.drawables]
        items, skipped = proposals(data, rules, self.reference_bounds(), drills)
        holes = {e.source_ref: e for e in self.elements if e.kind == 'hole' and e.source_ref}
        result = []
        for item in items:
            hole = holes.get(item['refdes'])
            x = hole.x if hole else item['x_mm']+self.pcb_dx
            cy = hole.y if hole else item['y_mm']+self.pcb_dy
            radius = (hole.size if hole else item['diameter_mm'])/2
            y = cy+(radius+gap+size/2)*(1 if position == 'above' else -1)
            result.append(Element('text', x, y, size, item['refdes'],
                                  source_ref=item['refdes'], source_footprint=item['footprint'],
                                  board_x=x-self.pcb_dx, board_y=y-self.pcb_dy))
        return result, skipped

    def apply_refdes_labels(self, data, rules, selected_refs, size=2.5, gap=1.0, position='above'):
        from footprint_holes import validate_data, validate_rules
        data, rules = validate_data(data), validate_rules(rules)
        labels, skipped = self.refdes_labels(data, rules, size, gap, position)
        selected = set(selected_refs)
        if not selected.issubset({e.source_ref for e in labels}):
            raise ValueError('Hay componentes seleccionados sin etiqueta válida.')
        updates, preserved = [], []
        for label in labels:
            if label.source_ref not in selected:
                continue
            # Conservative width estimate matches centred Arial preview/export.
            half_width = len(label.text)*label.size*.4
            if not (half_width <= label.x <= self.width-half_width and
                    label.size/2 <= label.y <= HEIGHT_MM-label.size/2):
                raise ValueError(f'{label.source_ref}: la etiqueta queda fuera del frontal.')
            owned = [e for e in self.elements if e.kind == 'text' and e.source_ref == label.source_ref]
            manual = [e for e in self.elements if e.kind == 'text' and not e.source_ref and
                      e.text.strip().casefold() == label.text.casefold()]
            if manual or owned:
                # Keep hand-edited label text and offsets on repeated imports.
                preserved.append(label.source_ref)
                continue
            updates.append(label)
        self.elements.extend(updates)
        self.component_data, self.footprint_rules = data, rules
        return len(updates), preserved, skipped

    def mounting_holes(self):
        if self.hp < 4:
            raise ValueError("Para el patrón de tornillos de esta versión elige al menos 4 HP.")
        xs = [7.5] if self.hp < 10 else [7.5, 7.5 + (self.hp - 3) * HP_MM]
        candidates = [Element('hole', x, y, 3.2, 'Tornillo rack', 'rack') for x in xs for y in (3, HEIGHT_MM-3)]
        # Replace the entire generated pattern, including old-width duplicates.
        # Unrelated holes are never removed merely because they share coordinates.
        self.elements = [e for e in self.elements if not e.is_rack_mount]+candidates

    def problems(self):
        issues = []
        bounds = self.reference_bounds()
        if bounds and (bounds[0]+self.pcb_dx < 0 or bounds[2]+self.pcb_dx > self.width or
                       bounds[1]+self.pcb_dy < 0 or bounds[3]+self.pcb_dy > HEIGHT_MM):
            issues.append('La PCB sobresale del frontal; aumenta los HP o revisa la capa de contorno.')
        for i, element in enumerate(self.elements):
            radius = element.size / 2 if element.kind == 'hole' else 0
            if not (radius <= element.x <= self.width-radius and radius <= element.y <= HEIGHT_MM-radius):
                issues.append(f'Objeto {i+1}: fuera del panel o demasiado cerca del borde.')
            if element.kind == 'hole':
                for other in self.elements[:i]:
                    if other.kind == 'hole' and math.hypot(element.x-other.x, element.y-other.y) < (element.size+other.size)/2:
                        issues.append(f'Agujero {i+1}: se solapa con otro agujero.')
        return issues

    def to_dict(self):
        return {'schema': SCHEMA, 'hp': self.hp, 'gap': self.gap,
                'layers': [ref.serialise() for ref in self.layers],
                'reference_index': self.reference_index, 'pcb_dx': self.pcb_dx,
                'pcb_dy': self.pcb_dy, 'elements': [asdict(e) for e in self.elements],
                'component_data': self.component_data, 'footprint_rules': self.footprint_rules}

    @classmethod
    def from_dict(cls, value):
        if value.get('schema') != SCHEMA:
            raise ValueError('Formato de proyecto no reconocido.')
        return cls(hp=value['hp'], gap=value['gap'],
                   layers=[Reference(**ref) for ref in value['layers']],
                   reference_index=value['reference_index'], pcb_dx=value['pcb_dx'],
                   pcb_dy=value['pcb_dy'], elements=[Element(**e) for e in value['elements']],
                   component_data=value.get('component_data'), footprint_rules=value.get('footprint_rules', {}))

    def save(self, path):
        atomic_write(path, json.dumps(self.to_dict(), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8')))

    def svg(self):
        # Reference PCB is intentionally omitted; the exported geometry is the panel.
        lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width:g}mm" '
                 f'height="{HEIGHT_MM:g}mm" viewBox="0 0 {self.width:g} {HEIGHT_MM:g}">',
                 '<title>Frontal Eurorack 3U — Sputtering Design Tools</title>',
                 '<g id="panel-outline" fill="none" stroke="#000" stroke-width="0.1">',
                 f'<rect x="0" y="0" width="{self.width:g}" height="{HEIGHT_MM:g}"/>', '</g>',
                 '<g id="holes" fill="none" stroke="#000" stroke-width="0.1">']
        for element in self.elements:
            if element.kind == 'hole':
                lines.append(f'<circle cx="{element.x:g}" cy="{HEIGHT_MM-element.y:g}" r="{element.size/2:g}"/>')
        lines += ['</g>', '<g id="artwork" fill="#000" font-family="Arial, sans-serif" '
                  'text-anchor="middle" dominant-baseline="central">']
        for element in self.elements:
            if element.kind == 'text':
                lines.append(f'<text x="{element.x:g}" y="{HEIGHT_MM-element.y:g}" '
                             f'font-size="{element.size:g}">{escape(element.text)}</text>')
        return '\n'.join(lines + ['</g>', '</svg>', ''])
