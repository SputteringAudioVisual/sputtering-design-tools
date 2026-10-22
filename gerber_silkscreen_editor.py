#!/usr/bin/env python3
"""
Gerber Silkscreen Editor
Permite abrir archivos Gerber, importar imágenes PNG/JPG/SVG
y añadirlas a la serigrafía con transformaciones interactivas.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import math
import re
import os
from pathlib import Path

try:
    from PIL import Image, ImageTk, ImageOps, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import svgpathtools
    SVG_AVAILABLE = True
except ImportError:
    SVG_AVAILABLE = False


# ─────────────────────────────────────────────
#  GERBER PARSER / WRITER (básico pero funcional)
# ─────────────────────────────────────────────

class GerberLayer:
    """Representa una capa Gerber parseada."""

    def __init__(self):
        self.raw_lines = []
        self.header_lines = []
        self.body_lines = []
        self.footer_lines = []
        self.unit = "MM"          # MM o IN
        self.format_x = (3, 6)   # (integer digits, decimal digits)
        self.format_y = (3, 6)
        self.bounds = None        # (xmin, ymin, xmax, ymax)
        self.drawables = []       # Lista de primitivas para dibujar en canvas
        self.filepath = None
        self.used_apertures = set()  # códigos D usados (para no colisionar al exportar)

    def load(self, filepath: str):
        self.filepath = filepath
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            self.raw_lines = f.readlines()
        self._parse()
        return self

    def _parse(self):
        """Parseo básico: extrae formato, unidades y primitivas de dibujo."""
        self.drawables = []
        coords = []
        current_x, current_y = 0.0, 0.0
        current_aperture = 10
        apertures = {}  # code -> (shape, size_x, size_y)
        in_region = False
        region_path = []
        polarity = "dark"
        arc_mode = 0   # 0=lineal(G01), 2=CW(G02), 3=CCW(G03)

        # Unir líneas que terminan en '*'
        full = "".join(self.raw_lines)
        # Separar por '*'
        tokens = re.split(r'\*', full)

        i = 0
        header_done = False

        for raw in tokens:
            cmd = raw.strip().lstrip('%')

            # Formato de coordenadas
            m = re.match(r'FSLA?X(\d)(\d)Y(\d)(\d)', cmd)
            if m:
                self.format_x = (int(m.group(1)), int(m.group(2)))
                self.format_y = (int(m.group(3)), int(m.group(4)))
                continue

            # Unidades
            if cmd.startswith('MOMM') or cmd == 'MO MM':
                self.unit = "MM"
                continue
            if cmd.startswith('MOIN') or cmd == 'MO IN':
                self.unit = "IN"
                continue

            # Apertura con ADD
            m = re.match(r'ADD(\d+)([A-Z]+),?([0-9.X]*)', cmd)
            if m:
                code = int(m.group(1))
                shape = m.group(2)
                sizes = [float(s) for s in m.group(3).split('X') if s]
                sx = sizes[0] if sizes else 0.1
                sy = sizes[1] if len(sizes) > 1 else sx
                apertures[code] = (shape, sx, sy)
                self.used_apertures.add(code)
                continue

            # Selección de apertura
            m = re.match(r'D(\d+)$', cmd)
            if m:
                current_aperture = int(m.group(1))
                continue

            # Polaridad
            if cmd.startswith('LPD'):
                polarity = "dark"
                continue
            if cmd.startswith('LPC'):
                polarity = "clear"
                continue

            # Inicio de región
            if cmd == 'G36':
                in_region = True
                region_path = []
                continue
            if cmd == 'G37':
                if len(region_path) > 2:
                    self.drawables.append({
                        "type": "region",
                        "path": list(region_path),
                        "polarity": polarity
                    })
                in_region = False
                region_path = []
                continue

            # Modo de interpolación (puede venir solo o con coords detrás)
            if cmd.startswith("G01"):
                arc_mode = 0
            elif cmd.startswith("G02"):
                arc_mode = 2
            elif cmd.startswith("G03"):
                arc_mode = 3

            # Movimiento / flash / draw (acepta prefijo G01/G02/G03)
            m = re.match(r'(?:G0[0123])?(X([+-]?\d+))?(Y([+-]?\d+))?(I([+-]?\d+))?(J([+-]?\d+))?D0?([123])', cmd)
            if m:
                raw_x = m.group(2)
                raw_y = m.group(4)
                raw_i = m.group(6)
                raw_j = m.group(8)
                op = int(m.group(9))

                prev_x, prev_y = current_x, current_y
                if raw_x is not None:
                    current_x = self._decode_coord(raw_x, self.format_x)
                if raw_y is not None:
                    current_y = self._decode_coord(raw_y, self.format_y)

                ap = apertures.get(current_aperture, ('C', 0.1, 0.1))
                size = ap[1]

                if op == 3:  # Flash
                    self.drawables.append({
                        "type": "flash",
                        "x": current_x, "y": current_y,
                        "shape": ap[0], "sx": ap[1], "sy": ap[2],
                        "polarity": polarity
                    })
                elif op == 1:  # Draw
                    if arc_mode in (2, 3) and (raw_i is not None or raw_j is not None):
                        # Arco: convertir a segmentos de línea
                        i_off = self._decode_offset(raw_i, self.format_x) if raw_i else 0.0
                        j_off = self._decode_offset(raw_j, self.format_y) if raw_j else 0.0
                        segs = self._arc_to_segments(prev_x, prev_y, current_x, current_y,
                                                     i_off, j_off, arc_mode, size, polarity)
                        self.drawables.extend(segs)
                        if in_region:
                            for s in segs:
                                region_path.append((s["x2"], s["y2"]))
                    else:
                        seg = {
                            "type": "line",
                            "x1": prev_x, "y1": prev_y,
                            "x2": current_x, "y2": current_y,
                            "width": size, "polarity": polarity
                        }
                        self.drawables.append(seg)
                        if in_region:
                            region_path.append((current_x, current_y))
                elif op == 2:  # Move
                    if in_region:
                        region_path.append((current_x, current_y))

                coords.append((current_x, current_y))

        # Calcular bounds
        if coords:
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            self.bounds = (min(xs), min(ys), max(xs), max(ys))
        else:
            self.bounds = (0, 0, 10, 10)

    def _decode_coord(self, raw: str, fmt: tuple) -> float:
        """Convierte coordenada Gerber a milímetros."""
        integer_d, decimal_d = fmt
        sign = -1 if raw.startswith('-') else 1
        digits = raw.lstrip('+-')
        # Rellenar hasta tener suficientes decimales
        total = integer_d + decimal_d
        digits = digits.zfill(total)
        integer_part = digits[:-decimal_d] if decimal_d else digits
        decimal_part = digits[-decimal_d:] if decimal_d else "0"
        value = sign * (int(integer_part or 0) + int(decimal_part) / (10 ** decimal_d))
        if self.unit == "IN":
            value *= 25.4
        return value

    def _decode_offset(self, raw: str, fmt: tuple) -> float:
        """Decodifica un offset I/J (mismo formato que coordenada)."""
        if raw is None:
            return 0.0
        return self._decode_coord(raw, fmt)

    def _arc_to_segments(self, x1, y1, x2, y2, i_off, j_off, mode, width, polarity):
        """Convierte un arco (G02 CW / G03 CCW) en una lista de segmentos de línea."""
        import math
        cx = x1 + i_off    # centro = inicio + offset (I,J)
        cy = y1 + j_off
        r = math.hypot(x1 - cx, y1 - cy)
        if r < 1e-9:
            return [{"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                     "width": width, "polarity": polarity}]

        a1 = math.atan2(y1 - cy, x1 - cx)
        a2 = math.atan2(y2 - cy, x2 - cx)

        # Dirección: G02 = horario (CW, ángulo decrece), G03 = antihorario
        if mode == 2:  # CW
            if a2 >= a1:
                a2 -= 2 * math.pi
        else:          # CCW (G03)
            if a2 <= a1:
                a2 += 2 * math.pi

        # Si inicio y fin coinciden (círculo completo), barrer 360°
        if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
            a2 = a1 + (-2 * math.pi if mode == 2 else 2 * math.pi)

        sweep = abs(a2 - a1)
        # Resolución: un segmento cada ~5 grados, mínimo 4
        n = max(4, int(sweep / math.radians(5)))

        segs = []
        px, py = x1, y1
        for k in range(1, n + 1):
            a = a1 + (a2 - a1) * k / n
            nx = cx + r * math.cos(a)
            ny = cy + r * math.sin(a)
            segs.append({"type": "line", "x1": px, "y1": py, "x2": nx, "y2": ny,
                         "width": width, "polarity": polarity})
            px, py = nx, ny
        return segs

    def get_header(self) -> list:
        """Extrae las líneas de cabecera hasta la primera apertura/draw."""
        header = []
        for line in self.raw_lines:
            header.append(line)
            if re.search(r'%ADD\d+', line) or re.search(r'D0?[123]\*', line):
                break
        return header

    def emit_drawables(self, extra_mm: float = 0.0, polarity: str = "D",
                       dcode_start: int = 200) -> list:
        """
        Re-emite la geometría de esta capa como comandos Gerber, opcionalmente
        ensanchada (extra_mm) y con polaridad D (oscura) o C (clara).
        Útil para 'perforar' otra capa con la forma de esta (ventanas).
        """
        unit_div = 25.4 if self.unit == "IN" else 1.0
        fx, fy = self.format_x, self.format_y

        def enc(v, fmt):
            return str(int(round((v / unit_div) * (10 ** fmt[1]))))

        defs = []
        draws = []
        ap_map = {}
        used = set(self.used_apertures)
        dcode = [dcode_start]

        def get_ap(shape, w):
            key = (shape, round(w, 5))
            if key not in ap_map:
                while dcode[0] in used:
                    dcode[0] += 1
                code = dcode[0]; used.add(code); dcode[0] += 1
                ap_map[key] = code
                wv = max(0.01, w + extra_mm) / unit_div
                defs.append(f"%ADD{code}{shape},{wv:.5f}*%")
            return ap_map[key]

        draws.append("%LPC*%" if polarity == "C" else "%LPD*%")
        draws.append("G01*")
        cur = None
        for d in self.drawables:
            if d["type"] == "line":
                code = get_ap("C", d.get("width", 0.15))
                if code != cur:
                    draws.append(f"G54D{code}*"); cur = code
                draws.append(f"G01X{enc(d['x1'],fx)}Y{enc(d['y1'],fy)}D02*")
                draws.append(f"X{enc(d['x2'],fx)}Y{enc(d['y2'],fy)}D01*")
            elif d["type"] == "flash":
                shape = "R" if d.get("shape") == "R" else "C"
                code = get_ap(shape, d.get("sx", 0.15))
                if code != cur:
                    draws.append(f"G54D{code}*"); cur = code
                draws.append(f"X{enc(d['x'],fx)}Y{enc(d['y'],fy)}D03*")
            elif d["type"] == "region":
                draws.append("G36*")
                first = True
                for (px, py) in d["path"]:
                    op = "D02" if first else "D01"
                    draws.append(f"X{enc(px,fx)}Y{enc(py,fy)}{op}*")
                    first = False
                draws.append("G37*")
        return defs + draws

    def export_new_layer(self, overlay_gerber_cmds: list, output_path: str,
                         layer_name: str = "GENERATED"):
        """
        Genera un Gerber NUEVO desde cero (solo el logo), usando el formato
        y unidades de esta capa (típicamente el outline) como base.
        No copia el contenido de la capa, solo hereda formato/unidades.
        """
        ix, dx = self.format_x
        iy, dy = self.format_y
        mo = "MOIN" if self.unit == "IN" else "MOMM"

        header = [
            "G04 ================== GENERATED SILKSCREEN/LAYER ==================*\n",
            f"G04 Layer: {layer_name}*\n",
            "G04 Created by Gerber Silkscreen Editor*\n",
            f"%FSLAX{ix}{dx}Y{iy}{dy}*{mo}*%\n",
            "%IPPOS*%\n",   # imagen positiva
        ]

        body = [cmd + "\n" for cmd in overlay_gerber_cmds]
        footer = ["M02*\n"]

        with open(output_path, "w", encoding="utf-8") as f:
            f.writelines(header + body + footer)

    def export_with_overlay(self, overlay_gerber_cmds: list, output_path: str,
                            position: str = "after"):
        """
        Exporta el Gerber original con el logo insertado.
        position="after": el logo va DESPUÉS de la base (logo encima).
        position="before": el logo va ANTES de la base (base encima del logo).
        """
        lines = list(self.raw_lines)

        block = (["\n", "G04 --- Logo imported by Gerber Silkscreen Editor ---*\n"]
                 + [cmd + "\n" for cmd in overlay_gerber_cmds] + ["\n"])

        if position == "before":
            # Insertar tras la cabecera (después de la última %ADD o el primer dibujo)
            insert_idx = 0
            for i, line in enumerate(lines):
                if re.search(r'D0?[123]\*', line) or re.search(r'G54D\d+', line):
                    insert_idx = i
                    break
            else:
                insert_idx = len(lines)
            new_lines = lines[:insert_idx] + block + lines[insert_idx:]
        else:
            # Insertar justo antes de M02 (logo encima de todo)
            insert_idx = len(lines)
            for i, line in enumerate(lines):
                if re.search(r'M0?2\*', line):
                    insert_idx = i
                    break
            new_lines = lines[:insert_idx] + block + lines[insert_idx:]

        with open(output_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)


# ─────────────────────────────────────────────
#  CONVERSOR IMAGEN → GERBER
# ─────────────────────────────────────────────


def _apply_floyd(arr, thresh):
    import numpy as np
    a = arr.copy(); h, w = a.shape
    out = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            old = a[y, x]; new = 0.0 if old < thresh else 255.0
            out[y, x] = new < 128; err = old - new
            if x+1 < w:   a[y,x+1]   += err * 7/16
            if y+1 < h:
                if x-1 >= 0: a[y+1,x-1] += err * 3/16
                a[y+1,x]   += err * 5/16
                if x+1 < w:  a[y+1,x+1] += err * 1/16
    return out

def _apply_atkinson(arr, thresh):
    import numpy as np
    a = arr.copy(); h, w = a.shape
    out = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            old = a[y, x]; new = 0.0 if old < thresh else 255.0
            out[y, x] = new < 128; err = (old - new) / 8
            for dy, dx in [(0,1),(0,2),(1,-1),(1,0),(1,1),(2,0)]:
                ny, nx = y+dy, x+dx
                if 0 <= ny < h and 0 <= nx < w: a[ny, nx] += err
    return out

def _apply_bayer(arr, n):
    import numpy as np
    def _bm(n):
        if n == 1: return np.array([[0]])
        m = _bm(n//2)
        return np.bmat([[4*m, 4*m+2], [4*m+3, 4*m+1]]).A / (n*n)
    bm = _bm(n) * 255; h, w = arr.shape
    tiled = np.tile(bm, (h//n+1, w//n+1))[:h, :w]
    return arr < tiled

def _apply_error_diffusion(arr, thresh, method):
    import numpy as np
    if method == 'stucki':
        kernel = [(0,1,8),(0,2,4),(1,-2,2),(1,-1,4),(1,0,8),(1,1,4),(1,2,2),(2,-2,1),(2,-1,2),(2,0,4),(2,1,2),(2,2,1)]
        div = 42
    else:  # jarvis
        kernel = [(0,1,7),(0,2,5),(1,-2,3),(1,-1,5),(1,0,7),(1,1,5),(1,2,3),(2,-2,1),(2,-1,3),(2,0,5),(2,1,3),(2,2,1)]
        div = 48
    a = arr.copy(); h, w = a.shape
    out = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            old = a[y,x]; new = 0.0 if old < thresh else 255.0
            out[y,x] = new < 128; err = old - new
            for dy,dx,wt in kernel:
                ny,nx = y+dy, x+dx
                if 0<=ny<h and 0<=nx<w: a[ny,nx] += err * wt / div
    return out


class ImageToGerber:
    """Convierte una imagen PIL a comandos Gerber de líneas/flashes."""

    def __init__(self, layer: GerberLayer):
        self.layer = layer

    def convert(self, img: 'Image', x_mm: float, y_mm: float,
                width_mm: float, height_mm: float,
                threshold: int = 128, dot_size_mm: float = 0.15,
                clearance_mm: float = 0.0, dither_algo: str = 'threshold',
                dither_px_mm: float = None) -> list:
        """
        Convierte imagen a trazos Gerber.
        - dot_size_mm: tamaño de trazo físico en el Gerber (siempre ≥0.15mm para JLCPCB)
        - dither_px_mm: tamaño del 'píxel' para el algoritmo de dithering.
          Si es mayor que dot_size_mm, el dithering se calcula a baja resolución
          y luego se escala al Gerber a 0.15mm, dando un efecto de trama gruesa.
          Si es None, usa dot_size_mm (máxima resolución).
        """
        import numpy as np

        gray = img.convert("L")

        # Resolución de exportación Gerber (trazo físico, mín 0.15mm JLCPCB)
        dot_mm = max(0.15, dot_size_mm)
        exp_cols = max(1, int(round(width_mm / dot_mm)))
        exp_rows = max(1, int(round(height_mm / dot_mm)))
        MAX_PIX = 4_000_000
        if exp_cols * exp_rows > MAX_PIX:
            f = math.sqrt(MAX_PIX / (exp_cols * exp_rows))
            exp_cols = max(1, int(exp_cols * f))
            exp_rows = max(1, int(exp_rows * f))

        # Resolución de dithering (puede ser más gruesa para efecto de trama visible)
        px_mm = max(dot_mm, dither_px_mm) if dither_px_mm else dot_mm
        dith_cols = max(1, int(round(width_mm / px_mm)))
        dith_rows = max(1, int(round(height_mm / px_mm)))

        # 1) Dithering a la resolución del píxel visual
        resized_dith = gray.resize((dith_cols, dith_rows), Image.LANCZOS)
        arr = np.array(resized_dith, dtype=np.float32)

        if dither_algo == 'floyd':
            dark_dith = _apply_floyd(arr, threshold)
        elif dither_algo == 'atkinson':
            dark_dith = _apply_atkinson(arr, threshold)
        elif dither_algo == 'bayer4':
            dark_dith = _apply_bayer(arr, 4)
        elif dither_algo == 'bayer8':
            dark_dith = _apply_bayer(arr, 8)
        elif dither_algo == 'stucki':
            dark_dith = _apply_error_diffusion(arr, threshold, 'stucki')
        elif dither_algo == 'jarvis':
            dark_dith = _apply_error_diffusion(arr, threshold, 'jarvis')
        else:
            dark_dith = arr < threshold

        # 2) Escalar la máscara binaria a resolución de exportación (NEAREST = bloques)
        if dith_cols != exp_cols or dith_rows != exp_rows:
            from PIL import Image as _PILImg
            mask_img = _PILImg.fromarray(dark_dith.astype(np.uint8) * 255, "L")
            mask_img = mask_img.resize((exp_cols, exp_rows), _PILImg.NEAREST)
            dark = np.array(mask_img) > 128
        else:
            dark = dark_dith

        cols, rows = exp_cols, exp_rows
        cell_w = width_mm / cols
        cell_h = height_mm / rows

        fmt_x = self.layer.format_x
        fmt_y = self.layer.format_y
        unit_div = 25.4 if self.layer.unit == "IN" else 1.0

        def enc(val_mm, fmt):
            return str(int(round((val_mm / unit_div) * (10 ** fmt[1]))))

        line_w_mm = max(0.15, cell_h * 1.15)
        # Longitud mínima de un run: al menos igual al ancho de línea
        # para que no se vea como círculo (trazo puntual con apertura grande)
        min_run_mm = line_w_mm

        # Precalcular las rachas (runs) por fila una sola vez
        runs = []  # (cy_enc, cx1_enc, cx2_enc, run_len_mm)
        for row in range(rows):
            py_mm = y_mm + height_mm - (row + 0.5) * cell_h
            cy = enc(py_mm, fmt_y)
            run_dark = dark[row]
            col = 0
            while col < cols:
                if not run_dark[col]:
                    col += 1
                    continue
                start = col
                while col < cols and run_dark[col]:
                    col += 1
                end = col - 1
                run_len_mm = (end - start + 1) * cell_w
                # Descartar runs muy cortos (píxeles sueltos → círculos en el Gerber)
                if run_len_mm < min_run_mm:
                    continue
                x1_mm = x_mm + (start + 0.5) * cell_w
                x2_mm = x_mm + (end + 0.5) * cell_w
                runs.append((cy, enc(x1_mm, fmt_x), enc(x2_mm, fmt_x)))

        def free_dcode(start, used):
            d = start
            while d in used:
                d += 1
            return d

        used = set(self.layer.used_apertures)
        cmds = ["G75*", "G01*"]

        # Apertura del logo
        d_logo = free_dcode(90, used); used.add(d_logo)
        cmds.append(f"%ADD{d_logo}C,{(line_w_mm / unit_div):.5f}*%")

        if clearance_mm > 0:
            # Estrategia: LPD logo limpio, luego LPC dilatado (borra el anillo exterior)
            # → el logo queda como isla de cobre, rodeado de un hueco de clearance_mm
            # sin ningún redibujado que cree anillos.

            # Paso 1: dibujar el logo en oscuro (isla de cobre)
            cmds.append("%LPD*%")
            cmds.append(f"G54D{d_logo}*")
            for cy, cx1, cx2 in runs:
                cmds.append(f"G01X{cx1}Y{cy}D02*")
                cmds.append(f"X{cx2}Y{cy}D01*")

            # Paso 2: borrar el anillo exterior usando apertura dilatada (logo + clearance a cada lado)
            clear_w = (line_w_mm + 2 * clearance_mm) / unit_div
            dc = free_dcode(90, used); used.add(dc)
            cmds.append(f"%ADD{dc}C,{clear_w:.5f}*%")
            cmds.append("%LPC*%")
            cmds.append(f"G54D{dc}*")
            for cy, cx1, cx2 in runs:
                cmds.append(f"G01X{cx1}Y{cy}D02*")
                cmds.append(f"X{cx2}Y{cy}D01*")

            # Paso 3: restaurar el logo que quedó dentro del área borrada
            cmds.append("%LPD*%")
            cmds.append(f"G54D{d_logo}*")
            for cy, cx1, cx2 in runs:
                cmds.append(f"G01X{cx1}Y{cy}D02*")
                cmds.append(f"X{cx2}Y{cy}D01*")

        else:
            # Sin clearance: solo el logo
            cmds.append("%LPD*%")
            cmds.append(f"G54D{d_logo}*")
            for cy, cx1, cx2 in runs:
                cmds.append(f"G01X{cx1}Y{cy}D02*")
                cmds.append(f"X{cx2}Y{cy}D01*")

        return cmds

    def convert_svg_paths(self, svg_path: str, x_mm: float, y_mm: float,
                          width_mm: float, height_mm: float,
                          line_width_mm: float = 0.15) -> list:
        """Convierte SVG a trazos Gerber más precisos."""
        if not SVG_AVAILABLE:
            raise ImportError("svgpathtools no disponible")

        paths, attrs, svg_attribs = svgpathtools.svg2paths2(svg_path)

        # Obtener bounds del SVG
        all_points = []
        for path in paths:
            for seg in path:
                all_points.append(seg.start)
                all_points.append(seg.end)

        if not all_points:
            return []

        svg_xs = [p.real for p in all_points]
        svg_ys = [p.imag for p in all_points]
        svg_xmin, svg_xmax = min(svg_xs), max(svg_xs)
        svg_ymin, svg_ymax = min(svg_ys), max(svg_ys)
        svg_w = svg_xmax - svg_xmin or 1
        svg_h = svg_ymax - svg_ymin or 1

        scale_x = width_mm / svg_w
        scale_y = height_mm / svg_h
        scale = min(scale_x, scale_y)

        fmt_x = self.layer.format_x
        fmt_y = self.layer.format_y
        unit_div = 25.4 if self.layer.unit == "IN" else 1.0

        def encode_coord(val_mm, fmt):
            dec = fmt[1]
            raw = int(round((val_mm / unit_div) * (10 ** dec)))
            return str(raw)

        def svg_to_mm(pt):
            nx = (pt.real - svg_xmin) * scale + x_mm
            ny = y_mm + height_mm - (pt.imag - svg_ymin) * scale
            return nx, ny

        # Código de apertura libre
        dcode = 90
        while dcode in self.layer.used_apertures:
            dcode += 1
        aperture_size = line_width_mm / unit_div

        cmds = []
        cmds.append(f"%ADD{dcode}C,{aperture_size:.5f}*%")
        cmds.append(f"D{dcode}*")
        cmds.append("G01*")

        for path in paths:
            first = True
            for seg in path:
                sx, sy = svg_to_mm(seg.start)
                ex, ey = svg_to_mm(seg.end)
                # Move to start
                if first:
                    cmds.append(f"X{encode_coord(sx, fmt_x)}Y{encode_coord(sy, fmt_y)}D02*")
                    first = False
                cmds.append(f"X{encode_coord(ex, fmt_x)}Y{encode_coord(ey, fmt_y)}D01*")

        return cmds


# ─────────────────────────────────────────────
#  APLICACIÓN PRINCIPAL
# ─────────────────────────────────────────────

class GerberEditor(tk.Tk):

    CANVAS_W = 800
    CANVAS_H = 600
    GRID_COLOR = "#1a2a1a"
    BG_COLOR = "#0d1a0d"
    PCB_COLOR = "#1a3a1a"
    TRACE_COLOR = "#c8a020"
    SILK_COLOR = "#f0f0f0"
    OVERLAY_COLOR = "#00aaff"

    def __init__(self):
        super().__init__()
        self.title("Gerber Silkscreen Editor")
        self.configure(bg="#1e1e2e")
        self.resizable(True, True)

        # Capas Gerber: lista de dicts {layer, name, visible, bbox_only, color, var_visible, var_bbox}
        self.gerber_layers = []
        self.logo_targets = []   # lista de tags de capa destino del logo
        self.gerber_layer = None  # capa activa para exportación/referencia (la primera)
        self.overlay_image = None       # PIL Image
        self.overlay_tk = None          # ImageTk para canvas
        self.overlay_canvas_id = None

        # Parámetros de transformación del overlay (en mm)
        self.overlay_x_mm = 0.0
        self.overlay_y_mm = 0.0
        self.overlay_w_mm = 10.0
        self.overlay_h_mm = 10.0
        self.overlay_angle_deg = 0.0
        self.overlay_threshold = tk.IntVar(value=128)

        # Estado de drag
        self._drag_start = None
        self._drag_overlay_start = None
        self._active_drag = None   # ("move"|"scale"|"rotate"|"corner", data)

        # Cache de imagen procesada para el overlay (evita recalcular en cada frame)
        self._overlay_cache = None        # (thresh, angle, w_px, h_px) -> ImageTk
        self._overlay_cache_key = None
        self._redraw_pending = False      # throttle de redraws durante drag

        # Modo de referencia para alineación: 'pcb' o 'silk'
        self._align_ref = None   # se calcula al usarlo
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._pan_start = None

        self._build_ui()

    # ── UI ──────────────────────────────────────────

    def _build_ui(self):
        # Barra superior
        toolbar = tk.Frame(self, bg="#252535", pady=4)
        toolbar.pack(fill="x")

        btn_style = {"bg": "#3a3a5c", "fg": "white", "relief": "flat",
                     "padx": 10, "pady": 4, "cursor": "hand2",
                     "font": ("Segoe UI", 9)}
        sep_style = {"bg": "#444466", "width": 1}

        tk.Button(toolbar, text="📂 Añadir capa", command=self.open_gerber, **btn_style).pack(side="left", padx=2)
        tk.Button(toolbar, text="🗑 Limpiar capas", command=self.clear_layers, **btn_style).pack(side="left", padx=2)
        tk.Frame(toolbar, **sep_style).pack(side="left", fill="y", padx=2)
        tk.Button(toolbar, text="🖼 Importar Imagen", command=self.import_image, **btn_style).pack(side="left", padx=2)
        tk.Frame(toolbar, **sep_style).pack(side="left", fill="y", padx=2)
        tk.Button(toolbar, text="💾 Exportar Gerber", command=self.export_gerber, **btn_style).pack(side="left", padx=2)
        tk.Button(toolbar, text="✨ Generar capa nueva", command=self.generate_new_layer, **btn_style).pack(side="left", padx=2)
        tk.Frame(toolbar, **sep_style).pack(side="left", fill="y", padx=2)
        tk.Button(toolbar, text="🔍 Ajustar Vista", command=self.fit_view, **btn_style).pack(side="left", padx=2)
        tk.Button(toolbar, text="❌ Eliminar Imagen", command=self.remove_overlay, **btn_style).pack(side="left", padx=2)

        # Info
        self.info_var = tk.StringVar(value="Abre un archivo Gerber para empezar")
        tk.Label(toolbar, textvariable=self.info_var, bg="#252535", fg="#aaaacc",
                 font=("Segoe UI", 8)).pack(side="right", padx=10)
        self.targets_var = tk.StringVar(value="(sin capas destino)")
        tk.Label(toolbar, textvariable=self.targets_var, bg="#252535", fg="#66cc88",
                 font=("Segoe UI", 8)).pack(side="right", padx=10)

        # Layout principal
        main = tk.Frame(self, bg="#1e1e2e")
        main.pack(fill="both", expand=True)

        # Panel izquierdo: controles
        panel = tk.Frame(main, bg="#252535", width=240, padx=8, pady=8)
        panel.pack(side="left", fill="y")
        panel.pack_propagate(False)

        self._build_controls(panel)

        # Canvas
        canvas_frame = tk.Frame(main, bg="#0d1a0d")
        canvas_frame.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Canvas(canvas_frame, bg=self.BG_COLOR,
                                highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        # Bindings canvas
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_press)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_release)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_drag)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_drag)
        self.canvas.bind("<MouseWheel>", self._on_scroll)
        self.canvas.bind("<Button-4>", self._on_scroll)
        self.canvas.bind("<Button-5>", self._on_scroll)
        self.canvas.bind("<Configure>", lambda e: self._safe_redraw())

        # Barra de estado
        status_bar = tk.Frame(self, bg="#151525", pady=2)
        status_bar.pack(fill="x", side="bottom")
        self.coords_var = tk.StringVar(value="X: --  Y: --")
        tk.Label(status_bar, textvariable=self.coords_var, bg="#151525",
                 fg="#556677", font=("Courier", 8)).pack(side="left", padx=8)
        self.canvas.bind("<Motion>", self._update_coords_display)

    def _build_controls(self, parent):
        lbl = {"bg": "#252535", "fg": "#aaaacc", "font": ("Segoe UI", 8), "anchor": "w"}
        entry_style = {"bg": "#1a1a2e", "fg": "white", "insertbackground": "white",
                       "relief": "flat", "font": ("Segoe UI", 9), "width": 10}

        def section(text):
            tk.Label(parent, text=text, bg="#252535", fg="#7777cc",
                     font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", pady=(10, 2))
            tk.Frame(parent, bg="#444466", height=1).pack(fill="x")

        # ── Panel de capas ──────────────────────────
        section("🗂 Capas Gerber")
        self.layers_frame = tk.Frame(parent, bg="#252535")
        self.layers_frame.pack(fill="x", pady=2)
        tk.Label(self.layers_frame, text="(sin capas cargadas)",
                 bg="#252535", fg="#556677", font=("Segoe UI", 7)).pack(anchor="w")

        section("📍 Posición (mm)")
        row = tk.Frame(parent, bg="#252535")
        row.pack(fill="x", pady=2)
        tk.Label(row, text="X:", **lbl, width=4).pack(side="left")
        self.entry_x = tk.Entry(row, **entry_style)
        self.entry_x.insert(0, "0.0")
        self.entry_x.pack(side="left", padx=2)

        row2 = tk.Frame(parent, bg="#252535")
        row2.pack(fill="x", pady=2)
        tk.Label(row2, text="Y:", **lbl, width=4).pack(side="left")
        self.entry_y = tk.Entry(row2, **entry_style)
        self.entry_y.insert(0, "0.0")
        self.entry_y.pack(side="left", padx=2)

        section("📐 Tamaño (mm)")
        row3 = tk.Frame(parent, bg="#252535")
        row3.pack(fill="x", pady=2)
        tk.Label(row3, text="W:", **lbl, width=4).pack(side="left")
        self.entry_w = tk.Entry(row3, **entry_style)
        self.entry_w.insert(0, "10.0")
        self.entry_w.pack(side="left", padx=2)

        row4 = tk.Frame(parent, bg="#252535")
        row4.pack(fill="x", pady=2)
        tk.Label(row4, text="H:", **lbl, width=4).pack(side="left")
        self.entry_h = tk.Entry(row4, **entry_style)
        self.entry_h.insert(0, "10.0")
        self.entry_h.pack(side="left", padx=2)

        # Lock aspect ratio
        self.lock_aspect = tk.BooleanVar(value=True)
        tk.Checkbutton(parent, text="🔒 Mantener proporción",
                       variable=self.lock_aspect, bg="#252535", fg="#aaaacc",
                       selectcolor="#1a1a2e", activebackground="#252535",
                       font=("Segoe UI", 8)).pack(anchor="w", pady=2)

        section("🔄 Rotación")
        row5 = tk.Frame(parent, bg="#252535")
        row5.pack(fill="x", pady=2)
        tk.Label(row5, text="°:", **lbl, width=4).pack(side="left")
        self.entry_rot = tk.Entry(row5, **entry_style)
        self.entry_rot.insert(0, "0.0")
        self.entry_rot.pack(side="left", padx=2)

        rot_btns = tk.Frame(parent, bg="#252535")
        rot_btns.pack(fill="x", pady=2)
        for deg, txt in [(-90, "↺ -90°"), (-45, "-45°"), (45, "+45°"), (90, "↻ +90°")]:
            tk.Button(rot_btns, text=txt, command=lambda d=deg: self._rotate_by(d),
                      bg="#3a3a5c", fg="white", relief="flat",
                      font=("Segoe UI", 7), padx=3).pack(side="left", padx=1)

        section("🎚 Umbral B/N")
        tk.Scale(parent, variable=self.overlay_threshold, from_=0, to=255,
                 orient="horizontal", bg="#252535", fg="white", troughcolor="#1a1a2e",
                 highlightthickness=0,
                 command=lambda v: (setattr(self, '_overlay_cache_key', None), self._redraw())
                 ).pack(fill="x")

        section("⚙ Tamaño punto (mm)")
        self.dot_size_var = tk.DoubleVar(value=0.15)
        row6 = tk.Frame(parent, bg="#252535")
        row6.pack(fill="x", pady=2)
        tk.Label(row6, text="Dot:", **lbl, width=4).pack(side="left")
        self.entry_dot = tk.Entry(row6, **entry_style)
        self.entry_dot.insert(0, "0.15")
        self.entry_dot.pack(side="left", padx=2)

        # Aplicar botón
        tk.Button(parent, text="✓ Aplicar cambios", command=self._apply_controls,
                  bg="#2244aa", fg="white", relief="flat",
                  font=("Segoe UI", 9, "bold"), pady=6).pack(fill="x", pady=(12, 2))
        tk.Button(parent, text="🔬 Editor de conversión", command=self._open_conversion_editor,
                  bg="#334455", fg="#aaddff", relief="flat",
                  font=("Segoe UI", 8), pady=4).pack(fill="x", pady=(0, 4))

        # ── Ajuste y alineación ──────────────────────
        section("📏 Referencia de alineación")
        self.align_ref_var = tk.StringVar(value="pcb")
        ref_row = tk.Frame(parent, bg="#252535")
        ref_row.pack(fill="x", pady=2)
        for txt, val in [("PCB outline", "pcb"), ("Silk bbox", "silk")]:
            tk.Radiobutton(ref_row, text=txt, variable=self.align_ref_var, value=val,
                           bg="#252535", fg="#aaaacc", selectcolor="#1a1a2e",
                           activebackground="#252535",
                           font=("Segoe UI", 8)).pack(side="left", padx=4)

        section("↔ Ajuste de tamaño")
        fit_btns = [
            ("⬛ Llenar ref.",   self._fit_fill),
            ("🔲 Ajustar (fit)", self._fit_contain),
            ("↔ Ajustar ancho", self._fit_width),
            ("↕ Ajustar alto",  self._fit_height),
        ]
        for txt, cmd in fit_btns:
            tk.Button(parent, text=txt, command=cmd,
                      bg="#2a3a4a", fg="white", relief="flat",
                      font=("Segoe UI", 8), pady=3, anchor="w", padx=6
                      ).pack(fill="x", pady=1)

        section("⊹ Centrar")
        center_row = tk.Frame(parent, bg="#252535")
        center_row.pack(fill="x", pady=2)
        tk.Button(center_row, text="↔ H", command=self._center_h,
                  bg="#2a3a4a", fg="white", relief="flat",
                  font=("Segoe UI", 8), padx=6).pack(side="left", expand=True, fill="x", padx=1)
        tk.Button(center_row, text="↕ V", command=self._center_v,
                  bg="#2a3a4a", fg="white", relief="flat",
                  font=("Segoe UI", 8), padx=6).pack(side="left", expand=True, fill="x", padx=1)
        tk.Button(center_row, text="✛ Ambos", command=self._center_both,
                  bg="#2a3a4a", fg="white", relief="flat",
                  font=("Segoe UI", 8), padx=6).pack(side="left", expand=True, fill="x", padx=1)

        section("📌 Alinear a borde")
        # Fila arriba/abajo con margen
        align_top_row = tk.Frame(parent, bg="#252535")
        align_top_row.pack(fill="x", pady=1)
        tk.Button(align_top_row, text="⬆ Arriba", command=lambda: self._align_edge("top"),
                  bg="#2a3a4a", fg="white", relief="flat",
                  font=("Segoe UI", 8)).pack(side="left", expand=True, fill="x", padx=1)
        tk.Button(align_top_row, text="⬇ Abajo", command=lambda: self._align_edge("bottom"),
                  bg="#2a3a4a", fg="white", relief="flat",
                  font=("Segoe UI", 8)).pack(side="left", expand=True, fill="x", padx=1)

        align_lr_row = tk.Frame(parent, bg="#252535")
        align_lr_row.pack(fill="x", pady=1)
        tk.Button(align_lr_row, text="⬅ Izq", command=lambda: self._align_edge("left"),
                  bg="#2a3a4a", fg="white", relief="flat",
                  font=("Segoe UI", 8)).pack(side="left", expand=True, fill="x", padx=1)
        tk.Button(align_lr_row, text="➡ Der", command=lambda: self._align_edge("right"),
                  bg="#2a3a4a", fg="white", relief="flat",
                  font=("Segoe UI", 8)).pack(side="left", expand=True, fill="x", padx=1)

        # Margen para alineación de borde
        margin_row = tk.Frame(parent, bg="#252535")
        margin_row.pack(fill="x", pady=2)
        tk.Label(margin_row, text="Margen:", **lbl, width=7).pack(side="left")
        self.entry_margin = tk.Entry(margin_row, **entry_style)
        self.entry_margin.insert(0, "1.0")
        self.entry_margin.pack(side="left", padx=2)
        tk.Label(margin_row, text="mm", **lbl).pack(side="left")

        # Modo interacción
        section("🖱 Modo arrastre")
        self.drag_mode = tk.StringVar(value="move")
        modes = [("Mover", "move"), ("Escalar", "scale"), ("Rotar", "rotate")]
        for txt, val in modes:
            tk.Radiobutton(parent, text=txt, variable=self.drag_mode, value=val,
                           bg="#252535", fg="#aaaacc", selectcolor="#1a1a2e",
                           activebackground="#252535",
                           font=("Segoe UI", 8)).pack(anchor="w")

        self.file_info_var = tk.StringVar(value="")

    # ── Capas ──────────────────────────────────────

    LAYER_COLORS = ["#f0f0f0", "#ffcc44", "#44ddff", "#ff6644",
                    "#88ff44", "#ff44cc", "#44ffaa", "#ffaa44"]

    def open_gerber(self):
        filepaths = filedialog.askopenfilenames(
            title="Añadir capas Gerber",
            filetypes=[
                ("Archivos Gerber", "*.gbr *.gtl *.gbl *.gts *.gbs *.gto *.gbo *.ger *.art *.top *.bot"),
                ("Todos los archivos", "*.*")
            ]
        )
        if not filepaths:
            return
        for filepath in filepaths:
            try:
                layer = GerberLayer().load(filepath)
                color = self.LAYER_COLORS[len(self.gerber_layers) % len(self.LAYER_COLORS)]
                self.gerber_layers.append({
                    "layer": layer,
                    "name": Path(filepath).name,
                    "color": color,
                    "var_visible": tk.BooleanVar(value=True),
                    "var_bbox": tk.BooleanVar(value=False),
                })
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo cargar {Path(filepath).name}:\n{e}")
        if self.gerber_layers:
            self.gerber_layer = self.gerber_layers[0]["layer"]
        self._rebuild_layers_panel()
        self.fit_view()
        self._redraw()
        self.info_var.set(f"{len(self.gerber_layers)} capa(s) cargada(s)")

    def clear_layers(self):
        self.gerber_layers.clear()
        self.gerber_layer = None
        self._rebuild_layers_panel()
        self._redraw()

    def _rebuild_layers_panel(self):
        for w in self.layers_frame.winfo_children():
            w.destroy()
        if not self.gerber_layers:
            tk.Label(self.layers_frame, text="(sin capas cargadas)",
                     bg="#252535", fg="#556677", font=("Segoe UI", 7)).pack(anchor="w")
            return
        for entry in self.gerber_layers:
            row = tk.Frame(self.layers_frame, bg="#252535")
            row.pack(fill="x", pady=1)
            tk.Label(row, text="■", bg="#252535", fg=entry["color"],
                     font=("Segoe UI", 9)).pack(side="left")
            tk.Checkbutton(row, variable=entry["var_visible"], command=self._redraw,
                           bg="#252535", fg="#cccccc", selectcolor="#1a1a2e",
                           activebackground="#252535", font=("Segoe UI", 7)).pack(side="left")
            name = entry["name"][:20] + "…" if len(entry["name"]) > 20 else entry["name"]
            tk.Label(row, text=name, bg="#252535", fg="#aaaacc",
                     font=("Segoe UI", 7), anchor="w").pack(side="left", fill="x", expand=True)
            tk.Checkbutton(row, text="bbox", variable=entry["var_bbox"], command=self._redraw,
                           bg="#252535", fg="#ffcc44", selectcolor="#1a1a2e",
                           activebackground="#252535", font=("Segoe UI", 6)).pack(side="right")
        tk.Label(self.layers_frame, text="✓=visible  bbox=solo contorno",
                 bg="#252535", fg="#556677", font=("Segoe UI", 6)).pack(anchor="w", pady=(3,0))

    # ── Apertura / Importación ─────────────────────

    def import_image(self):
        if not PIL_AVAILABLE:
            messagebox.showerror("Error", "Pillow no está instalado.")
            return

        filepath = filedialog.askopenfilename(
            title="Importar imagen",
            filetypes=[
                ("Imágenes", "*.png *.jpg *.jpeg *.bmp *.gif *.svg"),
                ("PNG", "*.png"), ("JPEG", "*.jpg *.jpeg"),
                ("SVG", "*.svg"), ("Todos", "*.*")
            ]
        )
        if not filepath:
            return

        ext = Path(filepath).suffix.lower()

        if ext == ".svg":
            # Para SVG: renderizamos como imagen de preview con Pillow
            # pero guardamos el path para exportar trazos precisos
            self.overlay_svg_path = filepath
            try:
                import subprocess
                # Intentar convertir SVG a PNG con inkscape si está disponible
                tmp = "/tmp/svg_preview.png"
                result = subprocess.run(
                    ["inkscape", "--export-type=png", f"--export-filename={tmp}",
                     "--export-width=512", filepath],
                    capture_output=True, timeout=10
                )
                if result.returncode == 0:
                    img = Image.open(tmp)
                else:
                    raise RuntimeError("Inkscape no disponible")
            except Exception:
                # Fallback: crear imagen placeholder con texto
                img = Image.new("RGBA", (200, 200), (255, 255, 255, 0))
                from PIL import ImageDraw
                draw = ImageDraw.Draw(img)
                draw.rectangle([10, 10, 190, 190], outline=(0, 0, 0, 255), width=3)
                draw.text((100, 100), "SVG\n(preview\nnot available)", fill=(0, 0, 0, 255), anchor="mm")
                messagebox.showinfo("SVG", "SVG cargado. El preview es aproximado.\nLa exportación usará trazos vectoriales precisos.")
        else:
            self.overlay_svg_path = None
            img = Image.open(filepath).convert("RGBA")

        self.overlay_image = img
        self.overlay_image_path = filepath

        # Inicializar posición en el centro del Gerber
        if self.gerber_layers:
            b = self._get_all_bounds()
            cx = (b[0] + b[2]) / 2
            cy = (b[1] + b[3]) / 2
            # Tamaño inicial: 20% del ancho del Gerber
            init_w = (b[2] - b[0]) * 0.2
            init_h = init_w * img.height / img.width
            self.overlay_x_mm = cx - init_w / 2
            self.overlay_y_mm = cy - init_h / 2
            self.overlay_w_mm = init_w
            self.overlay_h_mm = init_h
        else:
            self.overlay_x_mm = 0.0
            self.overlay_y_mm = 0.0
            self.overlay_w_mm = 10.0
            self.overlay_h_mm = img.height / img.width * 10.0

        self.overlay_angle_deg = 0.0
        self._sync_controls_to_state()
        self._redraw()
        self.info_var.set(f"Imagen importada: {Path(filepath).name}  |  Arrastra para posicionar")

        # Preguntar a qué capa(s) destino va el logo
        self._choose_logo_layers()

    def remove_overlay(self):
        self.overlay_image = None
        self.overlay_canvas_id = None
        self._redraw()

    # ── Métodos de alineación y ajuste ─────────────

    def _get_ref_bounds(self):
        """Retorna (xmin, ymin, xmax, ymax) según la referencia seleccionada."""
        if not self.gerber_layers:
            messagebox.showwarning("Aviso", "Primero carga un archivo Gerber.")
            return None
        if self.align_ref_var.get() == "silk":
            # Bounding box de las primitivas de todas las capas visibles
            xs, ys = [], []
            for entry in self.gerber_layers:
                if not entry["var_visible"].get():
                    continue
                for d in entry["layer"].drawables:
                    if d["type"] == "line":
                        xs += [d["x1"], d["x2"]]; ys += [d["y1"], d["y2"]]
                    elif d["type"] == "flash":
                        xs.append(d["x"]); ys.append(d["y"])
                    elif d["type"] == "region":
                        for px, py in d["path"]:
                            xs.append(px); ys.append(py)
            if xs:
                return (min(xs), min(ys), max(xs), max(ys))
        return self._get_all_bounds()

    def _require_overlay(self):
        if not self.overlay_image:
            messagebox.showwarning("Aviso", "Primero importa una imagen.")
            return False
        return True

    def _aspect_ratio(self):
        """Proporción h/w de la imagen original (independiente del tamaño actual)."""
        img = self.overlay_image
        return img.height / img.width if img.width else 1.0

    # Ajuste de tamaño ──────────────────────────────

    def _fit_fill(self):
        """Escala la imagen para cubrir completamente la referencia (sin franjas)."""
        if not self._require_overlay(): return
        ref = self._get_ref_bounds()
        if not ref: return
        rw, rh = ref[2] - ref[0], ref[3] - ref[1]
        ar = self._aspect_ratio()          # h/w de la imagen
        # Escala por ancho y por alto, elegir la MAYOR (cover)
        scale_w = rw                       # ancho imagen = rw → h = rw*ar
        scale_h = rh / ar                  # alto imagen = rh → w = rh/ar
        if scale_w >= scale_h:             # escalar por ancho cubre más
            self.overlay_w_mm = rw
            self.overlay_h_mm = rw * ar
        else:
            self.overlay_h_mm = rh
            self.overlay_w_mm = rh / ar
        self.overlay_x_mm = ref[0] + (rw - self.overlay_w_mm) / 2
        self.overlay_y_mm = ref[1] + (rh - self.overlay_h_mm) / 2
        self._finish_align()

    def _fit_contain(self):
        """Escala la imagen para que quepa completamente (con posible franjas)."""
        if not self._require_overlay(): return
        ref = self._get_ref_bounds()
        if not ref: return
        rw, rh = ref[2] - ref[0], ref[3] - ref[1]
        ar = self._aspect_ratio()
        # Escala por ancho y por alto, elegir la MENOR (contain)
        scale_w = rw                       # w = rw → h = rw*ar
        scale_h = rh / ar                  # h = rh → w = rh/ar
        if scale_w <= scale_h:             # escalar por ancho es más pequeño
            self.overlay_w_mm = rw
            self.overlay_h_mm = rw * ar
        else:
            self.overlay_h_mm = rh
            self.overlay_w_mm = rh / ar
        self.overlay_x_mm = ref[0] + (rw - self.overlay_w_mm) / 2
        self.overlay_y_mm = ref[1] + (rh - self.overlay_h_mm) / 2
        self._finish_align()

    def _fit_width(self):
        """Ajusta la imagen al ancho de la referencia, manteniendo proporción."""
        if not self._require_overlay(): return
        ref = self._get_ref_bounds()
        if not ref: return
        rw = ref[2] - ref[0]
        self.overlay_w_mm = rw
        self.overlay_h_mm = rw * self._aspect_ratio()
        self.overlay_x_mm = ref[0]
        self._finish_align()

    def _fit_height(self):
        """Ajusta la imagen al alto de la referencia, manteniendo proporción."""
        if not self._require_overlay(): return
        ref = self._get_ref_bounds()
        if not ref: return
        rh = ref[3] - ref[1]
        self.overlay_h_mm = rh
        self.overlay_w_mm = rh / self._aspect_ratio()
        self.overlay_y_mm = ref[1]
        self._finish_align()

    # Centrado ──────────────────────────────────────

    def _center_h(self):
        """Centra horizontalmente respecto a la referencia."""
        if not self._require_overlay(): return
        ref = self._get_ref_bounds()
        if not ref: return
        self.overlay_x_mm = ref[0] + (ref[2] - ref[0] - self.overlay_w_mm) / 2
        self._finish_align()

    def _center_v(self):
        """Centra verticalmente respecto a la referencia."""
        if not self._require_overlay(): return
        ref = self._get_ref_bounds()
        if not ref: return
        self.overlay_y_mm = ref[1] + (ref[3] - ref[1] - self.overlay_h_mm) / 2
        self._finish_align()

    def _center_both(self):
        """Centra en ambos ejes."""
        if not self._require_overlay(): return
        ref = self._get_ref_bounds()
        if not ref: return
        self.overlay_x_mm = ref[0] + (ref[2] - ref[0] - self.overlay_w_mm) / 2
        self.overlay_y_mm = ref[1] + (ref[3] - ref[1] - self.overlay_h_mm) / 2
        self._finish_align()

    # Alineación a borde ────────────────────────────

    def _align_edge(self, edge: str):
        """Alinea la imagen al borde indicado con el margen configurado."""
        if not self._require_overlay(): return
        ref = self._get_ref_bounds()
        if not ref: return
        try:
            margin = float(self.entry_margin.get())
        except ValueError:
            margin = 0.0

        if edge == "left":
            self.overlay_x_mm = ref[0] + margin
        elif edge == "right":
            self.overlay_x_mm = ref[2] - self.overlay_w_mm - margin
        elif edge == "bottom":
            self.overlay_y_mm = ref[1] + margin
        elif edge == "top":
            self.overlay_y_mm = ref[3] - self.overlay_h_mm - margin
        self._finish_align()

    def _finish_align(self):
        """Sync controles, invalidar cache y redibujar. No toca zoom ni pan."""
        self._overlay_cache_key = None
        self._sync_controls_to_state()
        self._redraw()
        self._flash_ref_bounds()

    def _flash_ref_bounds(self):
        """Dibuja brevemente el rectángulo de referencia en amarillo para feedback."""
        ref = self._get_ref_bounds()
        if not ref:
            return
        x1c, y1c = self._mm_to_canvas(ref[0], ref[1])
        x2c, y2c = self._mm_to_canvas(ref[2], ref[3])
        rect_id = self.canvas.create_rectangle(
            x1c, y1c, x2c, y2c,
            outline="#ffcc00", width=2, dash=(6, 3), tags="ref_flash"
        )
        # Eliminar tras 800ms
        self.after(800, lambda: self.canvas.delete("ref_flash"))

    # ── Controles ──────────────────────────────────

    def _apply_controls(self):
        try:
            self.overlay_x_mm = float(self.entry_x.get())
            self.overlay_y_mm = float(self.entry_y.get())
            self.overlay_w_mm = float(self.entry_w.get())
            self.overlay_h_mm = float(self.entry_h.get())
            self.overlay_angle_deg = float(self.entry_rot.get())
            self._redraw()
        except ValueError:
            messagebox.showerror("Error", "Valores numéricos inválidos")

    def _sync_controls_to_state(self):
        for entry, val in [
            (self.entry_x, self.overlay_x_mm),
            (self.entry_y, self.overlay_y_mm),
            (self.entry_w, self.overlay_w_mm),
            (self.entry_h, self.overlay_h_mm),
            (self.entry_rot, self.overlay_angle_deg),
        ]:
            entry.delete(0, tk.END)
            entry.insert(0, f"{val:.3f}")

    def _rotate_by(self, deg):
        self.overlay_angle_deg = (self.overlay_angle_deg + deg) % 360
        self._sync_controls_to_state()
        self._redraw()

    # ── Coordenadas canvas ↔ mm ─────────────────────

    def _mm_to_canvas(self, x_mm, y_mm):
        """Convierte coordenadas mm a píxeles del canvas."""
        if not self.gerber_layers:
            return x_mm * 10, y_mm * 10
        b = self._get_all_bounds()
        w = self.canvas.winfo_width() or self.CANVAS_W
        h = self.canvas.winfo_height() or self.CANVAS_H
        gw = b[2] - b[0] or 1
        gh = b[3] - b[1] or 1
        base_scale = min(w / gw, h / gh) * 0.85
        scale = base_scale * self.zoom
        cx = w / 2 + self.pan_x
        cy = h / 2 + self.pan_y
        gx = (x_mm - b[0]) * scale - gw * scale / 2
        gy = -(y_mm - b[1]) * scale + gh * scale / 2
        return cx + gx, cy + gy

    def _canvas_to_mm(self, px, py):
        """Convierte píxeles del canvas a mm."""
        if not self.gerber_layers:
            return px / 10, py / 10
        b = self._get_all_bounds()
        w = self.canvas.winfo_width() or self.CANVAS_W
        h = self.canvas.winfo_height() or self.CANVAS_H
        gw = b[2] - b[0] or 1
        gh = b[3] - b[1] or 1
        base_scale = min(w / gw, h / gh) * 0.85
        scale = base_scale * self.zoom
        cx = w / 2 + self.pan_x
        cy = h / 2 + self.pan_y
        x_mm = (px - cx + gw * scale / 2) / scale + b[0]
        y_mm = -(py - cy - gh * scale / 2) / scale + b[1]
        return x_mm, y_mm

    def _get_mm_scale(self):
        """Retorna píxeles por mm en la vista actual."""
        if not self.gerber_layers:
            return 10
        b = self._get_all_bounds()
        w = self.canvas.winfo_width() or self.CANVAS_W
        h = self.canvas.winfo_height() or self.CANVAS_H
        gw = b[2] - b[0] or 1
        gh = b[3] - b[1] or 1
        base_scale = min(w / gw, h / gh) * 0.85
        return base_scale * self.zoom

    # ── Dibujo ─────────────────────────────────────

    def _safe_redraw(self):
        """Redraw protegido: ignora llamadas antes de que __init__ termine."""
        if not hasattr(self, 'zoom'):
            return
        self._redraw()

    def _redraw(self):
        self.canvas.delete("all")
        self._draw_grid()
        for entry in self.gerber_layers:
            if entry["var_visible"].get():
                self._draw_layer_entry(entry, fast=False)
        if self.overlay_image:
            self._draw_overlay()

    def _draw_grid(self):
        w = self.canvas.winfo_width() or self.CANVAS_W
        h = self.canvas.winfo_height() or self.CANVAS_H
        step = max(20, int(30 * self.zoom))
        for x in range(0, w, step):
            self.canvas.create_line(x, 0, x, h, fill=self.GRID_COLOR, width=1)
        for y in range(0, h, step):
            self.canvas.create_line(0, y, w, y, fill=self.GRID_COLOR, width=1)

    def _draw_gerber(self):
        """Compatibilidad: dibuja la capa activa."""
        if self.gerber_layer:
            entry = next((e for e in self.gerber_layers if e["layer"] is self.gerber_layer), None)
            if entry:
                self._draw_layer_entry(entry, fast=False)

    def _dim_color(self, hex_color, factor=0.45):
        """Devuelve una versión más oscura del color (para el relleno de copper pour)."""
        h = hex_color.lstrip("#")
        if len(h) != 6:
            return hex_color
        r, g, bch = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        r = int(r * factor); g = int(g * factor); bch = int(bch * factor)
        return f"#{r:02x}{g:02x}{bch:02x}"

    def _draw_layer_entry(self, entry, fast=False):
        layer = entry["layer"]
        color = entry["color"]
        dim = self._dim_color(color)        # tono apagado para el plano de masa
        scale = self._get_mm_scale()
        min_px = 1.0

        # Siempre dibujar el bbox
        b = layer.bounds
        x1c, y1c = self._mm_to_canvas(b[0], b[1])
        x2c, y2c = self._mm_to_canvas(b[2], b[3])
        self.canvas.create_rectangle(x1c, y1c, x2c, y2c,
                                     outline=color, width=1, dash=(4, 4))

        if entry["var_bbox"].get():
            return  # solo bbox

        drawables = layer.drawables
        step = max(1, len(drawables) // 250) if fast else 1

        # PASO 1: dibujar primero los rellenos de región (copper pour) en tono apagado,
        # con un borde fino del color brillante para marcar el contorno del plano.
        if not fast:
            for d in drawables:
                if d["type"] == "region":
                    pts = []
                    for (mx, my) in d["path"]:
                        cx, cy = self._mm_to_canvas(mx, my)
                        pts.extend([cx, cy])
                    if len(pts) >= 6:
                        self.canvas.create_polygon(pts, fill=dim,
                                                   outline=color, width=1)

        # PASO 2: pistas y flashes en el color brillante, encima del plano
        for i, d in enumerate(drawables):
            if fast and i % step != 0:
                continue
            if d["type"] == "line":
                x1c, y1c = self._mm_to_canvas(d["x1"], d["y1"])
                x2c, y2c = self._mm_to_canvas(d["x2"], d["y2"])
                w_px = max(min_px, d["width"] * scale) if not fast else 1
                self.canvas.create_line(x1c, y1c, x2c, y2c,
                                        fill=color, width=w_px, capstyle="round")
            elif d["type"] == "flash" and not fast:
                xc, yc = self._mm_to_canvas(d["x"], d["y"])
                sx = max(min_px, d["sx"] * scale / 2)
                sy = max(min_px, d["sy"] * scale / 2)
                if d["shape"] == "R":
                    self.canvas.create_rectangle(xc-sx, yc-sy, xc+sx, yc+sy,
                                                 fill=color, outline="")
                else:
                    self.canvas.create_oval(xc-sx, yc-sy, xc+sx, yc+sy,
                                            fill=color, outline="")

    def _make_overlay_image(self, disp_w: int, disp_h: int, thresh: int, angle: float):
        """
        Genera la imagen RGBA del overlay al TAMAÑO EXACTO de display (disp_w x disp_h),
        para que coincida pixel a pixel con el marco. El procesado numpy se hace a
        resolución reducida (rápido) y luego se escala al tamaño real.
        """
        import numpy as np

        disp_w = max(4, int(disp_w))
        disp_h = max(4, int(disp_h))

        # Resolución de procesado: capada para que numpy sea rápido
        PROC_CAP = 600
        pw = max(4, min(disp_w, PROC_CAP))
        ph = max(4, min(disp_h, PROC_CAP))

        src = self.overlay_image.convert("L")
        small = src.resize((pw, ph), Image.BILINEAR)
        arr = np.array(small, dtype=np.uint8)
        mask = arr < thresh

        rgba_arr = np.zeros((ph, pw, 4), dtype=np.uint8)
        rgba_arr[mask] = [0, 170, 255, 210]
        rgba = Image.fromarray(rgba_arr, "RGBA")

        # Escalar al tamaño de display real → coincide exactamente con el marco
        if (pw, ph) != (disp_w, disp_h):
            rgba = rgba.resize((disp_w, disp_h), Image.NEAREST)

        # Rotar al final
        if angle % 360 != 0:
            rgba = rgba.rotate(-angle, expand=True, resample=Image.NEAREST)

        return rgba

    def _draw_overlay(self):
        if not self.overlay_image:
            return

        scale = self._get_mm_scale()
        thresh = self.overlay_threshold.get()
        angle = self.overlay_angle_deg

        # Tamaño REAL de display en píxeles canvas (debe coincidir con el marco)
        disp_w = max(4, int(self.overlay_w_mm * scale))
        disp_h = max(4, int(self.overlay_h_mm * scale))
        # Límite de seguridad para no crear imágenes gigantescas con mucho zoom
        MAX_DISP = 3000
        disp_w = min(disp_w, MAX_DISP)
        disp_h = min(disp_h, MAX_DISP)

        cache_key = (thresh, round(angle, 1), disp_w, disp_h)
        if cache_key != self._overlay_cache_key:
            rgba = self._make_overlay_image(disp_w, disp_h, thresh, angle)
            self._overlay_tk_cache = ImageTk.PhotoImage(rgba)
            self._overlay_cache_key = cache_key

        # Centro del overlay en mm → píxeles canvas
        cx_mm = self.overlay_x_mm + self.overlay_w_mm / 2
        cy_mm = self.overlay_y_mm + self.overlay_h_mm / 2
        cx_px, cy_px = self._mm_to_canvas(cx_mm, cy_mm)

        # La imagen rotada puede tener tamaño diferente al original (expand=True)
        # Colocamos por el centro
        img_w = self._overlay_tk_cache.width()
        img_h = self._overlay_tk_cache.height()

        self.overlay_tk = self._overlay_tk_cache
        self.overlay_canvas_id = self.canvas.create_image(
            cx_px, cy_px,
            image=self.overlay_tk, anchor="center", tags="overlay"
        )

        # Bounding box rotado: calculamos las 4 esquinas del rectángulo original
        # y las rotamos alrededor del centro
        rad = math.radians(-angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        hw = self.overlay_w_mm / 2
        hh = self.overlay_h_mm / 2
        corners_mm = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
        pts = []
        for (dx, dy) in corners_mm:
            # Rotar
            rx = dx * cos_a - dy * sin_a
            ry = dx * sin_a + dy * cos_a
            # Trasladar al centro y convertir a canvas
            px, py = self._mm_to_canvas(cx_mm + rx, cy_mm + ry)
            pts.extend([px, py])

        self.canvas.create_polygon(pts, outline=self.OVERLAY_COLOR, fill="",
                                   width=1, dash=(3, 3), tags="overlay_border")

        # Handles en las 4 esquinas rotadas
        hs = 6
        for i in range(4):
            hx, hy = pts[i*2], pts[i*2+1]
            self.canvas.create_rectangle(hx - hs, hy - hs, hx + hs, hy + hs,
                                         fill=self.OVERLAY_COLOR, outline="white",
                                         tags="overlay_handle")
        # Punto central (para rotar)
        self.canvas.create_oval(cx_px - 5, cy_px - 5, cx_px + 5, cy_px + 5,
                                fill="#ff5500", outline="white", tags="overlay_center")

    # ── Interacción ────────────────────────────────

    def _get_overlay_corners(self):
        """Devuelve las 4 esquinas del overlay en píxeles canvas (ya rotadas)."""
        angle = self.overlay_angle_deg
        rad = math.radians(-angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        cx_mm = self.overlay_x_mm + self.overlay_w_mm / 2
        cy_mm = self.overlay_y_mm + self.overlay_h_mm / 2
        hw, hh = self.overlay_w_mm / 2, self.overlay_h_mm / 2
        corners = []
        for dx, dy in [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]:
            rx = dx * cos_a - dy * sin_a
            ry = dx * sin_a + dy * cos_a
            px, py = self._mm_to_canvas(cx_mm + rx, cy_mm + ry)
            corners.append((px, py))
        return corners  # 0=BL, 1=BR, 2=TR, 3=TL (índices coinciden con _corner_mm)

    def _hit_corner(self, mx, my, radius=18):
        """Retorna índice de esquina cercana al punto (mx,my) o -1 si ninguna."""
        if not self.overlay_image:
            return -1
        for i, (cx, cy) in enumerate(self._get_overlay_corners()):
            if abs(mx - cx) <= radius and abs(my - cy) <= radius:
                return i
        return -1

    def _hit_overlay(self, mx, my):
        """True si el punto está dentro del bounding box del overlay."""
        if not self.overlay_image:
            return False
        corners = self._get_overlay_corners()
        # Ray casting simple sobre el polígono
        n = len(corners)
        inside = False
        x, y = mx, my
        j = n - 1
        for i in range(n):
            xi, yi = corners[i]
            xj, yj = corners[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    def _corner_mm(self, idx):
        """Posición en mm de la esquina idx, YA ROTADA. 0=BL,1=BR,2=TR,3=TL."""
        angle = self.overlay_angle_deg
        rad = math.radians(-angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        cx = self.overlay_x_mm + self.overlay_w_mm / 2
        cy = self.overlay_y_mm + self.overlay_h_mm / 2
        hw, hh = self.overlay_w_mm / 2, self.overlay_h_mm / 2
        offs = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)][idx]
        rx = offs[0] * cos_a - offs[1] * sin_a
        ry = offs[0] * sin_a + offs[1] * cos_a
        return (cx + rx, cy + ry)

    def _on_mouse_press(self, event):
        if not self.overlay_image:
            return
        corner = self._hit_corner(event.x, event.y)
        if corner >= 0:
            # Guardar la esquina OPUESTA en mm (queda fija durante el escalado)
            opp_map = {0: 2, 1: 3, 2: 0, 3: 1}
            fixed_mm = self._corner_mm(opp_map[corner])
            self._active_drag = ("corner", (corner, fixed_mm))
        elif self._hit_overlay(event.x, event.y):
            self._active_drag = (self.drag_mode.get(), None)
        else:
            self._active_drag = None
            return
        self._drag_start = (event.x, event.y)
        self._drag_overlay_start = (self.overlay_x_mm, self.overlay_y_mm,
                                    self.overlay_w_mm, self.overlay_h_mm,
                                    self.overlay_angle_deg)

    def _on_mouse_drag(self, event):
        if not self.overlay_image or not self._drag_start or not self._active_drag:
            return

        dx_px = event.x - self._drag_start[0]
        dy_px = event.y - self._drag_start[1]
        scale = self._get_mm_scale()
        dx_mm = dx_px / scale
        dy_mm = -dy_px / scale
        ox, oy, ow, oh, oa = self._drag_overlay_start
        drag_type, drag_data = self._active_drag

        if drag_type == "move":
            self.overlay_x_mm = ox + dx_mm
            self.overlay_y_mm = oy + dy_mm

        elif drag_type == "scale":
            new_w = max(1.0, ow + dx_mm)
            if self.lock_aspect.get():
                new_h = new_w * (oh / ow if ow else 1)
            else:
                new_h = max(1.0, oh + dy_mm)
            self.overlay_w_mm = new_w
            self.overlay_h_mm = new_h

        elif drag_type == "rotate":
            cx_mm = ox + ow / 2
            cy_mm = oy + oh / 2
            cx_px, cy_px = self._mm_to_canvas(cx_mm, cy_mm)
            angle = math.degrees(math.atan2(event.y - cy_px, event.x - cx_px))
            angle0 = math.degrees(math.atan2(self._drag_start[1] - cy_px,
                                              self._drag_start[0] - cx_px))
            self.overlay_angle_deg = (oa + angle - angle0) % 360

        elif drag_type == "corner":
            # Escalado correcto incluso con rotación: se trabaja en el sistema LOCAL
            # de la imagen (sin rotar), manteniendo la esquina opuesta fija en el mundo.
            corner_idx, fixed_mm = drag_data
            fx, fy = fixed_mm
            mx_mm, my_mm = self._canvas_to_mm(event.x, event.y)

            # Signos de la esquina FIJA (la opuesta a la arrastrada) en local
            fixed_idx = {0: 2, 1: 3, 2: 0, 3: 1}[corner_idx]
            sfx = 1.0 if fixed_idx in (1, 2) else -1.0
            sfy = 1.0 if fixed_idx in (2, 3) else -1.0

            # Rotación de la imagen
            rad = math.radians(-oa)
            cos_a, sin_a = math.cos(rad), math.sin(rad)

            # Vector (ratón - esquina fija) llevado al sistema local: R(-rad)
            wx, wy = mx_mm - fx, my_mm - fy
            vx = wx * cos_a + wy * sin_a
            vy = -wx * sin_a + wy * cos_a

            if self.lock_aspect.get() and ow > 0 and oh > 0:
                # Diagonal local original (fija → arrastrada) = (-sfx*ow, -sfy*oh)
                ddx, ddy = -sfx * ow, -sfy * oh
                dsq = ddx * ddx + ddy * ddy
                t = max(0.02, (vx * ddx + vy * ddy) / dsq) if dsq > 0 else 1.0
                new_w = max(1.0, ow * t)
                new_h = max(1.0, oh * t)
            else:
                new_w = max(1.0, -vx * sfx)
                new_h = max(1.0, -vy * sfy)

            # Recolocar el centro para que la esquina fija no se mueva.
            # Offset local de la fija respecto al centro = (sfx*new_w/2, sfy*new_h/2)
            fox = sfx * new_w / 2
            foy = sfy * new_h / 2
            rox = fox * cos_a - foy * sin_a   # R(rad) local→mundo
            roy = fox * sin_a + foy * cos_a
            cx_new = fx - rox
            cy_new = fy - roy
            self.overlay_x_mm = cx_new - new_w / 2
            self.overlay_y_mm = cy_new - new_h / 2
            self.overlay_w_mm = new_w
            self.overlay_h_mm = new_h

        self._sync_controls_to_state()
        if not self._redraw_pending:
            self._redraw_pending = True
            self.after(32, self._drag_redraw)

    def _drag_redraw(self):
        """Redraw durante drag: grid + Gerber decimado + recuadro sin imagen."""
        self._redraw_pending = False
        self.canvas.delete("all")
        self._draw_grid()
        for entry in self.gerber_layers:
            if entry["var_visible"].get():
                self._draw_layer_entry(entry, fast=True)
        if self.overlay_image:
            self._draw_overlay_ghost()

    def _draw_overlay_ghost(self):
        """Dibuja el recuadro del overlay sin renderizar la imagen."""
        angle = self.overlay_angle_deg
        rad = math.radians(-angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        cx_mm = self.overlay_x_mm + self.overlay_w_mm / 2
        cy_mm = self.overlay_y_mm + self.overlay_h_mm / 2
        cx_px, cy_px = self._mm_to_canvas(cx_mm, cy_mm)
        hw, hh = self.overlay_w_mm / 2, self.overlay_h_mm / 2
        pts = []
        for dx, dy in [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]:
            rx = dx * cos_a - dy * sin_a
            ry = dx * sin_a + dy * cos_a
            px, py = self._mm_to_canvas(cx_mm + rx, cy_mm + ry)
            pts.extend([px, py])
        # Polígono sin alfa (tkinter no soporta alfa en fill de polígono)
        self.canvas.create_polygon(pts, outline=self.OVERLAY_COLOR,
                                   fill="", width=2, tags="overlay_ghost")
        # Esquinas como handles
        hs = 7
        for i in range(4):
            hx, hy = pts[i*2], pts[i*2+1]
            self.canvas.create_rectangle(hx-hs, hy-hs, hx+hs, hy+hs,
                                         fill=self.OVERLAY_COLOR, outline="white",
                                         tags="overlay_ghost")
        # Texto de dimensiones
        self.canvas.create_text(cx_px, cy_px,
                                text=f"{self.overlay_w_mm:.1f} × {self.overlay_h_mm:.1f} mm  ∠{self.overlay_angle_deg:.1f}°",
                                fill=self.OVERLAY_COLOR, font=("Courier", 9, "bold"),
                                tags="overlay_ghost")

    def _throttled_redraw(self):
        self._redraw_pending = False
        self._redraw()

    def _on_mouse_release(self, event):
        if self._drag_start:
            self._drag_start = None
            self._active_drag = None
            self._redraw()  # redraw completo con imagen al soltar

    def _on_pan_start(self, event):
        self._pan_start = (event.x, event.y, self.pan_x, self.pan_y)

    def _on_pan_drag(self, event):
        if not self._pan_start:
            return
        sx, sy, px0, py0 = self._pan_start
        self.pan_x = px0 + (event.x - sx)
        self.pan_y = py0 + (event.y - sy)
        self._nav_redraw()

    def _on_scroll(self, event):
        if event.num == 4 or event.delta > 0:
            self.zoom *= 1.1
        else:
            self.zoom /= 1.1
        self.zoom = max(0.1, min(self.zoom, 50))
        self._nav_redraw()

    def _nav_redraw(self):
        """Durante zoom/pan: grid + Gerber decimado + recuadro."""
        if hasattr(self, '_nav_timer') and self._nav_timer:
            self.after_cancel(self._nav_timer)
        self.canvas.delete("all")
        self._draw_grid()
        for entry in self.gerber_layers:
            if entry["var_visible"].get():
                self._draw_layer_entry(entry, fast=True)
        if self.overlay_image:
            self._draw_overlay_ghost()
        self._nav_timer = self.after(600, self._nav_finish)

    def _nav_finish(self):
        self._nav_timer = None
        self._overlay_cache_key = None
        self._redraw()

    def _draw_gerber_fast(self):
        """
        Render rápido para navegación: dibuja un subconjunto decimado de líneas.
        Objetivo: <300 create_line calls → fluido en Windows (~40ms).
        El outline siempre se dibuja completo (solo 4 líneas).
        """
        layer = self.gerber_layer
        scale = self._get_mm_scale()
        drawables = layer.drawables
        total = len(drawables)

        # Calcular step para quedarnos en ~250 líneas máximo
        target = 250
        step = max(1, total // target)

        for i, d in enumerate(drawables):
            if d["type"] != "line":
                continue
            if i % step != 0:
                continue
            x1c, y1c = self._mm_to_canvas(d["x1"], d["y1"])
            x2c, y2c = self._mm_to_canvas(d["x2"], d["y2"])
            self.canvas.create_line(x1c, y1c, x2c, y2c,
                                    fill=self.SILK_COLOR, width=1)

        # Borde del PCB siempre completo
        b = layer.bounds
        x1c, y1c = self._mm_to_canvas(b[0], b[1])
        x2c, y2c = self._mm_to_canvas(b[2], b[3])
        self.canvas.create_rectangle(x1c, y1c, x2c, y2c,
                                     outline="#44aa44", width=2)

    def _update_coords_display(self, event):
        mm_x, mm_y = self._canvas_to_mm(event.x, event.y)
        self.coords_var.set(f"X: {mm_x:.3f} mm  Y: {mm_y:.3f} mm")

    def fit_view(self):
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._redraw()

    def _get_all_bounds(self):
        """Bounding box union de todas las capas visibles."""
        xs, ys = [], []
        for entry in self.gerber_layers:
            if entry["var_visible"].get():
                b = entry["layer"].bounds
                xs += [b[0], b[2]]; ys += [b[1], b[3]]
        if xs:
            return (min(xs), min(ys), max(xs), max(ys))
        return (0, 0, 100, 100)

    # ── Exportación ────────────────────────────────

    # ── Editor de conversión de imagen ──────────────────────────────────

    # Parámetros JLCPCB: mínimo trazo 0.15mm, pitch mínimo recomendado 0.15mm
    JLCPCB_MIN_MM = 0.15

    def _open_conversion_editor(self):
        if not self.overlay_image:
            messagebox.showwarning("Aviso", "Importa una imagen primero.")
            return

        # Ventana no modal, independiente
        if hasattr(self, '_conv_editor') and self._conv_editor.winfo_exists():
            self._conv_editor.lift(); return

        win = tk.Toplevel(self)
        win.title("Editor de conversión")
        win.configure(bg="#252535")
        win.geometry("860x640")
        win.resizable(True, True)
        self._conv_editor = win

        # ── Parámetros (izquierda) ──
        left = tk.Frame(win, bg="#252535", width=220)
        left.pack(side="left", fill="y", padx=10, pady=10)
        left.pack_propagate(False)

        def lbl(text, fg="#ccccdd"):
            tk.Label(left, text=text, bg="#252535", fg=fg,
                     font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", pady=(8,1))
        def sep():
            tk.Frame(left, bg="#444466", height=1).pack(fill="x", pady=4)

        # Algoritmo
        lbl("Algoritmo de conversión")
        algo_var = tk.StringVar(value="threshold")
        algos = [
            ("Umbral simple",       "threshold"),
            ("Dithering Floyd-Steinberg", "floyd"),
            ("Dithering Atkinson",  "atkinson"),
            ("Dithering Bayer 4×4", "bayer4"),
            ("Dithering Bayer 8×8", "bayer8"),
            ("Dithering Stucki",    "stucki"),
            ("Dithering Jarvis",    "jarvis"),
        ]
        for txt, val in algos:
            tk.Radiobutton(left, text=txt, variable=algo_var, value=val,
                           bg="#252535", fg="#ddddee", selectcolor="#1a1a2e",
                           activebackground="#252535", font=("Segoe UI", 8),
                           anchor="w", command=lambda: win.after(50, refresh)
                           ).pack(fill="x", padx=4)

        sep()
        lbl("Umbral (para umbral simple)")
        thresh_var = tk.IntVar(value=self.overlay_threshold.get())
        tk.Scale(left, variable=thresh_var, from_=0, to=255, orient="horizontal",
                 bg="#252535", fg="white", troughcolor="#1a1a2e",
                 highlightthickness=0, command=lambda v: refresh(fast=True)
                 ).pack(fill="x")

        sep()
        # Tamaño real de la imagen en la PCB
        w_mm = self.overlay_w_mm; h_mm = self.overlay_h_mm
        import math as _m; angle = self.overlay_angle_deg
        if angle % 360 != 0:
            rad=_m.radians(angle); c,s=abs(_m.cos(rad)),abs(_m.sin(rad))
            w_mm, h_mm = w_mm*c+h_mm*s, w_mm*s+h_mm*c
        lbl(f"Imagen en PCB: {w_mm:.1f} × {h_mm:.1f} mm", fg="#88aacc")

        lbl("Tamaño de píxel visual (mm)")
        lbl("Controla el efecto del dithering. El Gerber\n"
            "siempre se exporta a 0.15mm (límite JLCPCB).",
            fg="#667788")

        # Calcular rango: mínimo = 0.15mm, máximo = 10% del lado menor
        min_px = self.JLCPCB_MIN_MM
        max_px = max(0.5, min(w_mm, h_mm) * 0.10)
        # Resolución equivalente en píxeles en los extremos
        def res_str(px):
            c = max(1, int(round(w_mm/px))); r = max(1, int(round(h_mm/px)))
            return f"{c}×{r} px"

        pxsize_var = tk.DoubleVar(value=min(max(min_px, float(self.entry_dot.get())), max_px))
        px_scale = tk.Scale(left, variable=pxsize_var, from_=min_px, to=max_px,
                            resolution=0.01, orient="horizontal",
                            bg="#252535", fg="white", troughcolor="#1a1a2e",
                            highlightthickness=0, command=lambda v: refresh(fast=True))
        px_scale.pack(fill="x")
        px_info = tk.Label(left, text="", bg="#252535", fg="#ffcc44", font=("Segoe UI", 8))
        px_info.pack()

        sep()
        lbl("Contraste / Gamma")
        contrast_var = tk.DoubleVar(value=getattr(self, '_conv_contrast', 1.0))
        tk.Scale(left, variable=contrast_var, from_=0.3, to=3.0, resolution=0.05,
                 orient="horizontal", bg="#252535", fg="white", troughcolor="#1a1a2e",
                 highlightthickness=0, command=lambda v: refresh(fast=True)
                 ).pack(fill="x")

        sep()
        lbl("Inversión de imagen")
        invert_var = tk.BooleanVar(value=getattr(self, '_conv_invert', False))
        tk.Checkbutton(left, text="Invertir negro/blanco", variable=invert_var,
                       bg="#252535", fg="#ddddee", selectcolor="#1a1a2e",
                       activebackground="#252535", font=("Segoe UI", 8),
                       command=lambda: refresh(fast=False)).pack(anchor="w")

        sep()
        # Botón aplicar: transfiere los parámetros a la ventana principal
        def apply_to_main():
            self.overlay_threshold.set(thresh_var.get())
            # El trazo de exportación siempre es 0.15mm (JLCPCB)
            self.entry_dot.delete(0, "end")
            self.entry_dot.insert(0, f"{self.JLCPCB_MIN_MM:.2f}")
            self._conv_algo = algo_var.get()
            self._conv_contrast = contrast_var.get()
            self._conv_invert = invert_var.get()
            self._conv_pxsize = pxsize_var.get()   # tamaño de píxel para dithering
            self._overlay_cache_key = None
            self._redraw()
            messagebox.showinfo("Aplicado",
                f"Exportación: trazo 0.15mm (JLCPCB)\n"
                f"Dithering: píxel {pxsize_var.get():.2f}mm · {algo_var.get()}\n"
                f"Contraste: {contrast_var.get():.2f}", parent=win)

        tk.Button(left, text="✅ Aplicar a exportación", command=apply_to_main,
                  bg="#2244aa", fg="white", relief="flat",
                  font=("Segoe UI", 9, "bold"), pady=6).pack(fill="x", pady=(8,2))
        tk.Button(left, text="Cerrar", command=win.destroy,
                  bg="#3a3a5c", fg="white", relief="flat",
                  font=("Segoe UI", 8), pady=4).pack(fill="x")

        # ── Preview (derecha) ──
        right = tk.Frame(win, bg="#1a1a2e")
        right.pack(side="left", fill="both", expand=True, padx=(0,10), pady=10)

        top_bar = tk.Frame(right, bg="#1a1a2e")
        top_bar.pack(fill="x", pady=(0,4))
        tk.Label(top_bar, text="Original", bg="#1a1a2e", fg="#aaaacc",
                 font=("Segoe UI", 8)).pack(side="left", padx=8)
        tk.Label(top_bar, text="Resultado Gerber", bg="#1a1a2e", fg="#ffcc44",
                 font=("Segoe UI", 8)).pack(side="right", padx=8)

        preview_frame = tk.Frame(right, bg="#1a1a2e")
        preview_frame.pack(fill="both", expand=True)

        lbl_orig = tk.Label(preview_frame, bg="#000000")
        lbl_orig.pack(side="left", fill="both", expand=True, padx=2)
        lbl_conv = tk.Label(preview_frame, bg="#000000")
        lbl_conv.pack(side="right", fill="both", expand=True, padx=2)

        info_lbl = tk.Label(right, text="", bg="#1a1a2e", fg="#888899",
                            font=("Segoe UI", 7))
        info_lbl.pack(pady=2)

        self._conv_refresh_id = None
        self._conv_quality_id = None

        def refresh(fast=True):
            # Cancelar renders pendientes
            for attr in ('_conv_refresh_id', '_conv_quality_id'):
                rid = getattr(self, attr, None)
                if rid:
                    try: win.after_cancel(rid)
                    except: pass
                setattr(self, attr, None)

            # Render rápido inmediato (baja res, umbral simple)
            if fast:
                def do_fast():
                    if not win.winfo_exists(): return
                    try: _render_preview(fast=True)
                    except Exception as e: info_lbl.config(text=f"Error: {e}")
                self._conv_refresh_id = win.after(30, do_fast)
                # Full quality 400ms después de que el usuario suelte
                def do_full():
                    if not win.winfo_exists(): return
                    try: _render_preview(fast=False)
                    except Exception as e: info_lbl.config(text=f"Error: {e}")
                self._conv_quality_id = win.after(420, do_full)
            else:
                def do_full():
                    if not win.winfo_exists(): return
                    try: _render_preview(fast=False)
                    except Exception as e: info_lbl.config(text=f"Error: {e}")
                self._conv_refresh_id = win.after(30, do_full)

        def _render_preview(fast=False):
            from PIL import Image as PILImg, ImageEnhance, ImageOps
            import numpy as np

            PW = max(1, (right.winfo_width() // 2) - 10) or 300
            PH = max(1, right.winfo_height() - 60) or 300

            # Imagen original (rotada si procede)
            img = self.overlay_image.copy()
            angle = self.overlay_angle_deg
            import math as _m
            if angle % 360 != 0:
                img = img.rotate(-angle, expand=True, resample=PILImg.BICUBIC)

            # Aplicar contraste/gamma
            img_enh = img.convert("L")
            if contrast_var.get() != 1.0:
                img_enh = ImageEnhance.Contrast(img_enh).enhance(contrast_var.get())
            if invert_var.get():
                img_enh = ImageOps.invert(img_enh)

            # Preview original (escalado a PW×PH)
            orig_disp = img_enh.copy()
            orig_disp.thumbnail((PW, PH), PILImg.LANCZOS)
            orig_disp = orig_disp.convert("RGB")

            # Calcular resolución en píxeles basada en tamaño de píxel visual
            dot = max(self.JLCPCB_MIN_MM, pxsize_var.get())
            w_mm_r = self.overlay_w_mm; h_mm_r = self.overlay_h_mm
            if angle % 360 != 0:
                rad = _m.radians(angle); cv, sv = abs(_m.cos(rad)), abs(_m.sin(rad))
                w_mm_r, h_mm_r = w_mm_r*cv+h_mm_r*sv, w_mm_r*sv+h_mm_r*cv
            cols = max(4, int(round(w_mm_r / dot)))
            rows = max(4, int(round(h_mm_r / dot)))

            # En modo rápido: limitar a 150px y usar umbral simple
            MAX_FAST = 150; MAX_FULL = 600
            max_p = MAX_FAST if fast else MAX_FULL
            if cols > max_p or rows > max_p:
                f = max_p / max(cols, rows)
                cols = max(4, int(cols*f)); rows = max(4, int(rows*f))

            small = img_enh.resize((cols, rows), PILImg.BILINEAR if fast else PILImg.LANCZOS)
            arr = np.array(small, dtype=np.float32)

            algo = algo_var.get()
            thresh = thresh_var.get()

            # Modo rápido: umbral simple siempre (los dithering error-diffusion son lentos)
            if fast or algo == "threshold":
                result = (arr < thresh).astype(np.uint8) * 255

            elif algo == "floyd":
                result = _dither_floyd(arr, thresh)

            elif algo == "atkinson":
                result = _dither_atkinson(arr, thresh)

            elif algo == "bayer4":
                result = _dither_bayer(arr, 4)

            elif algo == "bayer8":
                result = _dither_bayer(arr, 8)

            elif algo == "stucki":
                result = _dither_error(arr, thresh, "stucki")

            elif algo == "jarvis":
                result = _dither_error(arr, thresh, "jarvis")

            else:
                result = (arr < thresh).astype(np.uint8) * 255

            # Resultado como imagen visualizable
            # Mostrar resultado manteniendo aspect ratio (igual que la imagen original)
            res_img = PILImg.fromarray((255 - result).astype(np.uint8), "L").convert("RGB")
            res_img.thumbnail((PW, PH), PILImg.NEAREST)

            from PIL import ImageTk as PILImageTk
            tk_orig = PILImageTk.PhotoImage(orig_disp)
            tk_conv = PILImageTk.PhotoImage(res_img)
            lbl_orig.config(image=tk_orig); lbl_orig.image = tk_orig
            lbl_conv.config(image=tk_conv); lbl_conv.image = tk_conv

            dark_px = int(np.sum(result > 128))
            exp_cols = max(1, int(round(w_mm_r / self.JLCPCB_MIN_MM)))
            exp_rows = max(1, int(round(h_mm_r / self.JLCPCB_MIN_MM)))
            px_info.config(text=f"Píxel visual: {dot:.2f}mm → {cols}×{rows} px\n"
                                 f"Exportación: 0.15mm → {exp_cols}×{exp_rows} px")
            quality_note = "  ⚡ vista rápida…" if fast else ""
            info_lbl.config(text=f"Puntos de tinta: {dark_px}  ·  "
                                  f"Algoritmo: {algo_var.get()}{quality_note}")

        # ── Algoritmos de dithering ──
        def _dither_floyd(arr, thresh):
            import numpy as np
            a = arr.copy().astype(np.float32)
            h, w = a.shape
            out = np.zeros_like(a, dtype=np.uint8)
            for y in range(h):
                for x in range(w):
                    old = a[y, x]
                    new = 0.0 if old < thresh else 255.0
                    out[y, x] = int(new)
                    err = old - new
                    if x+1 < w:   a[y,x+1]   += err * 7/16
                    if y+1 < h:
                        if x-1 >= 0: a[y+1,x-1] += err * 3/16
                        a[y+1,x]   += err * 5/16
                        if x+1 < w:  a[y+1,x+1] += err * 1/16
            return out

        def _dither_atkinson(arr, thresh):
            import numpy as np
            a = arr.copy().astype(np.float32)
            h, w = a.shape
            out = np.zeros_like(a, dtype=np.uint8)
            for y in range(h):
                for x in range(w):
                    old = a[y, x]
                    new = 0.0 if old < thresh else 255.0
                    out[y, x] = int(new)
                    err = (old - new) / 8
                    for dy, dx in [(0,1),(0,2),(1,-1),(1,0),(1,1),(2,0)]:
                        ny, nx = y+dy, x+dx
                        if 0 <= ny < h and 0 <= nx < w:
                            a[ny, nx] += err
            return out

        def _dither_bayer(arr, n):
            import numpy as np
            def bayer_matrix(n):
                if n == 1: return np.array([[0]])
                m = bayer_matrix(n//2)
                return np.bmat([[4*m, 4*m+2], [4*m+3, 4*m+1]]).A / (n*n)
            bm = bayer_matrix(n) * 255
            h, w = arr.shape
            tiled = np.tile(bm, (h//n+1, w//n+1))[:h, :w]
            return ((arr < tiled) * 255).astype(np.uint8)

        def _dither_error(arr, thresh, method):
            import numpy as np
            if method == "stucki":
                kernel = [(0,1,8),(0,2,4),(1,-2,2),(1,-1,4),(1,0,8),(1,1,4),(1,2,2),(2,-2,1),(2,-1,2),(2,0,4),(2,1,2),(2,2,1)]
                div = 42
            else:  # jarvis
                kernel = [(0,1,7),(0,2,5),(1,-2,3),(1,-1,5),(1,0,7),(1,1,5),(1,2,3),(2,-2,1),(2,-1,3),(2,0,5),(2,1,3),(2,2,1)]
                div = 48
            a = arr.copy().astype(np.float32)
            h, w = a.shape
            out = np.zeros_like(a, dtype=np.uint8)
            for y in range(h):
                for x in range(w):
                    old = a[y,x]
                    new = 0.0 if old < thresh else 255.0
                    out[y,x] = int(new)
                    err = old - new
                    for dy,dx,wt in kernel:
                        ny,nx = y+dy, x+dx
                        if 0<=ny<h and 0<=nx<w:
                            a[ny,nx] += err * wt / div
            return out

        # Conectar resize a refresh
        win.bind("<Configure>", lambda e: refresh(fast=True))
        # Render inicial
        win.after(100, lambda: refresh(fast=False))

    def export_gerber(self):
        if not self.gerber_layers:
            messagebox.showwarning("Aviso", "Primero carga al menos una capa Gerber.")
            return

        # Construir la lista unificada de items exportables (todas las capas + targets nuevos)
        items = self._build_export_items()
        choices = self._choose_export_dialog(items)
        if not choices:
            return

        out_dir = filedialog.askdirectory(title="Carpeta donde guardar las capas exportadas")
        if not out_dir:
            return

        thresh = self.overlay_threshold.get()

        results = []
        try:
            for ch in choices:
                item = ch["item"]
                mode = ch["mode"]
                clr = ch.get("clearance", 0.5)   # holgura específica de esta capa
                tag = item["tag"]
                ext = item["ext"]
                out_path = str(Path(out_dir) / f"{tag}{ext}")

                if mode == "base":
                    # Exportar la capa cargada tal cual (sin logo)
                    item["base_entry"]["layer"].export_with_overlay([], out_path)
                    results.append(f"• {Path(out_path).name}  (solo base)")

                elif mode in ("merge", "clearance", "new", "under", "logo_windows"):
                    if item["base_entry"] is not None:
                        base_layer = item["base_entry"]["layer"]
                    else:
                        base = self._find_outline_layer() or self.gerber_layers[0]
                        base_layer = base["layer"]

                    converter = ImageToGerber(base_layer)
                    clearance = clr if mode == "clearance" else 0.0
                    cmds = self._build_logo_cmds(converter, thresh, clearance)

                    if mode == "new" or item["base_entry"] is None:
                        base_layer.export_new_layer(cmds, out_path, layer_name=tag)
                        results.append(f"• {Path(out_path).name}  (nueva, solo logo)")
                    elif mode == "clearance":
                        base_layer.export_with_overlay(cmds, out_path, position="after")
                        results.append(f"• {Path(out_path).name}  (logo con ventanas en base)")
                    elif mode == "under":
                        base_layer.export_with_overlay(cmds, out_path, position="before")
                        results.append(f"• {Path(out_path).name}  (base encima del logo)")
                    elif mode == "logo_windows":
                        # Logo encima + base perfora el logo (clear ancho) + base redibujada
                        clear_cmds = base_layer.emit_drawables(extra_mm=clr, polarity="C", dcode_start=200)
                        redraw_cmds = base_layer.emit_drawables(extra_mm=0.0, polarity="D", dcode_start=300)
                        combined = cmds + clear_cmds + redraw_cmds
                        base_layer.export_with_overlay(combined, out_path, position="after")
                        results.append(f"• {Path(out_path).name}  (logo con ventanas para la base)")
                    else:  # merge
                        base_layer.export_with_overlay(cmds, out_path, position="after")
                        results.append(f"• {Path(out_path).name}  (logo encima de base)")

            messagebox.showinfo("Exportado", "✅ Capas exportadas:\n\n" + "\n".join(results))
        except Exception as e:
            messagebox.showerror("Error de exportación", str(e))

    def _preview_layer(self, item, mode, parent=None, clearance=None):
        """Renderiza una preview de cómo quedará la capa (base + logo según modo)."""
        import numpy as np
        from PIL import Image as PILImage, ImageDraw as PILDraw

        # Holgura: la pasada explícitamente, o la del campo, o 0.5 por defecto
        if clearance is not None:
            try:
                clearance_mm = float(clearance)
            except (ValueError, TypeError):
                clearance_mm = 0.5
        else:
            clearance_mm = 0.5

        # Bounds de toda la placa
        b = self._get_all_bounds()
        gw = (b[2] - b[0]) or 1
        gh = (b[3] - b[1]) or 1
        PW = 700
        scale = PW / gw
        PH = int(gh * scale)
        clearance_px = max(1, int(round(clearance_mm * scale)))

        # Lienzo negro
        canvas_img = PILImage.new("RGB", (PW, PH), (40, 15, 20))
        draw = PILDraw.Draw(canvas_img)

        def to_px(xmm, ymm):
            px = (xmm - b[0]) * scale
            py = PH - (ymm - b[1]) * scale   # Y invertida
            return px, py

        base_entry = item["base_entry"]

        def draw_base(color, width=2, regions=True, traces=True, region_color=None):
            if base_entry is None:
                return
            rc = region_color if region_color is not None else color
            # Primero las regiones (copper pour) en tono apagado
            if regions:
                for d in base_entry["layer"].drawables:
                    if d["type"] == "region":
                        pts = [to_px(px, py) for (px, py) in d["path"]]
                        if len(pts) >= 3:
                            draw.polygon(pts, fill=rc)
            # Luego trazas y flashes encima
            if traces:
                for d in base_entry["layer"].drawables:
                    if d["type"] == "line":
                        x1, y1 = to_px(d["x1"], d["y1"])
                        x2, y2 = to_px(d["x2"], d["y2"])
                        draw.line([x1, y1, x2, y2], fill=color, width=width)
                    elif d["type"] == "flash":
                        x, y = to_px(d["x"], d["y"])
                        r = max(1.5, d["sx"] * scale / 2)
                        draw.ellipse([x-r, y-r, x+r, y+r], fill=color)

        # Imagen del logo binarizada y posicionada
        def logo_mask():
            thresh = self.overlay_threshold.get()
            img = self.overlay_image.convert("L")
            angle = self.overlay_angle_deg
            w_mm, h_mm = self.overlay_w_mm, self.overlay_h_mm
            cx = self.overlay_x_mm + w_mm/2
            cy = self.overlay_y_mm + h_mm/2
            # Tamaño en px de preview
            disp_w = max(2, int(w_mm * scale))
            disp_h = max(2, int(h_mm * scale))
            small = img.resize((disp_w, disp_h), PILImage.BILINEAR)
            arr = np.array(small) < thresh
            mimg = PILImage.fromarray((arr*255).astype(np.uint8), "L")
            if angle % 360 != 0:
                mimg = mimg.rotate(-angle, expand=True, resample=PILImage.NEAREST)
            # Posición: centrado en (cx,cy)
            mcx, mcy = to_px(cx, cy)
            return mimg, mcx, mcy

        mimg, mcx, mcy = logo_mask()
        mw, mh = mimg.size
        lx = int(mcx - mw/2); ly = int(mcy - mh/2)

        # Colores tipo cobre/placa (parecidos al visor de JLCPCB)
        logo_color = (255, 200, 40)   # logo en cobre (dorado brillante)
        base_color = (210, 130, 40)   # trazas en cobre
        pour_color = (150, 80, 30)    # plano de cobre (pour), tono cobre apagado
        bg = (40, 15, 20)             # board sin cobre (hueco/gap), rojo muy oscuro

        if mode == "under":
            # Logo primero, base encima (pour apagado + trazas + logo perforado por base)
            draw_base(pour_color, traces=False)                 # pour de fondo
            self._paste_mask(canvas_img, mimg, lx, ly, logo_color)
            draw_base(base_color, regions=False)                # trazas encima del logo
        elif mode == "clearance":
            # Pour + trazas, luego el reborde (gap sin cobre) alrededor del logo, luego logo cobre
            draw_base(base_color, region_color=pour_color)
            pad = clearance_px + 2
            padded = PILImage.new("L", (mimg.width + 2 * pad, mimg.height + 2 * pad), 0)
            padded.paste(mimg, (pad, pad))
            ksize = clearance_px * 2 + 1   # MaxFilter requiere tamaño impar
            mdil = padded.filter(__import__("PIL.ImageFilter", fromlist=["MaxFilter"]).MaxFilter(ksize))
            # Reborde: quita el cobre (pour) en la zona del logo + holgura → board oscuro
            self._paste_mask(canvas_img, mdil, lx - pad, ly - pad, bg)
            # Logo en cobre, tamaño original → queda el gap de separación visible alrededor
            self._paste_mask(canvas_img, mimg, lx, ly, logo_color)
        elif mode == "logo_windows":
            # Pour de fondo + logo encima + la base (trazas) perfora el logo con holgura
            draw_base(pour_color, traces=False)                 # pour apagado de fondo
            self._paste_mask(canvas_img, mimg, lx, ly, logo_color)   # logo cobre
            # Las trazas perforan el logo: hueco oscuro ancho y luego traza cobre
            draw_base(bg, width=2 + clearance_px * 2, regions=False)     # hueco alrededor de trazas
            draw_base(base_color, width=2, regions=False)               # traza visible dentro
        elif mode == "base":
            draw_base(base_color, region_color=pour_color)
        else:  # merge o new
            if mode != "new":
                draw_base(base_color, region_color=pour_color)
            self._paste_mask(canvas_img, mimg, lx, ly, logo_color)

        # Borde de placa (normalizar coords por la inversión de Y)
        x1, y1 = to_px(b[0], b[1]); x2, y2 = to_px(b[2], b[3])
        draw.rectangle([min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)],
                       outline=(80, 160, 80))

        # Mostrar en ventana (hija del diálogo que la abre, para jerarquía correcta)
        win = tk.Toplevel(parent if parent is not None else self)
        mode_labels = {"merge": "Logo encima de la base",
                       "under": "Base encima del logo",
                       "clearance": "Logo con ventanas en la base",
                       "logo_windows": "Ventanas en el logo (la base lo perfora)",
                       "base": "Solo la capa base (sin logo)",
                       "new": "Capa nueva (solo logo)"}
        win.title(f"Preview: {item['label']}")
        win.configure(bg="#1e1e2e")
        win.transient(parent if parent is not None else self)

        tk.Label(win, text=mode_labels.get(mode, mode),
                 bg="#1e1e2e", fg="#ffcc44", font=("Segoe UI", 10, "bold")).pack(pady=(8, 2))
        tk.Label(win, text=f"Holgura de ventanas: {clearance_mm:.2f} mm",
                 bg="#1e1e2e", fg="#88aacc", font=("Segoe UI", 8)).pack()
        from PIL import ImageTk as PILImageTk
        tkimg = PILImageTk.PhotoImage(canvas_img)
        lbl = tk.Label(win, image=tkimg, bg="#1e1e2e")
        lbl.image = tkimg
        lbl.pack(padx=8, pady=4)
        tk.Label(win, text="Dorado = logo en cobre  ·  Cobre = plano/trazas  ·  Oscuro = sin cobre (gap)",
                 bg="#1e1e2e", fg="#aaaacc", font=("Segoe UI", 8)).pack(pady=(0, 4))

        def close_preview():
            win.grab_release()
            win.destroy()
            # Devolver el grab al diálogo padre si existe
            if parent is not None:
                try:
                    parent.grab_set()
                except Exception:
                    pass

        tk.Button(win, text="Cerrar preview", command=close_preview,
                  bg="#3a3a5c", fg="white", relief="flat",
                  font=("Segoe UI", 9), pady=5, padx=14).pack(pady=(0, 10))
        win.protocol("WM_DELETE_WINDOW", close_preview)
        # La preview toma el grab temporalmente (modal sobre el diálogo)
        win.grab_set()
        win.lift()
        win.focus_force()

    def _paste_mask(self, canvas_img, mask, lx, ly, color):
        """Pega una máscara L como color sólido sobre canvas_img en (lx,ly)."""
        from PIL import Image as PILImage
        color_layer = PILImage.new("RGB", mask.size, color)
        canvas_img.paste(color_layer, (lx, ly), mask)

    def _build_export_items(self):
        """
        Construye la lista de items exportables:
        - Cada capa cargada (con o sin logo asignado)
        - Cada target del logo que NO tenga capa cargada equivalente (capa nueva)
        """
        items = []
        matched_tags = set()

        # 1) Capas cargadas
        for entry in self.gerber_layers:
            # ¿Esta capa es destino del logo?
            logo_here = None
            for t in self.logo_targets:
                if self._tag_matches_name(t["tag"], entry["name"]):
                    logo_here = t
                    matched_tags.add(t["tag"])
                    break
            tag = Path(entry["name"]).stem
            ext = Path(entry["name"]).suffix or ".gbr"
            items.append({
                "tag": tag, "ext": ext, "label": entry["name"],
                "base_entry": entry, "has_logo": logo_here is not None,
                "is_new": False,
            })

        # 2) Targets del logo sin capa cargada → capas nuevas
        for t in self.logo_targets:
            if t["tag"] in matched_tags:
                continue
            if self._find_loaded_layer_for_tag(t["tag"]) is not None:
                continue
            items.append({
                "tag": t["tag"], "ext": t["ext"], "label": t["label"],
                "base_entry": None, "has_logo": True, "is_new": True,
            })
        return items

    # Palabras clave y extensiones que identifican cada tipo de capa
    LAYER_KEYWORDS = {
        "TOP_SILK":      (["TOPSILK", "SILKTOP", "FSILKS", "SILKSCREENTOP"], [".gto"]),
        "BOTTOM_SILK":   (["BOTTOMSILK", "BOTSILK", "SILKBOTTOM", "SILKSCREENBOTTOM"], [".gbo"]),
        "TOP_MASK":      (["TOPMASK", "MASKTOP", "SOLDERMASKTOP", "FMASK"], [".gts"]),
        "BOTTOM_MASK":   (["BOTTOMMASK", "BOTMASK", "MASKBOTTOM", "SOLDERMASKBOTTOM", "BMASK"], [".gbs"]),
        "TOP_COPPER":    (["TOPCOPPER", "COPPERTOP", "TOPLAYER", "ETCHTOP", "FCU", "TOP"], [".gtl", ".cmp"]),
        "BOTTOM_COPPER": (["BOTTOMCOPPER", "COPPERBOTTOM", "BOTTOMLAYER", "ETCHBOTTOM", "BCU", "BOTTOM", "BOT"], [".gbl", ".sol"]),
    }

    def _tag_matches_name(self, tag, name):
        return self._layer_name_matches_tag(name, tag)

    def _layer_name_matches_tag(self, name, tag):
        """
        ¿El archivo 'name' corresponde al tipo de capa 'tag'?
        Reconoce nombres tipo TOP_SILK, TOP.art (cobre), .gtl, ETCH/BOTTOM, etc.
        """
        nm = name.upper()
        nm_clean = nm.replace("_", "").replace(".", "").replace(" ", "").replace("-", "")
        ext = ("." + name.split(".")[-1].lower()) if "." in name else ""

        # Coincidencia directa del tag limpio
        t = tag.upper().replace("_", "").replace(".", "").replace(" ", "")
        if t in nm_clean:
            return True

        # Coincidencia por palabras clave / extensiones conocidas
        if tag in self.LAYER_KEYWORDS:
            keywords, exts = self.LAYER_KEYWORDS[tag]
            if ext in exts:
                return True
            for kw in keywords:
                if kw in nm_clean:
                    # Evitar que "TOP" (cobre) capture "TOPSILK"/"TOPMASK"
                    if kw in ("TOP", "BOTTOM", "BOT") and ("SILK" in nm_clean or "MASK" in nm_clean):
                        continue
                    return True
        return False

    def _choose_export_dialog(self, items):
        """
        Diálogo que muestra TODAS las capas. Por cada una: checkbox de exportar
        y, si tiene base+logo, un modo (fusionar / solo base / logo con ventanas).
        Devuelve lista de {item, mode}.
        """
        dlg = tk.Toplevel(self)
        dlg.title("Exportar capas Gerber")
        dlg.configure(bg="#252535")
        dlg.transient(self); dlg.grab_set(); dlg.geometry("760x560")

        tk.Label(dlg, text="Selecciona qué capas exportar y cómo tratar el logo:",
                 bg="#252535", fg="#ccccdd", font=("Segoe UI", 10, "bold")
                 ).pack(pady=(14, 6), padx=14, anchor="w")

        tk.Label(dlg, text="Cada capa trae su receta por defecto (modo y holgura). "
                           "Puedes cambiarlas por capa.",
                 bg="#252535", fg="#8888aa", font=("Segoe UI", 8)).pack(padx=14, anchor="w")

        canvas_box = tk.Frame(dlg, bg="#252535")
        canvas_box.pack(fill="both", expand=True, padx=14, pady=6)

        # Mapa tag→receta del logo_targets (modo y holgura por defecto)
        recipe_by_tag = {}
        for t in self.logo_targets:
            recipe_by_tag[t["tag"]] = (t.get("def_mode", "merge"), t.get("def_clearance", 0.5))

        def recipe_for_item(item):
            # Buscar receta por tag exacto o por tipo de capa del item
            if item["tag"] in recipe_by_tag:
                return recipe_by_tag[item["tag"]]
            # Inferir por nombre
            nm = item["label"].upper()
            if "SILK" in nm:
                return ("logo_windows", 1.0)
            if "MASK" in nm:
                return ("merge", 0.0)
            if any(k in nm for k in ("COPPER", "ETCH", ".GTL", ".GBL")) or \
               item["tag"].upper() in ("TOP", "BOTTOM"):
                return ("clearance", 0.5)
            return ("merge", 0.5)

        rows = []
        for item in items:
            row = tk.Frame(canvas_box, bg="#1e1e2e", pady=4)
            row.pack(fill="x", pady=2)

            exp_var = tk.BooleanVar(value=item["has_logo"] or not item["is_new"])
            tk.Checkbutton(row, variable=exp_var, bg="#1e1e2e", selectcolor="#0a0a1a",
                           activebackground="#1e1e2e").pack(side="left")

            txt = item["label"]
            if item["is_new"]:
                txt += "  [NUEVA]"
            tk.Label(row, text=txt, bg="#1e1e2e", fg="#ddddee",
                     font=("Segoe UI", 9), width=24, anchor="w").pack(side="left")

            def_mode, def_clr = recipe_for_item(item)

            # Modo
            if item["base_entry"] is not None and item["has_logo"]:
                mode_var = tk.StringVar(value=def_mode)
                opts = tk.Frame(row, bg="#1e1e2e")
                opts.pack(side="left")
                for val, lbl in [("merge", "Logo encima"),
                                 ("under", "Base encima"),
                                 ("clearance", "Vent. base"),
                                 ("logo_windows", "Vent. logo"),
                                 ("base", "Solo base")]:
                    tk.Radiobutton(opts, text=lbl, variable=mode_var, value=val,
                                   bg="#1e1e2e", fg="#aaccdd", selectcolor="#0a0a1a",
                                   activebackground="#1e1e2e",
                                   font=("Segoe UI", 7)).pack(side="left")
                # Holgura por capa
                clr_var = tk.StringVar(value=f"{def_clr:.2f}")
                tk.Label(row, text="mm:", bg="#1e1e2e", fg="#88aacc",
                         font=("Segoe UI", 7)).pack(side="left", padx=(4, 0))
                tk.Entry(row, textvariable=clr_var, bg="#1a1a2e", fg="white",
                         insertbackground="white", relief="flat",
                         font=("Segoe UI", 8), width=4).pack(side="left")
                tk.Button(row, text="👁", font=("Segoe UI", 8),
                          bg="#3a3a5c", fg="white", relief="flat",
                          command=lambda it=item, mv=mode_var, cv=clr_var:
                              self._preview_layer(it, mv.get(), parent=dlg, clearance=cv.get())
                          ).pack(side="right", padx=2)
            elif item["is_new"]:
                mode_var = tk.StringVar(value="new")
                clr_var = tk.StringVar(value=f"{def_clr:.2f}")
                tk.Label(row, text="(genera nueva, solo logo)", bg="#1e1e2e",
                         fg="#66cc88", font=("Segoe UI", 7)).pack(side="left", padx=4)
                tk.Button(row, text="👁", font=("Segoe UI", 8),
                          bg="#3a3a5c", fg="white", relief="flat",
                          command=lambda it=item: self._preview_layer(it, "new", parent=dlg)
                          ).pack(side="right", padx=2)
            else:
                mode_var = tk.StringVar(value="base")
                clr_var = tk.StringVar(value="0.0")
                tk.Label(row, text="(sin logo, copia tal cual)", bg="#1e1e2e",
                         fg="#778899", font=("Segoe UI", 7)).pack(side="left", padx=4)
                tk.Button(row, text="👁", font=("Segoe UI", 8),
                          bg="#3a3a5c", fg="white", relief="flat",
                          command=lambda it=item: self._preview_layer(it, "base", parent=dlg)
                          ).pack(side="right", padx=2)

            rows.append((exp_var, mode_var, clr_var, item))

        res = {"v": None}
        def ok():
            sel = []
            for ev, mv, cv, it in rows:
                if not ev.get():
                    continue
                try:
                    clr = float(cv.get())
                except ValueError:
                    clr = 0.5
                sel.append({"item": it, "mode": mv.get(), "clearance": clr})
            if not sel:
                messagebox.showwarning("Aviso", "Marca al menos una capa.", parent=dlg)
                return
            res["v"] = sel
            dlg.destroy()

        btns = tk.Frame(dlg, bg="#252535"); btns.pack(side="bottom", fill="x", pady=12, padx=14)
        tk.Button(btns, text="Exportar seleccionadas", command=ok, bg="#2244aa", fg="white",
                  relief="flat", font=("Segoe UI", 9, "bold"), pady=6, padx=14).pack(side="right", padx=4)
        tk.Button(btns, text="Cancelar", command=dlg.destroy, bg="#3a3a5c", fg="white",
                  relief="flat", font=("Segoe UI", 9), pady=6, padx=14).pack(side="right", padx=4)
        self.wait_window(dlg)
        return res["v"]

    def _build_logo_cmds(self, converter, thresh, clearance_mm=0.0):
        """Genera los comandos Gerber del logo (SVG o raster)."""
        ext = Path(self.overlay_image_path).suffix.lower() if hasattr(self, 'overlay_image_path') else ""
        if ext == ".svg" and SVG_AVAILABLE and getattr(self, 'overlay_svg_path', None):
            try:
                return converter.convert_svg_paths(
                    self.overlay_svg_path,
                    self.overlay_x_mm, self.overlay_y_mm,
                    self.overlay_w_mm, self.overlay_h_mm
                )
            except Exception:
                return self._export_raster(converter, thresh, clearance_mm)
        return self._export_raster(converter, thresh, clearance_mm)

    def _find_loaded_layer_for_tag(self, tag):
        """Busca una capa cargada cuyo nombre coincida con el tag (TOP_SILK, etc.)."""
        for entry in self.gerber_layers:
            if self._layer_name_matches_tag(entry["name"], tag):
                return entry
        return None

    def _choose_export_targets(self):
        """Diálogo para elegir cuáles de las capas destino exportar. Devuelve lista."""
        dlg = tk.Toplevel(self)
        dlg.title("¿Qué capas exportar?")
        dlg.configure(bg="#252535")
        dlg.transient(self); dlg.grab_set(); dlg.geometry("420x360")
        tk.Label(dlg, text="Marca las capas que quieres exportar:",
                 bg="#252535", fg="#ccccdd", font=("Segoe UI", 10, "bold")
                 ).pack(pady=12, padx=14, anchor="w")

        rows = []
        for target in self.logo_targets:
            v = tk.BooleanVar(value=True)
            existing = self._find_loaded_layer_for_tag(target["tag"])
            note = "  (se añade a capa cargada)" if existing else "  (se genera nueva)"
            tk.Checkbutton(dlg, text=f"{target['label']} → {target['tag']}{target['ext']}{note}",
                           variable=v, bg="#252535", fg="#ddddee", selectcolor="#1a1a2e",
                           activebackground="#252535", font=("Segoe UI", 9),
                           anchor="w").pack(fill="x", padx=18, pady=2)
            rows.append((v, target))

        res = {"v": None}
        def ok():
            res["v"] = [t for v, t in rows if v.get()]
            if not res["v"]:
                messagebox.showwarning("Aviso", "Marca al menos una capa.", parent=dlg)
                return
            dlg.destroy()
        btns = tk.Frame(dlg, bg="#252535"); btns.pack(side="bottom", pady=14)
        tk.Button(btns, text="Exportar", command=ok, bg="#2244aa", fg="white",
                  relief="flat", font=("Segoe UI", 9, "bold"), pady=5, padx=14).pack(side="right", padx=4)
        tk.Button(btns, text="Cancelar", command=dlg.destroy, bg="#3a3a5c", fg="white",
                  relief="flat", font=("Segoe UI", 9), pady=5, padx=14).pack(side="right", padx=4)
        self.wait_window(dlg)
        return res["v"]

    def _choose_target_layer(self):
        """Diálogo modal para elegir la capa destino del logo. Devuelve el dict o None."""
        dlg = tk.Toplevel(self)
        dlg.title("¿En qué capa incluir el logo?")
        dlg.configure(bg="#252535")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("420x360")

        tk.Label(dlg, text="Selecciona la capa de serigrafía destino:",
                 bg="#252535", fg="#ccccdd", font=("Segoe UI", 10, "bold"),
                 wraplength=380).pack(pady=(14, 4), padx=14, anchor="w")
        tk.Label(dlg, text="El logo se insertará en una copia de esa capa. "
                           "Las capas de serigrafía suelen llamarse SILK / SILKSCREEN.",
                 bg="#252535", fg="#8888aa", font=("Segoe UI", 8),
                 wraplength=390, justify="left").pack(pady=(0, 8), padx=14, anchor="w")

        result = {"choice": None}
        sel_var = tk.IntVar(value=-1)

        # Pre-seleccionar una capa que parezca de silkscreen
        def looks_like_silk(entry):
            name = entry["name"].upper()
            hdr = "".join(entry["layer"].raw_lines[:20]).upper()
            return "SILK" in name or "SILK" in hdr

        list_frame = tk.Frame(dlg, bg="#252535")
        list_frame.pack(fill="both", expand=True, padx=14)
        default_idx = -1
        for i, entry in enumerate(self.gerber_layers):
            is_silk = looks_like_silk(entry)
            if is_silk and default_idx < 0:
                default_idx = i
            tag = "  ✓ serigrafía" if is_silk else ""
            row = tk.Frame(list_frame, bg="#252535")
            row.pack(fill="x", pady=2)
            tk.Radiobutton(row, text=f"{entry['name']}{tag}",
                           variable=sel_var, value=i,
                           bg="#252535", fg="#ddddee", selectcolor="#1a1a2e",
                           activebackground="#252535", font=("Segoe UI", 9),
                           anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(row, text="■", bg="#252535", fg=entry["color"]).pack(side="right")
        if default_idx >= 0:
            sel_var.set(default_idx)

        btns = tk.Frame(dlg, bg="#252535")
        btns.pack(fill="x", pady=12, padx=14)

        def accept():
            idx = sel_var.get()
            if idx < 0:
                messagebox.showwarning("Aviso", "Selecciona una capa.", parent=dlg)
                return
            result["choice"] = self.gerber_layers[idx]
            dlg.destroy()

        def cancel():
            dlg.destroy()

        tk.Button(btns, text="Exportar a esta capa", command=accept,
                  bg="#2244aa", fg="white", relief="flat",
                  font=("Segoe UI", 9, "bold"), pady=5).pack(side="right", padx=4)
        tk.Button(btns, text="Cancelar", command=cancel,
                  bg="#3a3a5c", fg="white", relief="flat",
                  font=("Segoe UI", 9), pady=5).pack(side="right", padx=4)

        self.wait_window(dlg)
        return result["choice"]

    # ── Generar capa nueva desde cero ──────────────

    # Tipos de capa que se pueden generar y sufijo de archivo sugerido
    NEW_LAYER_TYPES = [
        ("Serigrafía TOP", "TOP_SILK", ".gto"),
        ("Serigrafía BOTTOM", "BOTTOM_SILK", ".gbo"),
        ("Soldermask TOP", "TOP_MASK", ".gts"),
        ("Soldermask BOTTOM", "BOTTOM_MASK", ".gbs"),
        ("Cobre TOP", "TOP_COPPER", ".gtl"),
        ("Cobre BOTTOM", "BOTTOM_COPPER", ".gbl"),
    ]

    def generate_new_layer(self):
        if not self.gerber_layers:
            messagebox.showwarning("Aviso", "Carga al menos el outline de la PCB primero.")
            return
        if not self.overlay_image:
            messagebox.showwarning("Aviso", "Importa una imagen primero.")
            return

        # Buscar la capa de outline para usar su formato como base
        base = self._find_outline_layer()
        if base is None:
            base = self._choose_base_layer()
            if base is None:
                return

        # Elegir qué tipo de capa generar
        layer_type = self._choose_new_layer_type()
        if layer_type is None:
            return
        label, name_tag, ext = layer_type

        base_layer = base["layer"]
        output_path = filedialog.asksaveasfilename(
            title=f"Guardar nueva capa: {label}",
            defaultextension=ext,
            filetypes=[("Gerber", "*.gbr *.gto *.gbo *.gts *.gbs *.gtl *.gbl *.art"), ("Todos", "*.*")],
            initialfile=f"{name_tag}{ext}"
        )
        if not output_path:
            return

        try:
            converter = ImageToGerber(base_layer)
            thresh = self.overlay_threshold.get()

            ext_img = Path(self.overlay_image_path).suffix.lower() if hasattr(self, 'overlay_image_path') else ""
            if ext_img == ".svg" and SVG_AVAILABLE and getattr(self, 'overlay_svg_path', None):
                try:
                    cmds = converter.convert_svg_paths(
                        self.overlay_svg_path,
                        self.overlay_x_mm, self.overlay_y_mm,
                        self.overlay_w_mm, self.overlay_h_mm
                    )
                except Exception:
                    cmds = self._export_raster(converter, thresh)
            else:
                cmds = self._export_raster(converter, thresh)

            base_layer.export_new_layer(cmds, output_path, layer_name=name_tag)

            lines = sum(1 for c in cmds if c.endswith("D01*"))
            messagebox.showinfo(
                "Capa generada",
                f"✅ Nueva capa '{label}' creada desde cero.\n\n"
                f"Archivo: {Path(output_path).name}\n"
                f"Formato heredado de: {base['name']}\n"
                f"Unidades: {base_layer.unit}\n"
                f"Segmentos de línea: {lines}"
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _find_outline_layer(self):
        """Busca una capa cargada que sea el outline (por nombre o cabecera)."""
        for entry in self.gerber_layers:
            name = entry["name"].upper()
            hdr = "".join(entry["layer"].raw_lines[:20]).upper()
            if "OUTLINE" in name or "OUTLINE" in hdr or "BOARD GEOMETRY" in hdr:
                return entry
        return None

    def _choose_base_layer(self):
        """Si no hay outline claro, pedir al usuario qué capa usar como base de formato."""
        names = [e["name"] for e in self.gerber_layers]
        dlg = tk.Toplevel(self)
        dlg.title("Capa base para el formato")
        dlg.configure(bg="#252535")
        dlg.transient(self); dlg.grab_set(); dlg.geometry("400x300")
        tk.Label(dlg, text="No se detectó un OUTLINE. Elige de qué capa heredar\n"
                           "el formato (unidades, decimales) para la nueva capa:",
                 bg="#252535", fg="#ccccdd", font=("Segoe UI", 9),
                 justify="left", wraplength=370).pack(pady=12, padx=14, anchor="w")
        sel = tk.IntVar(value=0)
        for i, n in enumerate(names):
            tk.Radiobutton(dlg, text=n, variable=sel, value=i,
                           bg="#252535", fg="#ddddee", selectcolor="#1a1a2e",
                           activebackground="#252535", font=("Segoe UI", 9),
                           anchor="w").pack(fill="x", padx=20)
        res = {"v": None}
        def ok(): res["v"] = self.gerber_layers[sel.get()]; dlg.destroy()
        tk.Button(dlg, text="Usar esta capa", command=ok, bg="#2244aa", fg="white",
                  relief="flat", font=("Segoe UI", 9, "bold"), pady=5).pack(pady=14)
        self.wait_window(dlg)
        return res["v"]

    def _choose_logo_layers(self):
        """Diálogo: recetas de un clic + selección manual de capas destino."""
        dlg = tk.Toplevel(self)
        dlg.title("¿Dónde insertar el logo?")
        dlg.configure(bg="#252535")
        dlg.transient(self); dlg.grab_set(); dlg.geometry("440x600")

        # Checkbox por cada tipo de capa estándar (se usan también por las recetas)
        vars_by_tag = {}
        for label, tag, ext in self.NEW_LAYER_TYPES:
            vars_by_tag[tag] = (tk.BooleanVar(value=False), label, ext)
        custom_var = tk.BooleanVar(value=False)

        # ── RECETAS RÁPIDAS ──────────────────────────
        tk.Label(dlg, text="Recetas rápidas (un clic):",
                 bg="#252535", fg="#66cc88", font=("Segoe UI", 10, "bold")
                 ).pack(pady=(14, 4), padx=14, anchor="w")

        def clear_all():
            for v, _, _ in vars_by_tag.values():
                v.set(False)
            custom_var.set(False)

        def apply_recipe(tags):
            clear_all()
            for t in tags:
                vars_by_tag[t][0].set(True)

        recipes = [
            ("Insert to TOP silkscreen",      ["TOP_SILK"]),
            ("Insert to BOTTOM silkscreen",   ["BOTTOM_SILK"]),
            ("Insert to TOP copper + mask",   ["TOP_COPPER", "TOP_MASK"]),
            ("Insert to BOTTOM copper + mask",["BOTTOM_COPPER", "BOTTOM_MASK"]),
        ]
        for text, tags in recipes:
            tk.Button(dlg, text=text, command=lambda tg=tags: apply_recipe(tg),
                      bg="#2a4a3a", fg="white", relief="flat", anchor="w",
                      font=("Segoe UI", 9), pady=5, padx=10
                      ).pack(fill="x", padx=14, pady=2)

        tk.Frame(dlg, bg="#444466", height=1).pack(fill="x", padx=14, pady=8)

        # ── SELECCIÓN MANUAL ─────────────────────────
        tk.Label(dlg, text="Selección manual:",
                 bg="#252535", fg="#ccccdd", font=("Segoe UI", 10, "bold")
                 ).pack(padx=14, anchor="w")
        tk.Label(dlg, text="Si la capa ya está cargada, el logo se añade a ella; "
                           "si no, se genera desde el outline.",
                 bg="#252535", fg="#8888aa", font=("Segoe UI", 8),
                 wraplength=400, justify="left").pack(pady=(0, 6), padx=14, anchor="w")

        copper_mask_pairs = {"TOP_COPPER": "TOP_MASK", "BOTTOM_COPPER": "BOTTOM_MASK"}
        def on_copper_toggle(copper_tag):
            if vars_by_tag[copper_tag][0].get():
                vars_by_tag[copper_mask_pairs[copper_tag]][0].set(True)

        for label, tag, ext in self.NEW_LAYER_TYPES:
            v = vars_by_tag[tag][0]
            cmd = (lambda tg=tag: on_copper_toggle(tg)) if tag in copper_mask_pairs else None
            tk.Checkbutton(dlg, text=f"{label}   ({ext})", variable=v, command=cmd,
                           bg="#252535", fg="#ddddee", selectcolor="#1a1a2e",
                           activebackground="#252535", font=("Segoe UI", 9),
                           anchor="w").pack(fill="x", padx=20, pady=1)

        # Capa personalizada
        custom_frame = tk.Frame(dlg, bg="#252535")
        custom_frame.pack(fill="x", padx=20, pady=(4, 0))
        tk.Checkbutton(custom_frame, text="Capa personalizada:", variable=custom_var,
                       bg="#252535", fg="#ddddee", selectcolor="#1a1a2e",
                       activebackground="#252535", font=("Segoe UI", 9)).pack(side="left")
        custom_name = tk.Entry(custom_frame, bg="#1a1a2e", fg="white",
                               insertbackground="white", relief="flat",
                               font=("Segoe UI", 9), width=14)
        custom_name.insert(0, "CUSTOM_LAYER")
        custom_name.pack(side="left", padx=6)

        tk.Label(dlg, text="Presets: silk → ventanas en logo (1 mm) · "
                           "cobre → ventanas en cobre (0.5 mm) · máscara (0 mm)",
                 bg="#252535", fg="#66aa88", font=("Segoe UI", 7),
                 wraplength=400, justify="left").pack(pady=(8, 0), padx=14, anchor="w")

        def accept():
            targets = []
            for tag, (v, label, ext) in vars_by_tag.items():
                if v.get():
                    targets.append({"tag": tag, "label": label, "ext": ext,
                                    **self._recipe_for_tag(tag)})
            if custom_var.get():
                cname = custom_name.get().strip() or "CUSTOM_LAYER"
                targets.append({"tag": cname, "label": cname, "ext": ".gbr",
                                "def_mode": "merge", "def_clearance": 0.5})
            if not targets:
                messagebox.showwarning("Aviso", "Selecciona al menos una capa.", parent=dlg)
                return
            self.logo_targets = targets
            self._update_targets_label()
            dlg.destroy()

        btns = tk.Frame(dlg, bg="#252535")
        btns.pack(side="bottom", fill="x", pady=12, padx=14)
        tk.Button(btns, text="Confirmar", command=accept, bg="#2244aa", fg="white",
                  relief="flat", font=("Segoe UI", 9, "bold"), pady=5, padx=14).pack(side="right", padx=4)
        tk.Button(btns, text="Más tarde", command=dlg.destroy, bg="#3a3a5c", fg="white",
                  relief="flat", font=("Segoe UI", 9), pady=5, padx=14).pack(side="right", padx=4)

        self.wait_window(dlg)

    def _recipe_for_tag(self, tag):
        """
        Devuelve la receta por defecto (modo + holgura) según el tipo de capa.
        - Serigrafía: ventanas en logo, 1.0 mm (la silk antigua se ve a través del logo)
        - Cobre: ventanas en base/clearance, 0.5 mm (el logo queda como isla de cobre
          aislada del ground pour por un reborde de separación)
        - Máscara: logo encima, 0.0 mm
        """
        if "SILK" in tag:
            return {"def_mode": "logo_windows", "def_clearance": 1.0}
        if "COPPER" in tag:
            return {"def_mode": "clearance", "def_clearance": 0.5}
        if "MASK" in tag:
            return {"def_mode": "merge", "def_clearance": 0.0}
        return {"def_mode": "merge", "def_clearance": 0.5}

    def _update_targets_label(self):
        if hasattr(self, "targets_var"):
            if self.logo_targets:
                self.targets_var.set("Logo → " + ", ".join(t["label"] for t in self.logo_targets))
            else:
                self.targets_var.set("(sin capas destino)")

    def _choose_new_layer_type(self):
        """Diálogo para elegir el tipo de capa a generar. Devuelve (label, tag, ext) o None."""
        dlg = tk.Toplevel(self)
        dlg.title("¿Qué capa generar?")
        dlg.configure(bg="#252535")
        dlg.transient(self); dlg.grab_set(); dlg.geometry("360x340")
        tk.Label(dlg, text="Tipo de capa a crear desde cero:",
                 bg="#252535", fg="#ccccdd", font=("Segoe UI", 10, "bold")
                 ).pack(pady=12, padx=14, anchor="w")
        sel = tk.IntVar(value=0)
        for i, (label, tag, ext) in enumerate(self.NEW_LAYER_TYPES):
            tk.Radiobutton(dlg, text=f"{label}   ({ext})", variable=sel, value=i,
                           bg="#252535", fg="#ddddee", selectcolor="#1a1a2e",
                           activebackground="#252535", font=("Segoe UI", 9),
                           anchor="w").pack(fill="x", padx=20, pady=2)
        res = {"v": None}
        def ok(): res["v"] = self.NEW_LAYER_TYPES[sel.get()]; dlg.destroy()
        def cancel(): dlg.destroy()
        btns = tk.Frame(dlg, bg="#252535"); btns.pack(pady=16)
        tk.Button(btns, text="Generar", command=ok, bg="#2244aa", fg="white",
                  relief="flat", font=("Segoe UI", 9, "bold"), pady=5, padx=12).pack(side="right", padx=4)
        tk.Button(btns, text="Cancelar", command=cancel, bg="#3a3a5c", fg="white",
                  relief="flat", font=("Segoe UI", 9), pady=5, padx=12).pack(side="right", padx=4)
        self.wait_window(dlg)
        return res["v"]

    def _export_raster(self, converter, thresh, clearance_mm=0.0):
        import math as _m
        from PIL import ImageEnhance, ImageOps
        try:
            dot_size = float(self.entry_dot.get())
        except ValueError:
            dot_size = 0.15

        w_mm = self.overlay_w_mm
        h_mm = self.overlay_h_mm
        cx = self.overlay_x_mm + w_mm / 2
        cy = self.overlay_y_mm + h_mm / 2

        img = self.overlay_image.copy()
        angle = self.overlay_angle_deg

        if angle % 360 != 0:
            img = img.rotate(-angle, expand=True, resample=Image.BICUBIC)
            rad = _m.radians(angle)
            c, s = abs(_m.cos(rad)), abs(_m.sin(rad))
            box_w = w_mm * c + h_mm * s
            box_h = w_mm * s + h_mm * c
        else:
            box_w, box_h = w_mm, h_mm

        x0 = cx - box_w / 2
        y0 = cy - box_h / 2

        # Aplicar parámetros del editor de conversión si están activos
        algo = getattr(self, '_conv_algo', 'threshold')
        contrast = getattr(self, '_conv_contrast', 1.0)
        invert = getattr(self, '_conv_invert', False)
        pxsize = getattr(self, '_conv_pxsize', dot_size)  # tamaño píxel para dithering

        img_l = img.convert("L")
        if contrast != 1.0:
            img_l = ImageEnhance.Contrast(img_l).enhance(contrast)
        if invert:
            img_l = ImageOps.invert(img_l)

        return converter.convert(
            img_l, x0, y0, box_w, box_h,
            threshold=thresh, dot_size_mm=dot_size,
            clearance_mm=clearance_mm, dither_algo=algo,
            dither_px_mm=pxsize
        )


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if not PIL_AVAILABLE:
        print("ERROR: Pillow no está instalado. Ejecuta: pip install pillow")
        exit(1)

    app = GerberEditor()
    app.geometry("1200x750")
    app.mainloop()
