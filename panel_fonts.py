"""Shared physical ink masks: screen, SVG proof and Gerber use the same pixels."""
from functools import lru_cache
import math
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

PIXEL_MM = .025
FONTS = {
    'sans': ('Clásica · Arial', 'Arial', 'arial.ttf'),
    'console': ('Consola · Consolas', 'Consolas', 'consolab.ttf'),
    'gothic': ('Gótica · Old English', 'Old English Text MT', 'OLDENGL.TTF'),
    'industrial': ('Industrial · Bahnschrift', 'Bahnschrift', 'bahnschrift.ttf'),
}


def font_path(style):
    if style not in FONTS:raise ValueError('Tipografía desconocida.')
    path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/FONTS[style][2]
    if not path.is_file():raise ValueError(f'No está instalada la fuente {FONTS[style][1]}. Elige otra; no se sustituye al exportar.')
    return path


@lru_cache(maxsize=128)
def text_mask(text, size, style='sans'):
    if not text.strip() or len(text)>500 or '\n' in text or '\r' in text:
        raise ValueError('Usa una línea de texto de hasta 500 caracteres.')
    if not math.isfinite(size) or not .1<=size<=200:raise ValueError('Tamaño de texto no válido.')
    font=ImageFont.truetype(str(font_path(style)),max(1,round(size/PIXEL_MM)))
    missing=bytes(font.getmask('\u0378'))
    for c in set(text):
        if not c.isspace() and bytes(font.getmask(c))==missing:
            raise ValueError(f'La fuente no incluye el carácter {c!r}.')
    box=font.getbbox(text);w,h=box[2]-box[0],box[3]-box[1]
    if w*h>12_000_000:raise ValueError('Texto demasiado grande para convertir.')
    mask=Image.new('L',(max(1,w)+8,max(1,h)+8))
    ImageDraw.Draw(mask).text((4-box[0],4-box[1]),text,font=font,fill=255)
    # A 0.075 mm expansion on each side protects thin decorative strokes.
    mask=mask.point(lambda p:255 if p>=128 else 0).filter(ImageFilter.MaxFilter(7))
    bounds=mask.getbbox()
    if bounds is None:raise ValueError('El texto no produce tinta visible.')
    return mask.crop(bounds)


def ink_runs(element):
    mask=text_mask(element.text,element.size,element.font)
    width,height=mask.size;pixels=mask.load();left=element.x-width*PIXEL_MM/2;top=element.y+height*PIXEL_MM/2
    # Merge equal runs vertically; holes in letters remain unprinted.
    active={}
    for row in range(height+1):
        runs=set();x=0
        while row<height and x<width:
            if not pixels[x,row]:x+=1;continue
            end=x+1
            while end<width and pixels[end,row]:end+=1
            runs.add((x,end));x=end
        for run,start in list(active.items()):
            if run not in runs:
                yield (left+run[0]*PIXEL_MM,top-row*PIXEL_MM,
                       left+run[1]*PIXEL_MM,top-start*PIXEL_MM)
                del active[run]
        for run in runs:active.setdefault(run,row)
