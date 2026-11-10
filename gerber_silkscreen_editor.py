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
import json
from pathlib import Path
from layer_identity import layer_role,layer_label,display_name
from board_clip import outline_contours, clip_mask, clipping_commands
from image_tuning import (DEFAULTS as TUNING_DEFAULTS, validate_tuning, tune_gray,
                          PreparedCache, PreviewCancelled, check_cancel, auto_settings, native_floyd, ink_preview)

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
        self.used_apertures = set()
        self.unit = "MM"
        last_op = 2
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
            cmd = raw.replace('%', '').strip()

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
                sy = sizes[1] if len(sizes) > 1 and shape != 'C' else sx
                if self.unit == "IN":
                    sx *= 25.4
                    sy *= 25.4
                apertures[code] = (shape, sx, sy)
                self.used_apertures.add(code)
                continue

            # Selección de apertura
            m = re.fullmatch(r'(?:G54)?D(\d+)', cmd)
            if m and int(m.group(1)) >= 10:
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
            m = re.fullmatch(r'(?:G0[0123])?(X([+-]?\d+))?(Y([+-]?\d+))?(I([+-]?\d+))?(J([+-]?\d+))?(?:D0?([123]))?', cmd)
            if m and any(m.group(n) is not None for n in (2, 4, 6, 8, 9)):
                raw_x = m.group(2)
                raw_y = m.group(4)
                raw_i = m.group(6)
                raw_j = m.group(8)
                op = int(m.group(9)) if m.group(9) else last_op
                last_op = op

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
                        if in_region:
                            for segment in segs:segment['region_edge']=True
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
                        if in_region:seg['region_edge']=True
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
            if d.get('region_edge'):continue
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


def _apply_floyd(arr, thresh, cancel=None):
    import numpy as np
    a = arr.copy(); h, w = a.shape
    out = np.zeros((h, w), dtype=bool)
    for y in range(h):
        check_cancel(cancel)
        for x in range(w):
            old = a[y, x]; new = 0.0 if old < thresh else 255.0
            out[y, x] = new < 128; err = old - new
            if x+1 < w:   a[y,x+1]   += err * 7/16
            if y+1 < h:
                if x-1 >= 0: a[y+1,x-1] += err * 3/16
                a[y+1,x]   += err * 5/16
                if x+1 < w:  a[y+1,x+1] += err * 1/16
    return out

def _apply_atkinson(arr, thresh, cancel=None):
    import numpy as np
    a = arr.copy(); h, w = a.shape
    out = np.zeros((h, w), dtype=bool)
    for y in range(h):
        check_cancel(cancel)
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
        return np.block([[4*m, 4*m+2], [4*m+3, 4*m+1]])
    bm = (_bm(n) + .5) * (255 / (n*n)); h, w = arr.shape
    tiled = np.tile(bm, (h//n+1, w//n+1))[:h, :w]
    return arr < tiled

def _apply_error_diffusion(arr, thresh, method, cancel=None):
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
        check_cancel(cancel)
        for x in range(w):
            old = a[y,x]; new = 0.0 if old < thresh else 255.0
            out[y,x] = new < 128; err = old - new
            for dy,dx,wt in kernel:
                ny,nx = y+dy, x+dx
                if 0<=ny<h and 0<=nx<w: a[ny,nx] += err * wt / div
    return out


def _raster_ink_mask(arr, algo, threshold, cancel=None):
    """Máscara común para preview y Gerber: True siempre significa tinta."""
    import numpy as np
    arr = np.asarray(arr, dtype=np.float32)
    check_cancel(cancel)
    if algo == 'floyd_fast':return native_floyd(arr,threshold)
    if algo == 'floyd':
        return _apply_floyd(arr, threshold, cancel)
    if algo == 'atkinson':
        return _apply_atkinson(arr, threshold, cancel)
    if algo == 'bayer2':return _apply_bayer(arr,2)
    if algo == 'clustered4':
        ranks=np.array([[12,4,5,13],[6,0,1,7],[8,2,3,9],[14,10,11,15]],dtype=float)
        h,w=arr.shape
        return arr<np.tile((ranks+.5)*255/16,(h//4+1,w//4+1))[:h,:w]
    if algo == 'bayer4':
        return _apply_bayer(arr, 4)
    if algo == 'bayer8':
        return _apply_bayer(arr, 8)
    if algo in ('stucki', 'jarvis'):
        return _apply_error_diffusion(arr, threshold, algo, cancel)
    return arr < threshold


def _prepare_logo_image(image, width_mm, height_mm, angle, contrast, invert, tuning=None):
    """Misma rotación, contraste y elección de zonas en todas las vistas/Gerber."""
    from PIL import ImageEnhance, ImageOps
    background = (0, 0, 0) if invert else (255, 255, 255)
    if image.mode in {'RGBA', 'LA'} or 'transparency' in image.info:
        original = Image.alpha_composite(Image.new('RGBA', image.size, background+(255,)),
                                         image.convert('RGBA')).convert('RGB')
    else:
        original = image.convert('RGB')
    if angle % 360:
        original = original.rotate(-angle, expand=True, resample=Image.BICUBIC, fillcolor=background)
        radians = math.radians(angle)
        c, s = abs(math.cos(radians)), abs(math.sin(radians))
        width_mm, height_mm = width_mm*c+height_mm*s, width_mm*s+height_mm*c
    gray = original.convert('L')
    if contrast != 1.0:
        gray = ImageEnhance.Contrast(gray).enhance(contrast)
    options=validate_tuning(tuning)
    if options!=TUNING_DEFAULTS:
        gray=tune_gray(gray,options)
        if image.mode in {'RGBA','LA'} or 'transparency' in image.info:
            alpha=image.convert('RGBA').getchannel('A')
            if angle%360:alpha=alpha.rotate(-angle,expand=True,resample=Image.BICUBIC,fillcolor=0)
            gray.paste(0 if invert else 255,(0,0),alpha.point(lambda a:255 if a==0 else 0))
    if invert:
        gray = ImageOps.invert(gray)
    return original, gray, width_mm, height_mm


def _image_ink_mask(gray, width_mm, height_mm, pixel_mm, algorithm, threshold, limit=None):
    import numpy as np
    cols = max(1, int(round(width_mm/pixel_mm)))
    rows = max(1, int(round(height_mm/pixel_mm)))
    small = gray.resize((cols, rows), Image.LANCZOS)
    ink = _raster_ink_mask(np.array(small, dtype=np.float32), algorithm, threshold)
    if limit and max(cols, rows) > limit:
        factor = limit/max(cols, rows)
        size = max(1, int(cols*factor)), max(1, int(rows*factor))
        # Display reduction happens after conversion, never on the source tones.
        # Resizing gray first changes both threshold coverage and dithering.
        return np.asarray(Image.fromarray(ink).resize(size, Image.Resampling.NEAREST), dtype=bool)
    return ink


def _compute_logo_raster(image, width_mm, height_mm, angle, contrast, invert,
                         pixel_mm, algorithm, threshold, tuning=None, *, cancel=None, prepared_cache=None):
    """Pure image work: safe to run outside Tk for large dithered previews."""
    import numpy as np
    options=validate_tuning(tuning)
    key=(id(image),width_mm,height_mm,angle,contrast,invert,pixel_mm,tuple(sorted(options.items())))
    def prepare():
        check_cancel(cancel)
        original,gray,width,height=_prepare_logo_image(image,width_mm,height_mm,angle,contrast,invert,options)
        cols,rows=max(1,round(width/pixel_mm)),max(1,round(height/pixel_mm))
        small=np.asarray(gray.resize((cols,rows),Image.Resampling.LANCZOS),dtype=np.float32)
        return image,original,small,width,height
    _,original,small,width,height=prepared_cache.get_or_create(key,prepare) if prepared_cache else prepare()
    ink = _raster_ink_mask(small,algorithm,threshold,cancel)
    check_cancel(cancel)
    return {'original': original, 'mask': Image.fromarray(ink.astype(np.uint8)*255),
            'width_mm': width, 'height_mm': height, 'pixel_mm': pixel_mm}


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
        # 1) La misma máscara que las vistas previas, a resolución de fabricación.
        dark_dith = _image_ink_mask(gray, width_mm, height_mm, px_mm, dither_algo, threshold)
        dith_rows, dith_cols = dark_dith.shape

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

        # Precalcular las rachas (runs) por fila una sola vez
        runs = []  # (cy_enc, cx1_enc, cx2_enc); include isolated ink pixels.
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
                x1_mm = x_mm + (start + 0.5) * cell_w
                x2_mm = x_mm + (end + 0.5) * cell_w
                runs.append((cy, enc(x1_mm, fmt_x), enc(x2_mm, fmt_x)))

        def emit_runs():
            for cy, cx1, cx2 in runs:
                if cx1 == cx2:
                    # A flash retains a one-pixel dot. Dropping short runs
                    # destroyed dithering coverage despite a correct threshold.
                    cmds.append(f'X{cx1}Y{cy}D03*')
                else:
                    cmds.append(f'G01X{cx1}Y{cy}D02*')
                    cmds.append(f'X{cx2}Y{cy}D01*')

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
            emit_runs()

            # Paso 2: borrar el anillo exterior usando apertura dilatada (logo + clearance a cada lado)
            clear_w = (line_w_mm + 2 * clearance_mm) / unit_div
            dc = free_dcode(90, used); used.add(dc)
            cmds.append(f"%ADD{dc}C,{clear_w:.5f}*%")
            cmds.append("%LPC*%")
            cmds.append(f"G54D{dc}*")
            emit_runs()

            # Paso 3: restaurar el logo que quedó dentro del área borrada
            cmds.append("%LPD*%")
            cmds.append(f"G54D{d_logo}*")
            emit_runs()

        else:
            # Sin clearance: solo el logo
            cmds.append("%LPD*%")
            cmds.append(f"G54D{d_logo}*")
            emit_runs()

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
    GRID_COLOR = "#181818"
    BG_COLOR = "#000000"
    PCB_COLOR = "#000000"
    TRACE_COLOR = "#c8a020"
    SILK_COLOR = "#ffffff"
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
        canvas_frame = tk.Frame(main, bg=self.BG_COLOR)
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

        section("🎚 Umbral B/N · compartido")
        self.threshold_scale = tk.Scale(parent, variable=self.overlay_threshold, from_=0, to=255,
                 orient="horizontal", bg="#252535", fg="white", troughcolor="#1a1a2e",
                 highlightthickness=0,
                 command=self._main_threshold_changed
                 )
        self.threshold_scale.pack(fill="x")
        tk.Label(parent, text="Mismo valor en el editor y en el Gerber.\nEn tramas fijas, usa Brillo / Gamma.",
                 bg="#252535", fg="#bbc4dc", font=("Segoe UI", 8),
                 wraplength=190, justify="left").pack(fill="x")

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

    @staticmethod
    def _is_silkscreen(name, layer):
        return layer_role(name,layer) in ('TOP_SILK','BOTTOM_SILK')

    def _default_layer_color(self, name, layer):
        if self._is_silkscreen(name, layer):
            return self.SILK_COLOR
        return self.LAYER_COLORS[len(self.gerber_layers) % len(self.LAYER_COLORS)]

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
                color = self._default_layer_color(filepath, layer)
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
            name = f"{layer_label(entry['name'],entry['layer'])} ({Path(entry['name']).suffix[1:].upper()})"
            tk.Label(row, text=name, bg="#252535", fg="#aaaacc",
                     font=("Segoe UI", 8), anchor="w",justify='left',wraplength=145).pack(side="left", fill="x", expand=True)
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
        if hasattr(self,'save_project_session'):self.save_project_session()

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
        outline=self._find_outline_layer()
        if outline:
            from panel_model import geometry_bounds
            return geometry_bounds(outline['layer'],outline=True)
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
        if not layer.drawables:
            return
        color = entry["color"]
        dim = color if self._is_silkscreen(entry['name'], layer) else self._dim_color(color)
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

    def _logo_raster_request(self, thresh=None, *, algorithm=None, contrast=None, invert=None,
                             pixel_mm=None, angle=None, tuning=None):
        try: dot = max(.15, float(self.entry_dot.get()))
        except ValueError: dot = .15
        thresh = self.overlay_threshold.get() if thresh is None else thresh
        algorithm = getattr(self, '_conv_algo', 'threshold') if algorithm is None else algorithm
        contrast = getattr(self, '_conv_contrast', 1.0) if contrast is None else contrast
        invert = getattr(self, '_conv_invert', False) if invert is None else invert
        pixel_mm = max(dot, getattr(self, '_conv_pxsize', dot) if pixel_mm is None else pixel_mm)
        angle = self.overlay_angle_deg if angle is None else angle
        tuning=validate_tuning(getattr(self,'_conv_tuning',None) if tuning is None else tuning)
        key = (id(self.overlay_image), self.overlay_w_mm, self.overlay_h_mm, angle,
               thresh, algorithm, contrast, invert, pixel_mm,tuple(sorted(tuning.items())))
        parameters = (self.overlay_image, self.overlay_w_mm, self.overlay_h_mm, angle,
                      contrast, invert, pixel_mm, algorithm, thresh,tuning)
        return key, parameters

    def _cache_logo_raster(self, key, raster):
        cache = getattr(self, '_logo_raster_cache', {})
        if len(cache) >= 4 and key not in cache: cache.pop(next(iter(cache)))
        cache[key] = raster
        self._logo_raster_cache = cache

    def _logo_raster(self, thresh=None, *, algorithm=None, contrast=None, invert=None,
                     pixel_mm=None, angle=None, limit=600):
        # Retain limit for callers, but always convert at the fabrication grid.
        # Widgets resize the finished binary mask only for screen display.
        key, parameters = self._logo_raster_request(thresh, algorithm=algorithm, contrast=contrast,
                                                   invert=invert, pixel_mm=pixel_mm, angle=angle)
        cache = getattr(self, '_logo_raster_cache', {})
        if key not in cache:
            self._cache_logo_raster(key, _compute_logo_raster(*parameters,prepared_cache=self._prepared_cache()))
        return self._logo_raster_cache[key]

    def _prepared_cache(self):
        if not hasattr(self,'_prepared_image_cache'):self._prepared_image_cache=PreparedCache()
        return self._prepared_image_cache

    def _make_overlay_image(self, disp_w: int, disp_h: int, thresh: int, angle: float):
        raster = self._logo_raster(thresh, angle=angle)
        width = max(4, round(disp_w*raster['width_mm']/self.overlay_w_mm))
        height = max(4, round(disp_h*raster['height_mm']/self.overlay_h_mm))
        mask = ink_preview(raster['mask'], (width, height))
        mask = self._clip_logo_mask(mask, raster['width_mm'], raster['height_mm'])
        rgba = Image.new('RGBA', mask.size, 'white')
        rgba.putalpha(mask)
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

        cache_key = (id(self.overlay_image), thresh, angle, disp_w, disp_h,
                     self.overlay_w_mm, self.overlay_h_mm, self.entry_dot.get(),
                     getattr(self, '_conv_algo', 'threshold'), getattr(self, '_conv_contrast', 1.0),
                     getattr(self, '_conv_invert', False), getattr(self, '_conv_pxsize', None),
                     self.overlay_x_mm, self.overlay_y_mm, self._board_clip_key())
        if cache_key != self._overlay_cache_key:
            rgba = self._make_overlay_image(disp_w, disp_h, thresh, angle)
            self._overlay_tk_cache = ImageTk.PhotoImage(rgba,master=self)
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
            if entry["var_visible"].get() and entry["layer"].drawables:
                b = entry["layer"].bounds
                xs += [b[0], b[2]]; ys += [b[1], b[3]]
        if xs:
            return (min(xs), min(ys), max(xs), max(ys))
        return (0, 0, 100, 100)

    # ── Exportación ────────────────────────────────

    # ── Editor de conversión de imagen ──────────────────────────────────

    # Parámetros JLCPCB: mínimo trazo 0.15mm, pitch mínimo recomendado 0.15mm
    JLCPCB_MIN_MM = 0.15

    def _refresh_overlay_only(self):
        for tag in ('overlay','overlay_border','overlay_handle','overlay_center'):
            self.canvas.delete(tag)
        if self.overlay_image:self._draw_overlay()

    def _cancel_main_preview(self, stop=False):
        token=getattr(self,'_main_preview_cancel',None)
        if token is not None:token.set()
        future=getattr(self,'_main_preview_future',None)
        if future is not None:future.cancel()
        timer=getattr(self,'_main_preview_poll',None)
        if timer:
            try:self.after_cancel(timer)
            except tk.TclError:pass
        self._main_preview_poll=None;self._main_preview_key=None
        executor=getattr(self,'_main_preview_executor',None)
        if stop and executor is not None:
            executor.shutdown(wait=False,cancel_futures=True);self._main_preview_executor=None

    def _main_threshold_changed(self,value=None):
        self._overlay_cache_key=None
        editor=getattr(self,'_conv_editor',None)
        if editor is not None and editor.winfo_exists():return
        self._schedule_main_preview()

    def _schedule_main_preview(self):
        if self.overlay_image is None:return
        from concurrent.futures import ThreadPoolExecutor
        import threading
        key,parameters=self._logo_raster_request()
        if key in getattr(self,'_logo_raster_cache',{}):
            self._overlay_cache_key=None;self._refresh_overlay_only();return
        self._cancel_main_preview()
        if getattr(self,'_main_preview_executor',None) is None:
            self._main_preview_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='main-ink')
        if not getattr(self,'_preview_destroy_bound',False):
            def destroyed(event):
                if event.widget is self:self._cancel_main_preview(stop=True)
            self.bind('<Destroy>',destroyed,add='+');self._preview_destroy_bound=True
        cancel=threading.Event();self._main_preview_cancel=cancel;self._main_preview_key=key
        future=self._main_preview_executor.submit(_compute_logo_raster,*parameters,
            cancel=cancel,prepared_cache=self._prepared_cache())
        self._main_preview_future=future
        def poll():
            self._main_preview_poll=None
            if self._main_preview_key!=key:return
            if not future.done():self._main_preview_poll=self.after(25,poll);return
            try:
                raster=future.result()
                current,_=self._logo_raster_request()
                if current!=key:return
                self._cache_logo_raster(key,raster);self._overlay_cache_key=None
                self._refresh_overlay_only()
            except PreviewCancelled:pass
            except Exception as error:self.info_var.set('Error de conversión: '+str(error))
        self._main_preview_poll=self.after(25,poll)

    def _commit_conversion_editor(self):
        """An open image editor must never export older, unapplied settings."""
        win = getattr(self, '_conv_editor', None)
        commit = getattr(self, '_conv_commit', None)
        if win is not None and win.winfo_exists() and commit is not None:
            if not commit():
                win.lift()
                return False
        return True

    def _open_conversion_editor(self):
        if not self.overlay_image:
            messagebox.showwarning("Aviso", "Importa una imagen primero.")
            return

        # Ventana no modal, independiente
        if hasattr(self, '_conv_editor') and self._conv_editor.winfo_exists():
            self._conv_editor.lift(); return
        self._cancel_main_preview()

        win = tk.Toplevel(self)
        win.title("Editor de conversión")
        win.configure(bg="#252535")
        win.geometry(f"{min(1200, self.winfo_screenwidth()-60)}x{min(900, self.winfo_screenheight()-100)}")
        win.minsize(850, 600)
        win.resizable(True, True)
        self._conv_editor = win

        # ── Parámetros (izquierda) ──
        from tkinter import font as tkfont
        control_font = ("Segoe UI", 11)
        label_font = ("Segoe UI", 10, "bold")
        sidebar_width = max(310, tkfont.Font(win, font=control_font).measure("Dithering Floyd-Steinberg") + 55)
        sidebar = tk.Frame(win, bg="#252535", width=sidebar_width)
        sidebar.pack(side="left", fill="y", padx=10, pady=10)
        sidebar.pack_propagate(False)
        actions = tk.Frame(sidebar, bg="#252535")
        actions.pack(side="bottom", fill="x")
        scroller = tk.Canvas(sidebar, bg="#252535", highlightthickness=0)
        scrollbar = ttk.Scrollbar(sidebar, orient="vertical", command=scroller.yview)
        scrollbar.pack(side="right", fill="y")
        scroller.pack(side="left", fill="both", expand=True)
        scroller.configure(yscrollcommand=scrollbar.set)
        left = tk.Frame(scroller, bg="#252535")
        controls_id = scroller.create_window(0, 0, window=left, anchor="nw")
        left.bind("<Configure>", lambda e: scroller.configure(scrollregion=scroller.bbox("all")))
        scroller.bind("<Configure>", lambda e: scroller.itemconfigure(controls_id, width=e.width))
        def scroll_controls(event):
            widget = event.widget
            while widget is not None:
                if widget is sidebar:
                    scroller.yview_scroll(-1 if event.delta > 0 else 1, "units")
                    return "break"
                widget = getattr(widget, 'master', None)
        win.bind("<MouseWheel>", scroll_controls, add="+")

        def lbl(text, fg="#ccccdd"):
            tk.Label(left, text=text, bg="#252535", fg=fg,
                     font=label_font, wraplength=sidebar_width-35, justify="left",
                     anchor="w").pack(fill="x", pady=(8,1))
        def sep():
            tk.Frame(left, bg="#444466", height=1).pack(fill="x", pady=4)

        value_hint = "Enter confirma · Se admite coma decimal"
        value_status = tk.StringVar(win, value=value_hint)
        numeric_controls = []
        control_traces = []

        def numeric_control(variable, minimum, maximum, step, default, name, title, host=None):
            host=left if host is None else host
            # El texto en edición se mantiene separado del valor numérico válido.
            # Borrar un campo o escribir una coma nunca rompe el render/exportación.
            row = tk.Frame(host, bg="#252535", name=name+"_control")
            row.pack(fill="x", pady=(2, 0))
            row.grid_columnconfigure(1, weight=1)
            text = tk.StringVar(win)
            def sync_text(*_):
                value = variable.get()
                text.set(str(int(value)) if step == 1 else f"{value:.2f}".replace('.', ','))
            sync_text()
            control_traces.append((variable, variable.trace_add('write', sync_text)))

            entry = tk.Entry(row, textvariable=text, name="value", width=7,
                             justify="center", bg="#1a1a2e", fg="white",
                             insertbackground="white", font=control_font)
            entry.grid(row=0, column=1, sticky="ew", padx=4)

            def commit(event=None, revert=False):
                try:
                    value = float(text.get().strip().replace(',', '.'))
                    if not math.isfinite(value): raise ValueError()
                except ValueError:
                    if revert:
                        sync_text()
                        entry.configure(bg="#1a1a2e")
                        value_status.set(value_hint)
                    else:
                        entry.configure(bg="#71353b")
                        value_status.set(f"{title}: introduce un número válido")
                        entry.focus_set()
                    return False
                value = max(minimum, min(maximum, value))
                value = int(round(value)) if step == 1 else round(value, 2)
                changed = value != variable.get()
                variable.set(value)
                sync_text()
                entry.configure(bg="#1a1a2e")
                value_status.set(value_hint)
                if changed: refresh(fast=False)
                return True

            def nudge(direction):
                # Confirmar un número escrito antes de hacer el ajuste fino.
                if not commit(): return "break"
                text.set(str(variable.get() + direction*step))
                commit()
                return "break"

            def reset():
                text.set(str(default))
                commit()

            buttons = []
            for column, caption, command in ((0, "−", lambda: nudge(-1)),
                                              (2, "+", lambda: nudge(1)),
                                              (3, "Restablecer", reset)):
                button = tk.Button(row, text=caption, command=command,
                                   bg="#3a3a5c", fg="white", relief="flat",
                                   font=("Segoe UI", 10), padx=6,
                                   repeatdelay=350, repeatinterval=80)
                button.grid(row=0, column=column)
                buttons.append(button)
            entry.bind("<Return>", lambda e: (commit(), "break")[1])
            entry.bind("<FocusOut>", lambda e: commit())
            entry.bind("<Up>", lambda e: nudge(1))
            entry.bind("<Down>", lambda e: nudge(-1))
            scale = tk.Scale(host, variable=variable, from_=minimum, to=maximum,
                             resolution=step, orient="horizontal", showvalue=False,
                             bg="#252535", fg="white", troughcolor="#1a1a2e",
                             font=control_font, highlightthickness=0,
                             command=lambda v: refresh(fast=True))
            scale.pack(fill="x")
            control = {'commit': commit, 'entry': entry, 'widgets': [entry, scale, *buttons]}
            numeric_controls.append(control)
            return control

        # Algoritmo
        lbl("Algoritmo de conversión")
        algo_var = tk.StringVar(value=getattr(self, '_conv_algo', 'threshold'))
        algos = [
            ("Umbral simple",       "threshold"),
            ("Floyd rápido · fotografía", "floyd_fast"),
            ("Dithering Floyd-Steinberg", "floyd"),
            ("Dithering Atkinson",  "atkinson"),
            ("Dithering Bayer 4×4", "bayer4"),
            ("Dithering Bayer 2×2", "bayer2"),
            ("Dithering Bayer 8×8", "bayer8"),
            ("Dithering Stucki",    "stucki"),
            ("Dithering Jarvis",    "jarvis"),
            ("Trama agrupada 4×4", "clustered4"),
        ]
        common={'threshold','floyd_fast','atkinson'}
        other_algorithms=tk.Frame(left,bg='#252535')
        def toggle_algorithms():
            if other_algorithms.winfo_manager():other_algorithms.pack_forget();more_algorithms.configure(text='Más algoritmos y tramas ▸')
            else:other_algorithms.pack(fill='x',after=more_algorithms);more_algorithms.configure(text='Más algoritmos y tramas ▾')
        for txt, val in algos:
            tk.Radiobutton(left if val in common else other_algorithms, text=txt, variable=algo_var, value=val,
                           bg="#252535", fg="#ddddee", selectcolor="#1a1a2e",
                           activebackground="#252535", font=control_font,
                           anchor="w", command=lambda: algorithm_changed()
                           ).pack(fill="x", padx=4)
        more_algorithms=tk.Button(left,text='Más algoritmos y tramas ▸',command=toggle_algorithms,
            bg='#3a3a5c',fg='white',relief='flat',font=('Segoe UI',9))
        more_algorithms.pack(fill='x',pady=3)
        if algo_var.get() not in common:toggle_algorithms()

        sep()
        lbl("Umbral (0–255)")
        thresh_var = self.overlay_threshold
        threshold_control = numeric_control(thresh_var, 0, 255, 1, 128, 'threshold', 'Umbral')
        threshold_hint = tk.Label(left, bg="#252535", fg="#88aacc", height=2,
                                  font=("Segoe UI", 9), wraplength=sidebar_width-35,
                                  justify="left", anchor="w")
        threshold_hint.pack(fill="x")

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

        pxsize_var = tk.DoubleVar(value=min(max(min_px, getattr(self, '_conv_pxsize', float(self.entry_dot.get()))), max_px))
        numeric_control(pxsize_var, min_px, max_px, .01, min_px, 'pixel', 'Píxel')
        px_info = tk.Label(left, text="", height=2, bg="#252535", fg="#ffcc44", font=("Segoe UI", 10))
        px_info.pack()

        sep()
        lbl("Contraste (1,00 = original)")
        contrast_var = tk.DoubleVar(value=getattr(self, '_conv_contrast', 1.0))
        numeric_control(contrast_var, .3, 3.0, .01, 1.0, 'contrast', 'Contraste')

        tuning=validate_tuning(getattr(self,'_conv_tuning',None))
        tuning_vars={name:tk.DoubleVar(value=value) for name,value in tuning.items()}
        advanced=tk.Frame(left,bg='#252535')
        def toggle_advanced():
            if advanced.winfo_manager():advanced.pack_forget();advanced_button.configure(text='Ajustes finos ▸')
            else:advanced.pack(fill='x',after=advanced_button);advanced_button.configure(text='Ajustes finos ▾')
        advanced_button=tk.Button(left,text='Ajustes finos ▸',command=toggle_advanced,bg='#3a3a5c',fg='white',relief='flat',font=label_font)
        advanced_button.pack(fill='x',pady=8)
        for title,name,low,high,step in [('Brillo','brightness',.3,2.,.05),('Gamma · medios tonos','gamma',.3,3.,.05),
                                       ('Nitidez','sharpness',0.,3.,.1),('Suavizado (px de imagen)','smoothing',0.,2.,.1)]:
            tk.Label(advanced,text=title,bg='#252535',fg='#ccccdd',font=label_font).pack(anchor='w')
            numeric_control(tuning_vars[name],low,high,step,TUNING_DEFAULTS[name],name,title,host=advanced)

        def algorithm_changed(render=True):
            bayer = algo_var.get() in ('bayer2','bayer4','bayer8','clustered4')
            for widget in threshold_control['widgets']:
                widget.configure(state='disabled' if bayer else 'normal')
            threshold_hint.configure(text="Trama fija: ajusta Brillo / Gamma y píxel."
                                     if bayer else "Umbral ajusta la conversión. En fotografías, prueba también Brillo / Gamma.")
            if render: refresh(fast=True)
        algorithm_changed(render=False)

        sep()
        lbl("Qué zonas reciben tinta blanca")
        invert_var = tk.BooleanVar(value=getattr(self, '_conv_invert', False))
        for caption, value in (("Claros → tinta blanca (foto positiva)", True),
                               ("Oscuros → tinta blanca (foto negativa)", False)):
            tk.Radiobutton(left, text=caption, variable=invert_var, value=value,
                           bg="#252535", fg="#ddddee", selectcolor="#1a1a2e",
                           activebackground="#252535", font=control_font,
                           wraplength=sidebar_width-35, justify="left", anchor="w",
                           command=lambda: refresh(fast=False)).pack(fill="x")

        sep()
        tk.Label(actions, textvariable=value_status, bg="#252535", fg="#ffcc44",
                 font=("Segoe UI", 9), height=2, wraplength=sidebar_width-35,
                 justify="left").pack(fill="x")
        # Botón aplicar: transfiere los parámetros a la ventana principal
        def apply_to_main(notify=True):
            for control in numeric_controls:
                if not control['commit'](): return False
            self.overlay_threshold.set(thresh_var.get())
            # El trazo de exportación siempre es 0.15mm (JLCPCB)
            self.entry_dot.delete(0, "end")
            self.entry_dot.insert(0, f"{self.JLCPCB_MIN_MM:.2f}")
            self._conv_algo = algo_var.get()
            self.threshold_scale.configure(state='disabled' if self._conv_algo in ('bayer2','bayer4','bayer8','clustered4') else 'normal')
            self._conv_contrast = contrast_var.get()
            self._conv_invert = invert_var.get()
            self._conv_pxsize = pxsize_var.get()   # tamaño de píxel para dithering
            self._conv_tuning=validate_tuning({name:var.get() for name,var in tuning_vars.items()})
            self._overlay_cache_key = None
            self._schedule_main_preview()
            refresh(fast=False)
            if notify:
                messagebox.showinfo("Aplicado",
                    f"Umbral B/N compartido: {thresh_var.get()}\n"
                    f"Exportación: trazo 0.15mm (JLCPCB)\n"
                    f"Dithering: píxel {pxsize_var.get():.2f}mm · {algo_var.get()}\n"
                    f"Contraste: {contrast_var.get():.2f}", parent=win)
            return True

        self._conv_commit = lambda: apply_to_main(notify=False)

        before_auto=None
        def snapshot():
            return dict(threshold=thresh_var.get(),algorithm=algo_var.get(),contrast=contrast_var.get(),
                invert=invert_var.get(),pixel=pxsize_var.get(),tuning={n:v.get() for n,v in tuning_vars.items()})
        def set_values(values):
            thresh_var.set(values['threshold']);algo_var.set(values['algorithm']);contrast_var.set(values['contrast'])
            if 'invert' in values:invert_var.set(values['invert'])
            if 'pixel' in values:pxsize_var.set(values['pixel'])
            for name,value in values['tuning'].items():tuning_vars[name].set(value)
            for control in numeric_controls:control['commit']()
            algorithm_changed(render=False);refresh(fast=False)
        def auto_adjust():
            nonlocal before_auto
            try:
                suggestion=auto_settings(self.overlay_image,invert_var.get())
                before_auto=snapshot();set_values(suggestion)
                undo_auto.configure(state='normal')
                value_status.set(f"Auto: {suggestion['kind']} · contraste {suggestion['contrast']:.2f} · umbral {suggestion['threshold']}. Propuesta ajustable.")
            except ValueError as error:value_status.set(str(error))
        def revert_auto():
            nonlocal before_auto
            if before_auto is not None:
                set_values(before_auto);before_auto=None;undo_auto.configure(state='disabled')
                value_status.set('Se han recuperado los ajustes anteriores a Auto.')
        auto_row=tk.Frame(actions,bg='#252535');auto_row.pack(fill='x',before=actions.winfo_children()[0])
        tk.Button(auto_row,text='Auto · ajustar imagen',command=auto_adjust,bg='#285b67',fg='white',relief='flat',font=('Segoe UI',10,'bold')).pack(side='left',fill='x',expand=True)
        undo_auto=tk.Button(auto_row,text='Revertir Auto',command=revert_auto,state='disabled',bg='#3a3a5c',fg='white',relief='flat',font=('Segoe UI',9))
        undo_auto.pack(side='right',padx=(3,0))

        def close_editor():
            if apply_to_main(notify=False):
                win.destroy()

        tk.Button(actions, text="✅ Aplicar a PCB y exportación", command=apply_to_main,
                  bg="#2244aa", fg="white", relief="flat",
                  font=("Segoe UI", 11, "bold"), pady=6).pack(fill="x", pady=(8,2))
        tk.Button(actions, text="Cerrar y aplicar", command=close_editor,
                  bg="#3a3a5c", fg="white", relief="flat",
                  font=control_font, pady=4).pack(fill="x")

        # ── Preview (derecha) ──
        right = tk.Frame(win, bg="#1a1a2e")
        right.pack(side="left", fill="both", expand=True, padx=(0,10), pady=10)

        top_bar = tk.Frame(right, bg="#1a1a2e")
        top_bar.pack(fill="x", pady=(0,4))
        tk.Label(top_bar, text="Original", bg="#1a1a2e", fg="#aaaacc",
                 font=control_font).pack(side="left", padx=8)
        tk.Label(top_bar, text="Resultado · tinta blanca", bg="#1a1a2e", fg="#ffcc44",
                 font=control_font).pack(side="right", padx=8)
        displayed_mask = None
        def show_pixels():
            if displayed_mask is None:return
            detail=tk.Toplevel(win)
            detail.title('Puntos de tinta · detalle 1:1')
            detail.geometry(f'{min(1000,win.winfo_screenwidth()-80)}x{min(750,win.winfo_screenheight()-100)}')
            tk.Label(detail,text='Un píxel por punto · Arrastra para recorrer la imagen. Detalle de la conversión al abrir esta ventana.',
                     bg='#252535',fg='white',wraplength=800).pack(fill='x')
            frame=tk.Frame(detail);frame.pack(fill='both',expand=True)
            canvas=tk.Canvas(frame,bg='black',highlightthickness=0)
            sx=tk.Scrollbar(frame,orient='horizontal',command=canvas.xview)
            sy=tk.Scrollbar(frame,orient='vertical',command=canvas.yview)
            canvas.configure(xscrollcommand=sx.set,yscrollcommand=sy.set)
            frame.grid_rowconfigure(0,weight=1);frame.grid_columnconfigure(0,weight=1)
            canvas.grid(row=0,column=0,sticky='nsew');sx.grid(row=1,column=0,sticky='ew');sy.grid(row=0,column=1,sticky='ns')
            canvas.image=ImageTk.PhotoImage(displayed_mask,master=detail)
            canvas.create_image(0,0,image=canvas.image,anchor='nw')
            canvas.configure(scrollregion=(0,0,*displayed_mask.size))
            canvas.bind('<ButtonPress-1>',lambda e:canvas.scan_mark(e.x,e.y))
            canvas.bind('<B1-Motion>',lambda e:canvas.scan_dragto(e.x,e.y,gain=1))
            canvas.bind('<MouseWheel>',lambda e:canvas.yview_scroll(-int(e.delta/120),'units'))
            canvas.bind('<Shift-MouseWheel>',lambda e:canvas.xview_scroll(-int(e.delta/120),'units'))
            detail.bind('<Escape>',lambda e:detail.destroy())
        pixel_button=tk.Button(top_bar,text='Ver puntos 1:1…',command=show_pixels,state='disabled',
            bg='#3a3a5c',fg='white',relief='flat',font=control_font)
        pixel_button.pack(side='right',padx=8)

        preview_frame = tk.Frame(right, bg="#1a1a2e")
        preview_frame.pack(fill="both", expand=True)

        # Las imágenes no deben determinar el tamaño de su propia vista previa.
        # Cada mitad conserva su espacio aunque cambie la resolución del resultado.
        preview_frame.grid_columnconfigure((0, 1), weight=1, uniform="preview")
        preview_frame.grid_rowconfigure(0, weight=1)
        viewports = []
        for column in (0, 1):
            viewport = tk.Frame(preview_frame, bg="#000000", width=1, height=1)
            viewport.grid(row=0, column=column, sticky="nsew", padx=2)
            viewport.grid_propagate(False)
            viewports.append(viewport)
        lbl_orig = tk.Label(viewports[0], bg="#000000", borderwidth=0)
        lbl_orig.place(relx=.5, rely=.5, anchor="center")
        lbl_conv = tk.Label(viewports[1], bg="#000000", borderwidth=0)
        lbl_conv.place(relx=.5, rely=.5, anchor="center")

        info_lbl = tk.Label(right, text="", bg="#1a1a2e", fg="#888899",
                            font=("Segoe UI", 10), width=1, height=3)
        info_lbl.pack(fill="x", pady=2)

        self._conv_refresh_id = None
        self._conv_quality_id = None
        self._conv_poll_id = None
        preview_executor = None
        preview_future = None
        preview_key = None
        preview_cancel = None
        original_photo_key = None

        def cancel_pending():
            for attr in ('_conv_refresh_id', '_conv_quality_id', '_conv_poll_id'):
                rid = getattr(self, attr, None)
                if rid:
                    try: win.after_cancel(rid)
                    except tk.TclError: pass
                setattr(self, attr, None)

        def refresh(fast=True):
            cancel_pending()
            if not win.winfo_exists(): return
            pixel_button.configure(state='disabled')
            pending=getattr(self,'_main_preview_key',None)
            if pending is not None:
                desired,_=self._logo_raster_request(thresh_var.get(),algorithm=algo_var.get(),contrast=contrast_var.get(),
                    invert=invert_var.get(),pixel_mm=pxsize_var.get(),tuning={n:v.get() for n,v in tuning_vars.items()})
                if desired!=pending:self._cancel_main_preview()

            def render(fast, timer_attr):
                setattr(self, timer_attr, None)
                if not win.winfo_exists(): return
                try: _render_preview(fast=fast)
                except Exception as e: info_lbl.config(text=f"Error: {e}")

            if preview_cancel is not None:preview_cancel.set()
            self._conv_refresh_id=win.after(90 if fast else 40,lambda:render(False,'_conv_refresh_id'))

        def _render_preview(fast=False):
            nonlocal preview_executor, preview_future, preview_key, preview_cancel
            if self._conv_poll_id:
                win.after_cancel(self._conv_poll_id)
                self._conv_poll_id = None
            key, parameters = self._logo_raster_request(thresh_var.get(), algorithm=algo_var.get(),
                contrast=contrast_var.get(), invert=invert_var.get(), pixel_mm=pxsize_var.get(),
                tuning={name:var.get() for name,var in tuning_vars.items()})
            raster = getattr(self, '_logo_raster_cache', {}).get(key)
            if raster is not None:
                _display_preview(raster, fast)
                return
            cells = parameters[1]*parameters[2]/parameters[6]**2
            if cells > 40_000 or self.overlay_image.width*self.overlay_image.height>250_000:
                from concurrent.futures import ThreadPoolExecutor
                shared=getattr(self,'_main_preview_key',None)==key and getattr(self,'_main_preview_future',None) is not None
                if shared:
                    if preview_cancel is not None:preview_cancel.set()
                    preview_cancel=None;preview_future=self._main_preview_future;preview_key=key
                elif preview_executor is None:
                    preview_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='gerber-preview')
                if not shared and (preview_future is None or preview_key != key or preview_cancel is None or preview_future.cancelled() or preview_cancel.is_set()):
                    import threading
                    if preview_cancel is not None:preview_cancel.set()
                    if preview_future is not None: preview_future.cancel()
                    preview_cancel=threading.Event()
                    preview_future = preview_executor.submit(_compute_logo_raster, *parameters,
                        cancel=preview_cancel,prepared_cache=self._prepared_cache())
                    preview_key = key
                future = preview_future
                info_lbl.config(text=f'Calculando la misma máscara que el Gerber…\nUmbral: {thresh_var.get()} · {algo_var.get()}')
                def poll_preview():
                    self._conv_poll_id = None
                    if not win.winfo_exists(): return
                    if not future.done():
                        self._conv_poll_id = win.after(50, poll_preview)
                        return
                    try:
                        result = future.result()
                        self._cache_logo_raster(key, result)
                        _display_preview(result, fast)
                    except PreviewCancelled:pass
                    except Exception as error:
                        info_lbl.config(text=f'Error: {error}')
                poll_preview()
                return
            raster = _compute_logo_raster(*parameters,prepared_cache=self._prepared_cache())
            self._cache_logo_raster(key, raster)
            _display_preview(raster, fast)

        def _display_preview(raster, fast=False):
            nonlocal original_photo_key, displayed_mask
            from PIL import Image as PILImg, ImageTk as PILImageTk
            import numpy as np
            PW = max(1, min(viewport.winfo_width() for viewport in viewports)-4)
            PH = max(1, preview_frame.winfo_height()-4)
            width, height = raster['width_mm'], raster['height_mm']
            scale = min(PW/width, PH/height)
            display_size = (max(1, int(width*scale)), max(1, int(height*scale)))
            original_key=(id(self.overlay_image),self.overlay_angle_deg,invert_var.get(),display_size)
            if original_key!=original_photo_key:
                original = raster['original'].convert('RGB').resize(display_size, PILImg.LANCZOS)
                tk_orig=PILImageTk.PhotoImage(original)
                lbl_orig.config(image=tk_orig);lbl_orig.image=tk_orig;original_photo_key=original_key
            # Máscara de material: blanco es tinta, negro es placa sin tinta.
            result = ink_preview(raster['mask'], display_size)
            tk_conv = PILImageTk.PhotoImage(result)
            lbl_conv.config(image=tk_conv); lbl_conv.image = tk_conv
            displayed_mask=raster['mask'].copy()
            pixel_button.configure(state='normal')
            cols, rows = raster['mask'].size
            exp_cols, exp_rows = max(1, round(width/self.JLCPCB_MIN_MM)), max(1, round(height/self.JLCPCB_MIN_MM))
            px_info.config(text=f"Píxel visual: {raster['pixel_mm']:.2f}mm → {cols}×{rows} px\n"
                                 f"Exportación: 0.15mm → {exp_cols}×{exp_rows} px")
            applied = (thresh_var.get() == self.overlay_threshold.get()
                       and algo_var.get() == getattr(self, '_conv_algo', 'threshold')
                       and contrast_var.get() == getattr(self, '_conv_contrast', 1.0)
                       and invert_var.get() == getattr(self, '_conv_invert', False)
                       and validate_tuning({n:v.get() for n,v in tuning_vars.items()})==validate_tuning(getattr(self,'_conv_tuning',None))
                       and pxsize_var.get() == getattr(self, '_conv_pxsize', float(self.entry_dot.get())))
            state = "Aplicado a PCB y exportación" if applied else "Vista sin aplicar · se confirma al aplicar, cerrar o exportar"
            quality = " · vista ajustada suavizada; detalle en 1:1"
            info_lbl.config(text=f"Blanco = tinta · Negro = PCB sin tinta{quality}\n{state}\n"
                                 f"Umbral: {thresh_var.get()} · Puntos de tinta: {np.count_nonzero(np.array(raster['mask']))} · {algo_var.get()}")

        # Configure en un Toplevel también recibe los cambios de sus hijos.
        # Escuchar solo el área de preview evita que dibujar dispare otro render.
        preview_size = None
        def preview_resized(event):
            nonlocal preview_size
            size = (event.width, event.height)
            if event.widget is preview_frame and size != preview_size:
                preview_size = size
                refresh(fast=True)

        def editor_destroyed(event):
            if event.widget is win:
                cancel_pending()
                if preview_cancel is not None:preview_cancel.set()
                if preview_executor is not None:
                    preview_executor.shutdown(wait=False, cancel_futures=True)
                for variable, token in control_traces:
                    try: variable.trace_remove('write', token)
                    except tk.TclError: pass
                self._conv_commit = None

        def threshold_changed(*args):
            refresh(fast=True)
        control_traces.append((thresh_var, thresh_var.trace_add('write', threshold_changed)))

        preview_frame.bind("<Configure>", preview_resized)
        win.bind("<Destroy>", editor_destroyed, add="+")
        win.protocol('WM_DELETE_WINDOW', close_editor)
        refresh(fast=False)

    def export_gerber(self):
        if not self.gerber_layers:
            messagebox.showwarning("Aviso", "Primero carga al menos una capa Gerber.")
            return
        if not self._commit_conversion_editor():
            return
        if not self._save_before_output():return
        choices = self._choose_export_dialog(self._build_export_items())
        if not choices:
            return
        if not self._save_before_output():return
        source = getattr(self, 'fabrication_source', None)
        destination = getattr(self,'fabrication_destination',None) or (Path(source).parent if source else filedialog.askdirectory(
            title="Carpeta donde crear el nuevo paquete Gerber y ZIP")
        )
        if not destination:
            return
        try:
            from fabrication_export import FabricationExport
            baseline = {}
            def add_original(name, content):
                name = Path(name).name
                data = content.encode('utf-8')
                if name in baseline and baseline[name] != data:
                    raise ValueError(f"Hay dos capas diferentes con el mismo nombre: {name}")
                baseline[name] = data
            for entry in self.gerber_layers:
                add_original(entry['name'], ''.join(entry['layer'].raw_lines))
            drill_formats = {}
            for ref in getattr(self, 'drill_references', []):
                add_original(ref.name, ref.content)
                drill_formats[Path(ref.name).name] = list(ref.coord_format)
            if not source and drill_formats:
                formats = set(tuple(value) for value in drill_formats.values())
                if len(formats) == 1:
                    integer, decimal = formats.pop()
                    add_original('nc_param.txt', f'INTEGER-PLACES {integer}\nDECIMAL-PLACES {decimal}\n')
            changes, results = [], []
            with FabricationExport(destination, baseline, source) as package:
                for choice in choices:
                    item = choice['item']
                    name = f"{item['tag']}{item['ext']}"
                    output = package.path_for(name)
                    results.append(self._write_export_layer(choice, str(output), self.overlay_threshold.get()))
                    changes.append({'file': output.relative_to(package.work).as_posix(),
                                    'mode': choice['mode'], 'clearance_mm': choice.get('clearance', .5),
                                    'window_shape': choice.get('window_shape','rectangle')})
                settings = {'algorithm': getattr(self, '_conv_algo', 'threshold'),
                            'threshold': self.overlay_threshold.get(),
                            'contrast': getattr(self, '_conv_contrast', 1.0),
                            'invert': getattr(self, '_conv_invert', False),
                            'tuning': validate_tuning(getattr(self,'_conv_tuning',None)),
                            'pixel_mm': getattr(self, '_conv_pxsize', .15),
                            'x_mm': self.overlay_x_mm, 'y_mm': self.overlay_y_mm,
                            'width_mm': self.overlay_w_mm, 'height_mm': self.overlay_h_mm,
                            'angle_deg': self.overlay_angle_deg,
                            'clip_to_pcb_outline': self._find_outline_layer() is not None}
                from module_project import lineage
                editing_project=getattr(self,'silk_project',None) or getattr(self,'panel_project',None)
                if editing_project:settings['lineage']=lineage(editing_project)
                folder, archive = package.finish(changes, settings, drill_formats)
            if editing_project:
                from module_project import record_output
                record_output(editing_project,archive,source)
            self.last_export_zip, self.last_export_folder = archive, folder
            from export_result import show_export_result
            from release_contract import association,caption
            release=association(archive)
            show_export_result(self,'Liberación '+release['release_label']+' creada',archive,caption(release)+'\n\n'+'\n'.join(results))
            return archive
        except Exception as error:
            messagebox.showerror("Error de exportación", str(error), parent=self)

    def _save_before_output(self):
        try:
            if hasattr(self,'save_project_session'):self.save_project_session()
            return True
        except (OSError,ValueError) as error:
            messagebox.showerror('Guardar proyecto',str(error),parent=self)
            return False

    def _write_export_layer(self, ch, out_path, thresh):
        results = []
        if ch['mode'] != 'base' and self.overlay_image is None:
            raise ValueError('Importa una imagen antes de exportar una receta con logo.')
        item = ch["item"]
        mode = ch["mode"]
        clr = ch.get("clearance", 0.5)   # holgura específica de esta capa
        tag = item["tag"]
        ext = item["ext"]

        if mode == "base":
            # Exportar la capa cargada tal cual (sin logo)
            pass  # El paquete ya conserva los bytes de la capa original.
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
                from silkscreen_windows import clear_commands
                outline=self._find_outline_layer()
                from panel_model import geometry_bounds
                bounds=geometry_bounds(outline['layer'],outline=True) if outline else None
                clear_cmds = clear_commands(base_layer,clr,bounds,ch.get('window_shape','rectangle'))
                if clear_cmds is None:clear_cmds=base_layer.emit_drawables(extra_mm=clr, polarity="C", dcode_start=200)
                redraw_cmds = base_layer.emit_drawables(extra_mm=0.0, polarity="D", dcode_start=300)
                combined = cmds + clear_cmds + redraw_cmds
                base_layer.export_with_overlay(combined, out_path, position="after")
                results.append(f"• {Path(out_path).name}  (logo con ventanas para la base)")
            else:  # merge
                base_layer.export_with_overlay(cmds, out_path, position="after")
                results.append(f"• {Path(out_path).name}  (logo encima de base)")
        if not results:
            raise ValueError(f"Modo de exportación no reconocido: {ch['mode']}")
        return results[0]

    def _preview_layer(self, item, mode, parent=None, clearance=None,window_shape='rectangle'):
        """Renderiza una preview de cómo quedará la capa (base + logo según modo)."""
        if not self._commit_conversion_editor():
            return
        import numpy as np
        from PIL import Image as PILImage, ImageDraw as PILDraw

        # Holgura: la pasada explícitamente, o la del campo, o 0.5 por defecto
        if clearance is not None:
            try:
                clearance_mm = float(str(clearance).replace(',','.'))
                if not math.isfinite(clearance_mm) or clearance_mm<0:raise ValueError()
            except (ValueError, TypeError):
                clearance_mm = 0.5
        else:
            clearance_mm = 0.5

        # Bounds de toda la placa
        outline=self._find_outline_layer()
        from panel_model import geometry_bounds
        b = geometry_bounds(outline['layer'],outline=True) if outline else self._get_all_bounds()
        gw = (b[2] - b[0]) or 1
        gh = (b[3] - b[1]) or 1
        PW = 700
        scale = PW / gw
        PH = int(gh * scale)
        clearance_px = max(1, int(round(clearance_mm * scale)))

        is_silk = ('SILK' in (item['tag']+' '+item['label']).upper()
                   or item['ext'].lower() in {'.gto', '.gbo'})
        # Serigrafía física blanca sobre placa negra; cobre conserva su paleta.
        background = (0, 0, 0) if is_silk else (40, 15, 20)
        canvas_img = PILImage.new("RGB", (PW, PH), background)
        draw = PILDraw.Draw(canvas_img)

        def to_px(xmm, ymm):
            px = (xmm - b[0]) * scale
            py = PH - (ymm - b[1]) * scale   # Y invertida
            return px, py

        base_entry = item["base_entry"]

        def draw_base(color, width=None, regions=True, traces=True, region_color=None):
            if base_entry is None:
                return
            rc = region_color if region_color is not None else color
            # Preserve Gerber order and actual aperture widths; region edges
            # are boundaries, not additional thick pen strokes.
            for d in base_entry['layer'].drawables:
                if d.get('region_edge'):continue
                ink=bg if d.get('polarity')=='clear' else color
                if d['type']=='region' and regions:
                    pts=[to_px(px,py) for px,py in d['path']]
                    if len(pts)>=3:draw.polygon(pts,fill=bg if d.get('polarity')=='clear' else rc)
                elif d['type']=='line' and traces:
                    x1,y1=to_px(d['x1'],d['y1']);x2,y2=to_px(d['x2'],d['y2'])
                    pen=width if width is not None else max(1,round(d['width']*scale))
                    draw.line([x1,y1,x2,y2],fill=ink,width=pen)
                elif d['type']=='flash' and traces:
                    x,y=to_px(d['x'],d['y']);rx,ry=d['sx']*scale/2,d['sy']*scale/2
                    box=[x-rx,y-ry,x+rx,y+ry]
                    if d.get('shape')=='R':draw.rectangle(box,fill=ink)
                    elif d.get('shape')=='O':draw.rounded_rectangle(box,radius=min(rx,ry),fill=ink)
                    else:draw.ellipse(box,fill=ink)

        # Imagen del logo binarizada y posicionada
        def logo_mask():
            if self.overlay_image is None:return PILImage.new('L',(1,1),0),0,0
            raster = self._logo_raster()
            width = max(1, round(raster['width_mm']*scale))
            height = max(1, round(raster['height_mm']*scale))
            mask = ink_preview(raster['mask'], (width, height))
            mask = self._clip_logo_mask(mask, raster['width_mm'], raster['height_mm'])
            cx = self.overlay_x_mm+self.overlay_w_mm/2
            cy = self.overlay_y_mm+self.overlay_h_mm/2
            return mask, *to_px(cx, cy)

        mimg, mcx, mcy = logo_mask()
        mw, mh = mimg.size
        lx = int(mcx - mw/2); ly = int(mcy - mh/2)

        # Colores tipo cobre/placa (parecidos al visor de JLCPCB)
        logo_color = (255, 200, 40)   # logo en cobre (dorado brillante)
        base_color = (210, 130, 40)   # trazas en cobre
        pour_color = (150, 80, 30)    # plano de cobre (pour), tono cobre apagado
        bg = background
        if is_silk:
            logo_color = (255, 255, 255)
            base_color = (220, 220, 220)
            pour_color = (160, 160, 160)

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
            from silkscreen_windows import window_rectangles
            boxes=window_rectangles(base_entry['layer'],clearance_mm,b,window_shape) if base_entry else None
            if boxes is not None:
                for x0,y0,x1,y1 in boxes:
                    corner_a,corner_b=to_px(x0,y1),to_px(x1,y0)
                    draw.rectangle((*corner_a,*corner_b),fill=bg)
                draw_base(base_color,region_color=base_color)
            else:
                draw_base(bg, width=2 + clearance_px * 2, regions=False)
                draw_base(base_color, width=2, regions=False)
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
        tkimg = PILImageTk.PhotoImage(canvas_img,master=win)
        lbl = tk.Label(win, image=tkimg, bg="#1e1e2e")
        lbl.image = tkimg
        lbl.pack(padx=8, pady=4)
        legend = ("Blanco = tinta de serigrafía · Negro = PCB sin tinta" if is_silk else
                  "Dorado = logo en cobre · Cobre = plano/trazas · Oscuro = sin cobre (gap)")
        tk.Label(win, text=legend,
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
                if self._tag_matches_name(t["tag"], entry["name"], entry['layer']):
                    logo_here = t
                    matched_tags.add(t["tag"])
                    break
            tag = Path(entry["name"]).stem
            ext = Path(entry["name"]).suffix or ".gbr"
            items.append({
                "tag": tag, "ext": ext, "label": display_name(entry['name'],entry['layer']),
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

    def _tag_matches_name(self, tag, name, layer=None):
        return self._layer_name_matches_tag(name, tag, layer)

    def _layer_name_matches_tag(self, name, tag, layer=None):
        """
        ¿El archivo 'name' corresponde al tipo de capa 'tag'?
        Reconoce nombres tipo TOP_SILK, TOP.art (cobre), .gtl, ETCH/BOTTOM, etc.
        """
        role=layer_role(name,layer)
        if role is not None and tag in self.LAYER_KEYWORDS:return tag==role
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
        dlg.transient(self); dlg.grab_set(); dlg.geometry("1050x680")
        dlg.minsize(800,460)

        tk.Label(dlg, text="Selecciona qué capas exportar y cómo tratar el logo:",
                 bg="#252535", fg="#ccccdd", font=("Segoe UI", 10, "bold")
                 ).pack(pady=(14, 6), padx=14, anchor="w")

        tk.Label(dlg, text="Cada capa trae su receta por defecto (modo y holgura). "
                           "Puedes cambiarlas por capa.",
                 bg="#252535", fg="#8888aa", font=("Segoe UI", 8)).pack(padx=14, anchor="w")

        tk.Label(dlg, text="Se crea un ZIP nuevo. Sin marcar: se conserva la capa original.",
                 bg="#252535", fg="#88aacc", font=("Segoe UI", 8)).pack(padx=14, anchor="w")

        host=tk.Frame(dlg,bg='#252535');host.pack(fill='both',expand=True,padx=14,pady=6)
        scroll=tk.Scrollbar(host,orient='vertical');scroll.pack(side='right',fill='y')
        viewport=tk.Canvas(host,bg='#252535',highlightthickness=0,yscrollcommand=scroll.set)
        viewport.pack(side='left',fill='both',expand=True);scroll.config(command=viewport.yview)
        canvas_box = tk.Frame(viewport, bg="#252535")
        window_id=viewport.create_window(0,0,anchor='nw',window=canvas_box)
        canvas_box.bind('<Configure>',lambda e:viewport.configure(scrollregion=viewport.bbox('all')))
        viewport.bind('<Configure>',lambda e:viewport.itemconfigure(window_id,width=e.width))

        def recipe_for_item(item):
            return self._default_export_recipe(item)

        rows = []
        preferences = getattr(self, '_export_preferences', {})
        def preference_key(item):
            return self._export_preference_key(item)
        for item in items:
            row = tk.Frame(canvas_box, bg="#1e1e2e", pady=4)
            row.pack(fill="x", pady=2)

            saved = preferences.get(preference_key(item),preferences.get((item['label'],item['tag'],item['ext'],item['is_new']),{}))
            exp_var = tk.BooleanVar(master=dlg, value=saved.get('selected', item["has_logo"] or not item["is_new"]))
            tk.Checkbutton(row, variable=exp_var, onvalue=True, offvalue=False,
                           bg="#1e1e2e", fg="#ffffff", selectcolor="#2244aa",
                           activeforeground="#ffffff", activebackground="#1e1e2e").pack(side="left")

            txt = item["label"]
            if item["is_new"]:
                txt += "  [NUEVA]"
            tk.Label(row, text=txt, bg="#1e1e2e", fg="#ddddee",
                     font=("Segoe UI", 9), width=24, anchor="w").pack(side="left")

            def_mode, def_clr = recipe_for_item(item)
            def_mode = saved.get('mode', def_mode)
            def_clr = saved.get('clearance', def_clr)
            shape_var=tk.StringVar(master=dlg,value=saved.get('window_shape','rectangle'))

            # Modo
            if item["base_entry"] is not None and item["has_logo"]:
                mode_var = tk.StringVar(value=def_mode)
                controls=tk.Frame(row,bg='#1e1e2e');controls.pack(side='left',fill='x',expand=True)
                opts = tk.Frame(controls, bg="#1e1e2e")
                opts.pack(anchor='w')
                for val, lbl in [("merge", "Logo encima"),
                                 ("under", "Base encima"),
                                 ("clearance", "Recortar base"),
                                 ("logo_windows", "Respetar textos"),
                                 ("base", "Solo base")]:
                    tk.Radiobutton(opts, text=lbl, variable=mode_var, value=val,
                                   bg="#1e1e2e", fg="#aaccdd", selectcolor="#0a0a1a",
                                   activebackground="#1e1e2e",
                                   font=("Segoe UI", 9)).pack(side="left")
                extra=tk.Frame(controls,bg='#1e1e2e');extra.pack(anchor='w',pady=(4,0))
                tk.Label(extra,text='Ventana al respetar textos:',bg='#1e1e2e',fg='#aaccdd').pack(side='left')
                for val,label in [('rectangle','Recuadro'),('contour','Contorno / erosión')]:
                    tk.Radiobutton(extra,text=label,variable=shape_var,value=val,bg='#1e1e2e',fg='white',
                        selectcolor='#0a0a1a',activebackground='#1e1e2e').pack(side='left')
                # Holgura por capa
                clr_var = tk.StringVar(value=f"{def_clr:.2f}")
                tk.Label(extra, text="Margen mm:", bg="#1e1e2e", fg="#88aacc",
                         font=("Segoe UI", 9)).pack(side="left", padx=(4, 0))
                tk.Entry(extra, textvariable=clr_var, bg="#1a1a2e", fg="white",
                         insertbackground="white", relief="flat",
                         font=("Segoe UI", 8), width=4).pack(side="left")
                tk.Button(row, text="Vista previa", font=("Segoe UI", 9),
                          bg="#3a3a5c", fg="white", relief="flat",
                          command=lambda it=item, mv=mode_var, cv=clr_var,sv=shape_var:
                              self._preview_layer(it, mv.get(), parent=dlg, clearance=cv.get(),window_shape=sv.get())
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

            rows.append((exp_var, mode_var, clr_var, item,shape_var))

        res = {"v": None}
        def ok():
            sel = []
            for ev, mv, cv, it,sv in rows:
                if not ev.get():
                    continue
                try:
                    clr = float(cv.get().replace(',', '.'))
                    if not math.isfinite(clr) or clr < 0: raise ValueError()
                except ValueError:
                    messagebox.showwarning("Holgura", "Introduce una holgura válida, mayor o igual a cero.", parent=dlg)
                    return
                sel.append({"item": it, "mode": mv.get(), "clearance": clr,'window_shape':sv.get()})
            if not sel:
                messagebox.showwarning("Aviso", "Marca al menos una capa.", parent=dlg)
                return
            res["v"] = sel
            self._export_preferences = {
                preference_key(it): {'selected': ev.get(), 'mode': mv.get(),
                                     'window_shape':sv.get(),
                                     'clearance': float(cv.get().replace(',', '.')) if ev.get() else preferences.get(preference_key(it), {}).get('clearance', 0.5)}
                for ev, mv, cv, it,sv in rows}
            dlg.destroy()

        btns = tk.Frame(dlg, bg="#252535"); btns.pack(side="bottom", fill="x", pady=12, padx=14)
        tk.Button(btns, text="Exportar seleccionadas", command=ok, bg="#2244aa", fg="white",
                  relief="flat", font=("Segoe UI", 9, "bold"), pady=6, padx=14).pack(side="right", padx=4)
        tk.Button(btns, text="Cancelar", command=dlg.destroy, bg="#3a3a5c", fg="white",
                  relief="flat", font=("Segoe UI", 9), pady=6, padx=14).pack(side="right", padx=4)
        self.wait_window(dlg)
        return res["v"]

    def _export_preference_key(self,item):
        return json.dumps([item['tag'],item['ext'].lower(),bool(item['is_new'])],ensure_ascii=False)

    def _default_export_recipe(self,item):
        entry=item.get('base_entry')
        role=layer_role(entry['name'],entry['layer']) if entry else None
        for target in self.logo_targets:
            if target['tag'] in (item['tag'],role):
                return target.get('def_mode','merge'),target.get('def_clearance',.5)
        role=role or layer_role(item['tag']+item['ext'])
        if role in ('TOP_SILK','BOTTOM_SILK'):return 'logo_windows',1.
        if role in ('TOP_MASK','BOTTOM_MASK'):return 'merge',0.
        if role in ('TOP_COPPER','BOTTOM_COPPER'):return 'clearance',.5
        return 'merge',.5

    def _build_logo_cmds(self, converter, thresh, clearance_mm=0.0):
        """Genera los comandos Gerber del logo (SVG o raster)."""
        ext = Path(self.overlay_image_path).suffix.lower() if hasattr(self, 'overlay_image_path') else ""
        if (ext == ".svg" and SVG_AVAILABLE and getattr(self, 'overlay_svg_path', None)
                and self.overlay_angle_deg % 360 == 0):
            try:
                commands = converter.convert_svg_paths(
                    self.overlay_svg_path,
                    self.overlay_x_mm, self.overlay_y_mm,
                    self.overlay_w_mm, self.overlay_h_mm
                )
            except Exception:
                return self._export_raster(converter, thresh, clearance_mm)
            return self._clip_logo_commands(commands, converter.layer)
        return self._export_raster(converter, thresh, clearance_mm)

    def _board_clip_key(self):
        entry = self._find_outline_layer()
        return (entry['layer'], id(entry['layer'].drawables)) if entry else None

    def _board_clip_contours(self):
        entry = self._find_outline_layer()
        if entry is None:
            return None
        key = self._board_clip_key()
        if getattr(self, '_board_contours_key', None) != key:
            self._board_contours = outline_contours(entry['layer'])
            self._board_contours_key = key
        return self._board_contours

    def _clip_logo_mask(self, mask, width_mm, height_mm):
        try:
            contours = self._board_clip_contours()
        except ValueError:
            # Keep an incomplete outline editable. Export reports the error.
            return mask
        if contours is None:
            return mask
        cx = self.overlay_x_mm+self.overlay_w_mm/2
        cy = self.overlay_y_mm+self.overlay_h_mm/2
        return clip_mask(mask, contours, cx-width_mm/2, cy-height_mm/2, width_mm, height_mm)

    def _clip_logo_commands(self, commands, layer):
        contours = self._board_clip_contours()
        if contours is None or not commands:
            return commands
        # Include the complete stroke width and clearance, not only its centreline.
        probe = GerberLayer()
        probe.raw_lines = [f'%FSLAX{layer.format_x[0]}{layer.format_x[1]}Y{layer.format_y[0]}{layer.format_y[1]}*%',
                           '%MOIN*%' if layer.unit == 'IN' else '%MOMM*%', *commands]
        probe._parse()
        points = [p for path in contours for p in path]
        radius = 0.0
        for d in probe.drawables:
            if d['type'] == 'line':
                points.extend([(d['x1'], d['y1']), (d['x2'], d['y2'])])
                radius = max(radius, d['width']/2)
            elif d['type'] == 'flash':
                points.append((d['x'], d['y']))
                radius = max(radius, d['sx']/2, d['sy']/2)
            elif d['type'] == 'region':
                points.extend(d['path'])
        margin = radius+1.0
        bounds = (min(p[0] for p in points)-margin, min(p[1] for p in points)-margin,
                  max(p[0] for p in points)+margin, max(p[1] for p in points)+margin)
        return commands+clipping_commands(contours, bounds, layer)

    def _find_loaded_layer_for_tag(self, tag):
        """Busca una capa cargada cuyo nombre coincida con el tag (TOP_SILK, etc.)."""
        for entry in self.gerber_layers:
            if self._layer_name_matches_tag(entry["name"], tag, entry['layer']):
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
            return self._is_silkscreen(entry['name'],entry['layer'])

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
            tk.Radiobutton(row, text=f"{display_name(entry['name'],entry['layer'])}{tag}",
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
        if not self._commit_conversion_editor():
            return

        if not self._save_before_output():return

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
            initialdir=str(getattr(self,'fabrication_destination',None) or Path.cwd()),
            defaultextension=ext,
            filetypes=[("Gerber", "*.gbr *.gto *.gbo *.gts *.gbs *.gtl *.gbl *.art"), ("Todos", "*.*")],
            initialfile=f"{name_tag}{ext}"
        )
        if not output_path:
            return

        reserved=False;registered=False
        try:
            from module_project import reserve_output,find_root,record_output
            editing_project=getattr(self,'silk_project',None) or getattr(self,'panel_project',None)
            if editing_project:output_path,reserved=reserve_output(editing_project,output_path)
            converter = ImageToGerber(base_layer)
            thresh = self.overlay_threshold.get()

            existing=self._find_loaded_layer_for_tag(name_tag)
            from silkscreen_windows import text_boxes
            protected=existing is not None and bool(text_boxes(existing['layer']))
            if protected:
                item=dict(tag=name_tag,ext=ext,label=label,base_entry=existing,has_logo=True,is_new=False)
                _,margin=self._default_export_recipe(item)
                recipe=getattr(self,'_export_preferences',{}).get(self._export_preference_key(item),{})
                self._write_export_layer(dict(item=item,mode='logo_windows',clearance=recipe.get('clearance',margin),
                    window_shape=recipe.get('window_shape','rectangle')),output_path,thresh)
            else:
                cmds=self._build_logo_cmds(converter,thresh)
                base_layer.export_new_layer(cmds, output_path, layer_name=name_tag)

            lines = Path(output_path).read_text(encoding='utf-8').count('D01*')
            if reserved:
                record_output(editing_project,output_path,getattr(self,'fabrication_source',None),dict(type='single_layer',target=name_tag))
                registered=True
            from export_result import show_export_result
            show_export_result(self,'Capa generada',output_path,
                f"Capa '{label}' creada.\n" + ('Imagen y textos del frontal, con ventanas limpias.\n\n' if protected else 'Solo imagen, sin contenido de otras capas.\n\n') +
                f"Archivo: {Path(output_path).name}\n"
                f"Formato heredado de: {base['name']}\n"
                f"Unidades: {base_layer.unit}\n"
                f"Segmentos de línea: {lines}"
            )
        except Exception as e:
            if reserved and not registered:Path(output_path).unlink(missing_ok=True)
            messagebox.showerror("Error", str(e))

    def _find_outline_layer(self):
        """Busca una capa cargada que sea el outline (por nombre o cabecera)."""
        for entry in self.gerber_layers:
            if layer_role(entry['name'],entry['layer'])=='OUTLINE':
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
        try: dot_size = max(.15, float(self.entry_dot.get()))
        except ValueError: dot_size = .15
        _, gray, width, height = _prepare_logo_image(
            self.overlay_image, self.overlay_w_mm, self.overlay_h_mm,
            self.overlay_angle_deg, getattr(self, '_conv_contrast', 1.0),
            getattr(self, '_conv_invert', False),getattr(self,'_conv_tuning',None))
        cx = self.overlay_x_mm + self.overlay_w_mm/2
        cy = self.overlay_y_mm + self.overlay_h_mm/2
        commands = converter.convert(gray, cx-width/2, cy-height/2, width, height,
            threshold=thresh, dot_size_mm=dot_size, clearance_mm=clearance_mm,
            dither_algo=getattr(self, '_conv_algo', 'threshold'),
            dither_px_mm=getattr(self, '_conv_pxsize', dot_size))
        return self._clip_logo_commands(commands, converter.layer)


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if not PIL_AVAILABLE:
        print("ERROR: Pillow no está instalado. Ejecuta: pip install pillow")
        exit(1)

    if Path(__file__).with_name('design_app.py').exists():
        from design_app import DesignToolsApp
        app = DesignToolsApp()
    else:
        app = GerberEditor()
    app.geometry("1200x750")
    app.mainloop()
