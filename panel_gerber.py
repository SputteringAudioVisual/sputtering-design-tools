"""Standalone FR4 front-panel fabrication package; PCB references are excluded."""
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
import zipfile
from panel_fonts import ink_runs, font_path, PIXEL_MM, element_mask,text_mask

HEIGHT=128.5


def header(function):
    return f'G04 Sputtering front panel; millimetres; viewed from front*\n%FSLAX36Y36*%\n%MOMM*%\n%TF.FileFunction,{function}*%\n%LPD*%\n%ADD10C,0.05*%\nD10*\nG01*\n'


def coord(x,y):return f'X{round(x*1e6)}Y{round(y*1e6)}'


def rectangle(box):
    a,b,c,d=box
    return ('G36*\n'+coord(a,b)+'D02*\n'+coord(c,b)+'D01*\n'+coord(c,d)+'D01*\n'+
            coord(a,d)+'D01*\n'+coord(a,b)+'D01*\nG37*\n')


def package_files(document, copper=True):
    holes=[e for e in document.elements if e.kind=='hole']
    for i,h in enumerate(holes):
        r=h.size/2
        if h.size<.5 or not(r+.2<=h.x<=document.width-r-.2 and r+.2<=h.y<=HEIGHT-r-.2):
            raise ValueError(f'Agujero {i+1}: diámetro menor de 0,5 mm o demasiado cerca del borde.')
        if any(math.hypot(h.x-o.x,h.y-o.y)<(h.size+o.size)/2+.2 for o in holes[:i]):
            raise ValueError(f'Agujero {i+1}: se solapa o deja menos de 0,2 mm de material.')
    rects=[];fonts={};text_styles=[]
    for e in document.elements:
        if e.kind!='text':continue
        mask=element_mask(e)
        if any(text_mask(line,e.size,e.font,0,e.width_scale,e.tracking,e.line_spacing,e.align,e.ink_gain).height*PIXEL_MM<1
               for line in e.text.split('\n') if line.strip()):
            raise ValueError(f'{e.text}: la altura de los caracteres es menor de 1 mm. Aumenta el tamaño.')
        text_styles.append(dict(font=e.font,angle=e.angle,width_scale=e.width_scale,tracking=e.tracking,
                                line_spacing=e.line_spacing,align=e.align,ink_gain=e.ink_gain))
        fonts[e.font]=hashlib.sha256(font_path(e.font).read_bytes()).hexdigest()
        for box in ink_runs(e):
            x0,y0,x1,y1=box
            if x0<.2 or y0<.2 or x1>document.width-.2 or y1>HEIGHT-.2:
                raise ValueError(f'{e.text}: la tinta sale del panel o queda a menos de 0,2 mm del borde.')
            for h in holes:
                nx,ny=max(x0,min(h.x,x1)),max(y0,min(h.y,y1))
                if math.hypot(nx-h.x,ny-h.y)<h.size/2+.15:
                    raise ValueError(f'{e.text}: la tinta está sobre un agujero o a menos de 0,15 mm de su borde.')
            rects.append(box)
    outline=header('Profile,NP')+coord(0,0)+'D02*\n'
    outline+=''.join(coord(x,y)+'D01*\n' for x,y in [(document.width,0),(document.width,HEIGHT),(0,HEIGHT),(0,0)])+'M02*\n'
    silk=header('Legend,Top')+''.join(rectangle(r) for r in rects)+'M02*\n'
    copper_body=''
    if copper:
        copper_body=rectangle((.3,.3,document.width-.3,HEIGHT-.3))
        for n,h in enumerate(holes,11):copper_body+=f'%ADD{n}C,{h.size+.6:.6f}*%\n'
        copper_body+='%LPC*%\n'
        for n,h in enumerate(holes,11):copper_body+=f'D{n}*\n'+coord(h.x,h.y)+'D03*\n'
    tools={size:n for n,size in enumerate(sorted({h.size for h in holes}),1)}
    drill='M48\n;TYPE=NON_PLATED\n;FILE_FORMAT=3:6\nMETRIC,TZ\n'
    drill+=''.join(f'T{n:02}C{size:.6f}\n' for size,n in tools.items())+'G90\n%\n'
    for size,n in tools.items():
        drill+=f'T{n:02}\n'+''.join(f'X{h.x:.6f}Y{h.y:.6f}\n' for h in holes if h.size==size)
    drill+='M30\n'
    files={'panel.GKO':outline,'panel.GTO':silk,'panel.GBO':header('Legend,Bot')+'M02*\n',
           'panel.GTS':header('Soldermask,Top')+'M02*\n','panel.GBS':header('Soldermask,Bot')+'M02*\n',
           'panel.GTL':header('Copper,L1,Top')+copper_body+'M02*\n',
           'panel.GBL':header('Copper,L2,Bot')+copper_body+'M02*\n'}
    if holes:files['panel-NPTH.drl']=drill
    # The proof is fixed geometry: it needs no fonts and has the same ink as GTO.
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{document.width}mm" height="{HEIGHT}mm" viewBox="0 0 {document.width} {HEIGHT}">',
         f'<rect width="{document.width}" height="{HEIGHT}" fill="#141414"/>']
    svg += [f'<rect x="{a}" y="{HEIGHT-d}" width="{c-a}" height="{d-b}" fill="white"/>' for a,b,c,d in rects]
    svg += [f'<circle cx="{h.x}" cy="{HEIGHT-h.y}" r="{h.size/2}" fill="#777"/>' for h in holes]
    svg+=['</svg>']
    return {k:v.encode('ascii') for k,v in files.items()},'\n'.join(svg),dict(width_mm=document.width,height_mm=HEIGHT,
        hole_count=len(holes),holes=[dict(x=h.x,y=h.y,diameter=h.size,plated=False) for h in holes],
        fonts_sha256=fonts,text_count=len(text_styles),text_styles=text_styles,ink_pixel_mm=PIXEL_MM,
        ink_expansion_mm=next(iter({s['ink_gain'] for s in text_styles})) if len({s['ink_gain'] for s in text_styles})==1 else None,
        copper_fill=copper)


def export_panel(document, destination, name='panel', copper=True):
    files,proof,report=package_files(document,copper)
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    stem=re.sub(r'[^A-Za-z0-9_-]+','_',name).strip('_') or 'panel'
    for version in range(1,10000):
        target=destination/f'{stem}_gerbers_v{version:03}.zip'
        if not any(target.with_suffix(ext).exists() for ext in ('.zip','.svg','.json')):break
    else:raise ValueError('No hay número de exportación libre.')
    report['files']={k:dict(bytes=len(v),sha256=hashlib.sha256(v).hexdigest()) for k,v in files.items()}
    with tempfile.TemporaryDirectory(prefix='.panel-export-',dir=destination) as folder:
        staged=Path(folder)/target.name
        with zipfile.ZipFile(staged,'w',zipfile.ZIP_DEFLATED) as z:
            for k,v in files.items():z.writestr(k,v)
        with zipfile.ZipFile(staged) as z:
            if z.testzip() or any(z.read(k)!=v for k,v in files.items()):raise ValueError('El ZIP no supera la comprobación de integridad.')
        from panel_model import atomic_write
        atomic_write(target.with_suffix('.svg'),proof)
        atomic_write(target.with_suffix('.json'),json.dumps(report,indent=2))
        # Exclusive copy never overwrites a previous order package.
        with target.open('xb') as out:out.write(staged.read_bytes())
    return target
