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
