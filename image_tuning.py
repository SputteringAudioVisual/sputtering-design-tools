"""Image tuning, automatic starting points and cancellable preview work."""
from collections import OrderedDict
import math
import threading
from PIL import Image,ImageEnhance,ImageFilter,ImageOps
import numpy as np

DEFAULTS=dict(brightness=1.,gamma=1.,sharpness=1.,smoothing=0.)
RANGES=dict(brightness=(.3,2.),gamma=(.3,3.),sharpness=(0.,3.),smoothing=(0.,2.))


class PreviewCancelled(Exception):pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise PreviewCancelled()


def validate_tuning(values=None):
    result=dict(DEFAULTS)
    for name,value in (values or {}).items():
        if name not in result:raise ValueError('Ajuste de imagen desconocido: '+str(name))
        value=float(str(value).replace(',','.'))
        low,high=RANGES[name]
        if not math.isfinite(value) or not low<=value<=high:raise ValueError('Ajuste de imagen fuera de rango: '+name)
        result[name]=value
    return result


def tune_gray(gray,values=None):
    values=validate_tuning(values)
    if values['smoothing']:gray=gray.filter(ImageFilter.GaussianBlur(values['smoothing']))
    if values['sharpness']!=1:gray=ImageEnhance.Sharpness(gray).enhance(values['sharpness'])
    if values['brightness']!=1:gray=ImageEnhance.Brightness(gray).enhance(values['brightness'])
    if values['gamma']!=1:
        gamma=values['gamma'];gray=gray.point([round(255*(v/255)**(1/gamma)) for v in range(256)])
    return gray


def ink_preview(mask,size):
    """Resample finished ink for screen only; never rethreshold the averages."""
    size=tuple(max(1,int(v)) for v in size)
    gray=mask.convert('L')
    # At two or more screen pixels per dot, individual dots can be resolved.
    # An overview near one screen pixel per dot needs a density low-pass even
    # at 1:1: interpolation alone leaves the high-frequency dither visible as
    # waves/beats when the image is fitted or subsequently scaled by the screen.
    # The explicit 1:1 inspection window displays the untouched mask instead.
    scale=max(size[0]/gray.width,size[1]/gray.height)
    integer_zoom=(size[0]%gray.width==0 and size[1]%gray.height==0
                  and size[0]//gray.width==size[1]//gray.height)
    if integer_zoom and scale>=2:return gray.resize(size,Image.Resampling.NEAREST)
    if scale<=.5:return gray.resize(size,Image.Resampling.BOX)
    if scale<2:
        radius=1.25*min(1.,(2.-scale)/.5)
        gray=gray.filter(ImageFilter.GaussianBlur(radius))
    reduced=(min(size[0],gray.width),min(size[1],gray.height))
    if reduced!=gray.size:
        # Near native size use a low-pass filter, not sparse point sampling.
        # At strong reductions area averaging retains coverage and sharp edges.
        ratio=max(reduced[0]/gray.width,reduced[1]/gray.height)
        gray=gray.resize(reduced,Image.Resampling.BOX if ratio<=.5 else Image.Resampling.BILINEAR)
    return gray if gray.size==size else gray.resize(size,Image.Resampling.BILINEAR)


class PreparedCache:
    """Small cache: threshold changes reuse rotation/tones/resampling."""
    def __init__(self,limit=2):self.limit=limit;self.values=OrderedDict();self.lock=threading.Lock()
    def get_or_create(self,key,create):
        with self.lock:
            if key in self.values:
                self.values.move_to_end(key);return self.values[key]
        result=create()
        with self.lock:
            self.values[key]=result
            while len(self.values)>self.limit:self.values.popitem(last=False)
        return result


def auto_settings(image,invert=False):
    """Deterministic starting point, without altering placement or pixel size."""
    sample=image.copy();sample.thumbnail((320,320),Image.Resampling.LANCZOS)
    rgba=sample.convert('RGBA');alpha=np.asarray(rgba.getchannel('A'))
    background=(0,0,0,255) if invert else (255,255,255,255)
    gray=Image.alpha_composite(Image.new('RGBA',rgba.size,background),rgba).convert('L')
    values=np.asarray(gray)[alpha>0]
    if not values.size:raise ValueError('La imagen es totalmente transparente.')
    # Expand a compressed tonal range without letting isolated specks drive it.
    # Use the same contrast operation as preview/export, then measure threshold
    # again in that transformed image rather than reusing the original threshold.
    low,high=np.percentile(values,(5,95))
    contrast=round(float(np.clip(220/(high-low),1.,3.)),2) if high-low>1 else 1.
    if contrast!=1.:gray=ImageEnhance.Contrast(gray).enhance(contrast)
    adjusted=np.asarray(gray)[alpha>0]
    original_hist=np.bincount(values,minlength=256)
    extremes=(original_hist[:32].sum()+original_hist[224:].sum())/values.size
    hist=np.bincount(adjusted,minlength=256).astype(float)
    if invert:hist=hist[::-1]
    count=hist.sum();prob=hist/count
    weights=np.cumsum(prob);means=np.cumsum(prob*np.arange(256))
    denominator=weights*(1-weights)
    score=np.divide((means[-1]*weights-means)**2,denominator,out=np.zeros(256),where=denominator>1e-12)
    if score.max()<1e-8:
        return dict(algorithm='threshold',threshold=128,contrast=1.,tuning=dict(DEFAULTS),kind='imagen uniforme')
    plateau=np.flatnonzero(np.isclose(score,score.max(),rtol=1e-7,atol=1e-9))
    threshold=int(np.clip(round((int(plateau[0])+int(plateau[-1]))/2)+1,1,254))
    # Concentration near two tonal extremes distinguishes line art from photos.
    logo=extremes>=.8
    return dict(algorithm='threshold' if logo else 'floyd_fast',threshold=threshold,contrast=contrast,
                tuning=dict(DEFAULTS),kind='logo / dibujo' if logo else 'fotografía')


def native_floyd(arr,threshold):
    """Fast native diffusion, with a midpoint curve keeping black/white endpoints."""
    threshold=float(threshold)
    if threshold==128:tones=np.asarray(arr,dtype=np.uint8)
    else:
        x=np.asarray(arr,dtype=np.float32)
        tones=np.where(x<threshold,x*128/max(threshold,1),
                       128+(x-threshold)*127/max(255-threshold,1))
        tones=np.clip(tones,0,255).astype('uint8')
        tones[x<=0]=0;tones[x>=255]=255
    return ~np.asarray(Image.fromarray(tones).convert('1',dither=Image.Dither.FLOYDSTEINBERG),dtype=bool)
