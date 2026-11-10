"""Excellon drill reference reader. Ambiguous coordinate formats are rejected."""
import math
from pathlib import Path
import re


def parameter_format(content):
    integers = re.search(r'INTEGER-PLACES\s+(\d+)', content)
    decimals = re.search(r'DECIMAL-PLACES\s+(\d+)', content)
    if not integers or not decimals:
        raise ValueError('No se ha encontrado el formato de coordenadas en nc_param.txt.')
    return int(integers.group(1)), int(decimals.group(1))


class DrillLayer:
    """Compatible drawing primitives, deliberately without Gerber export methods."""
    def __init__(self, content, coord_format=None):
        self.raw_lines = content.splitlines(keepends=True)
        self.filepath = None
        self.used_apertures = set()
        self.drawables = []
        self.unit = 'IN' if re.search(r'(?m)^INCH', content) else 'MM'
        factor = 25.4 if self.unit == 'IN' else 1
        declared = re.search(r'FILE_FORMAT\s*[=:]\s*(\d+)[:.]([0-9]+)', content)
        mask = re.search(r'(?:METRIC|INCH)(?:,[A-Z]+)?,(0+)\.(0+)', content)
        if declared:
            coord_format = (int(declared.group(1)), int(declared.group(2)))
        elif mask:
            coord_format = (len(mask.group(1)), len(mask.group(2)))
        coordinate_lines = [line.strip() for line in content.splitlines() if re.match(r'^[XY][+-]?[\d.]', line.strip())]
        if coord_format is None and any('.' not in part for line in coordinate_lines
                                       for part in re.findall(r'[XY]([+-]?[\d.]+)', line)):
            raise ValueError('Drill sin formato de coordenadas: selecciona también nc_param.txt '
                             'o indica FILE_FORMAT en su cabecera. No se adivina la escala.')
        self.format_x = self.format_y = tuple(coord_format or (3, 3))
        # Excellon TZ means trailing zeroes are present; omitted leading zeroes.
        leading_present = bool(re.search(r'(?:METRIC|INCH),LZ', content))
        if re.search(r'(?m)^(?:G91|ICI,ON)', content):
            raise ValueError('Drill incremental no admitido.')

        def decode(raw):
            if '.' in raw:
                return float(raw) * factor
            sign = -1 if raw.startswith('-') else 1
            digits = raw.lstrip('+-')
            if leading_present:
                digits = digits.ljust(sum(self.format_x), '0')
            return sign * int(digits) / 10**self.format_x[1] * factor

        tools, active, x, y = {}, None, 0.0, 0.0
        for source in content.splitlines():
            line = source.split(';', 1)[0].strip()
            if not line:
                continue
            tool = re.fullmatch(r'T(\d+)C([\d.]+)', line)
            if tool:
                diameter = float(tool.group(2)) * factor
                if not math.isfinite(diameter) or diameter <= 0:
                    raise ValueError('Diámetro de herramienta no válido.')
                tools[int(tool.group(1))] = diameter
                continue
            tool = re.fullmatch(r'T(\d+)', line)
            if tool:
                active = int(tool.group(1))
                continue
            if line.startswith(('G00', 'G01', 'G02', 'G03', 'M15', 'G85', 'R')):
                raise ValueError('El drill contiene rutas, ranuras o repeticiones todavía no admitidas.')
            hit = re.fullmatch(r'(?:X([+-]?[\d.]+))?(?:Y([+-]?[\d.]+))?', line)
            if hit and any(hit.groups()):
                if active not in tools:
                    raise ValueError('Coordenada drill sin herramienta definida.')
                if hit.group(1) is not None:
                    x = decode(hit.group(1))
                if hit.group(2) is not None:
                    y = decode(hit.group(2))
                diameter = tools[active]
                self.drawables.append(dict(type='flash', x=x, y=y, sx=diameter, sy=diameter,
                                           shape='C', polarity='dark', tool=active))
        if not self.drawables:
            raise ValueError('El drill no contiene taladros reconocidos.')
        self.tools = tools
        self.bounds = (min(h['x']-h['sx']/2 for h in self.drawables),
                       min(h['y']-h['sy']/2 for h in self.drawables),
                       max(h['x']+h['sx']/2 for h in self.drawables),
                       max(h['y']+h['sy']/2 for h in self.drawables))


class RouteLayer:
    """Straight Excellon milling references; slot centres are registration points."""
    def __init__(self, content, coord_format=None):
        self.raw_lines = content.splitlines(keepends=True)
        self.filepath = None
        self.used_apertures = set()
        self.drawables = []
        self.unit = 'IN' if re.search(r'(?m)^INCH', content) else 'MM'
        factor = 25.4 if self.unit == 'IN' else 1
        declared = re.search(r'FILE_FORMAT\s*[=:]\s*(\d+)[:.]([0-9]+)', content)
        mask = re.search(r'(?:METRIC|INCH)(?:,[A-Z]+)?,(0+)\.(0+)', content)
        if declared: coord_format = (int(declared[1]), int(declared[2]))
        elif mask: coord_format = (len(mask[1]), len(mask[2]))
        coords = re.findall(r'[XY]([+-]?[\d.]+)', '\n'.join(s.split(';')[0] for s in content.splitlines()))
        if coord_format is None and any('.' not in value for value in coords):
            raise ValueError('Ranuras sin formato: carga también nc_param.txt. No se adivina la escala.')
        self.format_x = self.format_y = tuple(coord_format or (3, 3))
        leading = bool(re.search(r'(?:METRIC|INCH),LZ', content))
        def decode(value):
            if '.' in value: return float(value)*factor
            sign = -1 if value.startswith('-') else 1
            digits = value.lstrip('+-')
            if leading: digits = digits.ljust(sum(self.format_x), '0')
            return sign*int(digits)/10**self.format_x[1]*factor
        tools, active, x, y, cutting, positioned = {}, None, 0., 0., False, False
        for source in content.splitlines():
            line = source.split(';')[0].strip()
            if not line: continue
            tool = re.fullmatch(r'T(\d+)C([\d.]+)', line)
            if tool:
                diameter = float(tool[2])*factor
                if not math.isfinite(diameter) or diameter <= 0: raise ValueError('Herramienta de ranura inválida.')
                tools[int(tool[1])] = diameter
                continue
            tool = re.fullmatch(r'T(\d+)', line)
            if tool:
                if cutting: raise ValueError('Cambio de herramienta durante el fresado.')
                active = int(tool[1]); continue
            if line == 'M15':
                if active not in tools or not positioned: raise ValueError('Ranura sin herramienta o punto inicial.')
                cutting = True; continue
            if line == 'M16': cutting = False; continue
            move = re.fullmatch(r'G0([01])(?:X([+-]?[\d.]+))?(?:Y([+-]?[\d.]+))?', line)
            if move and (move[2] is not None or move[3] is not None):
                nx = decode(move[2]) if move[2] is not None else x
                ny = decode(move[3]) if move[3] is not None else y
                if move[1] == '0':
                    if cutting: raise ValueError('Movimiento rápido con la herramienta bajada.')
                else:
                    if not cutting or active not in tools: raise ValueError('Fresado sin herramienta activa.')
                    if abs(nx-x)>1e-7 and abs(ny-y)>1e-7:
                        raise ValueError('Ranuras diagonales todavía no admitidas; no se aproximan.')
                    diameter = tools[active]
                    self.drawables.append(dict(type='flash',shape='O',x=(x+nx)/2,y=(y+ny)/2,
                        sx=abs(nx-x)+diameter,sy=abs(ny-y)+diameter,polarity='dark',tool=active))
                x,y,positioned = nx,ny,True
                continue
            if line in ('M48','%','G90','G40','M30') or re.fullmatch(r'F[\d.]+',line) or re.fullmatch(r'(METRIC|INCH)(,[A-Z]+)?(,0+\.0+)?',line):
                continue
            raise ValueError(f'Instrucción de ranuras no admitida: {line}')
        if cutting or not self.drawables: raise ValueError('Archivo de ranuras incompleto o vacío.')
        self.tools = tools
        self.bounds = (min(p['x']-p['sx']/2 for p in self.drawables), min(p['y']-p['sy']/2 for p in self.drawables),
                       max(p['x']+p['sx']/2 for p in self.drawables), max(p['y']+p['sy']/2 for p in self.drawables))
