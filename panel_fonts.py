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
def text_mask(text, size, style='sans', angle=0, width_scale=1, tracking=0,
              line_spacing=1.2, align='center', ink_gain=.075):
    if not text.strip() or len(text)>500 or len(text.splitlines())>8 or '\r' in text or '\t' in text:
        raise ValueError('Usa hasta 8 líneas y 500 caracteres, sin tabuladores.')
    if not math.isfinite(size) or not .1<=size<=200:raise ValueError('Tamaño de texto no válido.')
    font=ImageFont.truetype(str(font_path(style)),max(1,round(size/PIXEL_MM)))
    missing=bytes(font.getmask('\u0378'))
    if (not all(math.isfinite(v) for v in [angle,width_scale,tracking,line_spacing,ink_gain]) or
            not .25<=width_scale<=4 or not 0<=tracking<=3 or not .6<=line_spacing<=3 or
            not 0<=ink_gain<=.3 or align not in {'left','center','right'}):
        raise ValueError('Ajustes de texto no válidos.')
    for c in set(text):
        if not c.isspace() and bytes(font.getmask(c))==missing:
            raise ValueError(f'La fuente no incluye el carácter {c!r}.')
    lines=text.split('\n');track=tracking/PIXEL_MM
    widths=[font.getlength(line)+max(0,len(line)-1)*track for line in lines];max_width=max(widths)
    atoms=[]
    for row,(line,width) in enumerate(zip(lines,widths)):
        offset=0 if align=='left' else max_width-width if align=='right' else (max_width-width)/2
        y=row*max(1,round(size/PIXEL_MM))*line_spacing
        if tracking:
            atoms.extend((offset+font.getlength(line[:i])+i*track,y,c) for i,c in enumerate(line))
        else:atoms.append((offset,y,line))
    boxes=[(x+b[0],y+b[1],x+b[2],y+b[3]) for x,y,t in atoms if t for b in [font.getbbox(t)]]
    x0=min(b[0] for b in boxes);y0=min(b[1] for b in boxes)
    x1=max(b[2] for b in boxes);y1=max(b[3] for b in boxes)
    w,h=math.ceil(x1-x0),math.ceil(y1-y0)
    if max(w,h)>20000 or w*h*width_scale>12_000_000:raise ValueError('Texto demasiado grande para convertir.')
    mask=Image.new('L',(max(1,w)+8,max(1,h)+8));draw=ImageDraw.Draw(mask)
    for x,y,t in atoms:draw.text((x-x0+4,y-y0+4),t,font=font,fill=255)
    mask=mask.crop(mask.getbbox())
    mask=mask.resize((max(1,round(mask.width*width_scale)),mask.height),Image.Resampling.LANCZOS)
    gain=round(ink_gain/PIXEL_MM)
    padded=Image.new('L',(mask.width+2*gain,mask.height+2*gain));padded.paste(mask,(gain,gain));mask=padded
    mask=mask.point(lambda p:255 if p>=128 else 0)
    if gain:mask=mask.filter(ImageFilter.MaxFilter(2*gain+1))
    if angle%360:
        radians=math.radians(angle%360)
        w=abs(mask.width*math.cos(radians))+abs(mask.height*math.sin(radians))
        h=abs(mask.width*math.sin(radians))+abs(mask.height*math.cos(radians))
        if w*h>12_000_000:raise ValueError('Texto girado demasiado grande para convertir.')
        mask=mask.rotate(angle%360,resample=Image.Resampling.NEAREST,expand=True)
    bounds=mask.getbbox()
    if bounds is None:raise ValueError('El texto no produce tinta visible.')
    return mask.crop(bounds)


def element_mask(element):
    return text_mask(element.text,element.size,element.font,element.angle,element.width_scale,
                     element.tracking,element.line_spacing,element.align,element.ink_gain)


def ink_runs(element):
    mask=element_mask(element)
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
