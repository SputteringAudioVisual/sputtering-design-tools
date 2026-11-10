"""Physical image keepouts around labels, shared by preview and export."""
import math
import re
from panel_fonts import element_mask,PIXEL_MM

MARKER='SPUTTERING_TEXTBOX_MM'

def element_box(element):
    mask=element_mask(element)
    w,h=mask.width*PIXEL_MM,mask.height*PIXEL_MM
    return element.x-w/2,element.y-h/2,element.x+w/2,element.y+h/2

def box_comment(box):
    return 'G04 '+MARKER+' '+','.join(f'{v:.6f}' for v in box)+'*\n'

def text_boxes(layer,margin=0.,bounds=None):
    if not math.isfinite(margin) or margin<0:raise ValueError('Margen de texto inválido.')
    result=[]
    for match in re.finditer(MARKER+r'\s+([^*\r\n]+)', ''.join(layer.raw_lines)):
        values=[float(v) for v in match[1].split(',')]
        if len(values)!=4 or not all(math.isfinite(v) for v in values):raise ValueError('Recuadro de texto inválido.')
        x0,y0,x1,y1=values
        if x1<=x0 or y1<=y0:raise ValueError('Recuadro de texto sin superficie.')
        box=(x0-margin,y0-margin,x1+margin,y1+margin)
        if bounds:
            box=(max(box[0],bounds[0]),max(box[1],bounds[1]),min(box[2],bounds[2]),min(box[3],bounds[3]))
        if box[0]<box[2] and box[1]<box[3]:result.append(box)
    return result

def window_rectangles(layer,margin=0.,bounds=None,shape='rectangle'):
    if shape not in ('rectangle','contour'):raise ValueError('Forma de ventana desconocida.')
    boxes=text_boxes(layer,margin,bounds)
    if shape=='rectangle':return boxes or None
    # Rasterise the composed ink before dilation: clear regions and counters
    # must take effect before eroding the artwork. Original letters stay vector.
    import numpy as np
    from PIL import Image,ImageDraw
    from panel_model import geometry_bounds
    if not layer.drawables:return []
    x0,y0,x1,y1=geometry_bounds(layer)
    step=PIXEL_MM
    radius=math.ceil(margin/step)
    x0-=radius*step+step;y0-=radius*step+step
    cols=math.ceil((x1-x0)/step)+radius+2
    rows=math.ceil((y1-y0)/step)+radius+2
    if cols*rows>64_000_000:raise ValueError('La capa es demasiado grande para generar ventanas de contorno a 0,025 mm.')
    top=y0+rows*step
    image=Image.new('1',(cols,rows));draw=ImageDraw.Draw(image)
    def point(x,y):return ((x-x0)/step-.5,(top-y)/step-.5)
    for d in layer.drawables:
        if d.get('region_edge'):continue
        color=0 if d.get('polarity')=='clear' else 1
        if d['type']=='region':
            if len(d['path'])>=3:draw.polygon([point(x,y) for x,y in d['path']],fill=color)
        elif d['type']=='line':
            a,b=point(d['x1'],d['y1']),point(d['x2'],d['y2'])
            width=max(1,round(d['width']/step));r=width/2
            draw.line((a,b),fill=color,width=width)
            for x,y in (a,b):draw.ellipse((x-r,y-r,x+r,y+r),fill=color)
        elif d['type']=='flash':
            x,y=d['x'],d['y'];sx,sy=d['sx'],d['sy']
            box=(*point(x-sx/2,y+sy/2),*point(x+sx/2,y-sy/2))
            if d.get('shape')=='R':draw.rectangle(box,fill=color)
            elif d.get('shape')=='O':draw.rounded_rectangle(box,radius=min(sx,sy)/step/2,fill=color)
            else:draw.ellipse(box,fill=color)
    ink=np.asarray(image,dtype=bool)
    # Square structuring element, separable cumulative sums: bounded linear
    # work even with a wide margin, unlike a large Pillow rank filter.
    if radius:
        for axis in (1,0):
            pads=[(0,0),(0,0)];pads[axis]=(radius+1,radius)
            sums=np.cumsum(np.pad(ink,pads),axis=axis,dtype=np.int32)
            lo=[slice(None),slice(None)];hi=lo.copy()
            lo[axis]=slice(None,-2*radius-1);hi[axis]=slice(2*radius+1,None)
            ink=(sums[tuple(hi)]-sums[tuple(lo)])>0
    # Merge equal horizontal runs vertically, retaining holes and gaps.
    active={};result=[]
    for row in range(rows+1):
        if row<rows:
            changes=np.flatnonzero(np.diff(np.pad(ink[row],(1,1)).astype(np.int8)))
            runs=set(zip(changes[::2],changes[1::2]))
        else:runs=set()
        for run,start in list(active.items()):
            if run not in runs:
                box=(x0+run[0]*step,top-row*step,x0+run[1]*step,top-start*step)
                if bounds:box=(max(box[0],bounds[0]),max(box[1],bounds[1]),min(box[2],bounds[2]),min(box[3],bounds[3]))
                if box[0]<box[2] and box[1]<box[3]:result.append(box)
                del active[run]
        for run in runs:active.setdefault(run,row)
    return result


def clear_commands(layer,margin=0.,bounds=None,shape='rectangle'):
    boxes=window_rectangles(layer,margin,bounds,shape)
    if boxes is None:return None
    div=25.4 if layer.unit=='IN' else 1.
    def xy(x,y):return f'X{round(x/div*10**layer.format_x[1])}Y{round(y/div*10**layer.format_y[1])}'
    commands=['G01*','%LPC*%']
    for x0,y0,x1,y1 in boxes:
        commands+=['G36*',xy(x0,y0)+'D02*',xy(x1,y0)+'D01*',xy(x1,y1)+'D01*',xy(x0,y1)+'D01*',xy(x0,y0)+'D01*','G37*']
    return commands+['%LPD*%','G01*']
