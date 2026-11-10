"""Layer roles for display; original filenames remain fabrication identifiers."""
from pathlib import Path
import re

EXTENSIONS={'.gto':'TOP_SILK','.gbo':'BOTTOM_SILK','.gts':'TOP_MASK','.gbs':'BOTTOM_MASK',
            '.gtl':'TOP_COPPER','.gbl':'BOTTOM_COPPER','.gko':'OUTLINE','.gm1':'OUTLINE'}
LABELS={'TOP_SILK':'Serigrafía superior','BOTTOM_SILK':'Serigrafía inferior',
        'TOP_MASK':'Máscara superior','BOTTOM_MASK':'Máscara inferior',
        'TOP_COPPER':'Cobre superior','BOTTOM_COPPER':'Cobre inferior',
        'OUTLINE':'Contorno','DRILL':'Taladros','NPTH':'Taladros sin metalizar','ROUTE':'Ranuras'}

def layer_role(name,layer=None):
    header=''.join(getattr(layer,'raw_lines',[])[:40]).upper()
    match=re.search(r'FILEFUNCTION,([^*%]+)',header)
    if match:
        function=match[1].split(',');kind=function[0]
        bottom=any(v in ('BOT','BOTTOM') for v in function)
        if kind=='PROFILE':return 'OUTLINE'
        if kind in ('LEGEND','SILKSCREEN'):return 'BOTTOM_SILK' if bottom else 'TOP_SILK'
        if kind=='SOLDERMASK':return 'BOTTOM_MASK' if bottom else 'TOP_MASK'
        if kind=='COPPER' and any(v in ('TOP','BOT','BOTTOM') for v in function):
            return 'BOTTOM_COPPER' if bottom else 'TOP_COPPER'
    if 'BOARD GEOMETRY' in header or 'OUTLINE' in header:return 'OUTLINE'
    suffix=Path(name).suffix.lower()
    if suffix in EXTENSIONS:return EXTENSIONS[suffix]
    if suffix=='.rou':return 'ROUTE'
    if suffix in ('.drl','.xln','.exc'):return 'NPTH' if 'NPTH' in name.upper() else 'DRILL'
    text=re.sub(r'[^A-Z0-9]','',Path(name).stem.upper())
    if any(v in text for v in ('OUTLINE','PROFILE','EDGECUTS','CONTORNO')):return 'OUTLINE'
    bottom='BOTTOM' in text or 'BOT' in text
    if 'SILK' in text or 'SERIGRAFIA' in text:return 'BOTTOM_SILK' if bottom else 'TOP_SILK'
    if 'MASK' in text:return 'BOTTOM_MASK' if bottom else 'TOP_MASK'
    if 'COPPER' in text or 'ETCH' in text:return 'BOTTOM_COPPER' if bottom else 'TOP_COPPER'
    return None

def layer_label(name,layer=None):
    return LABELS.get(layer_role(name,layer),'Capa Gerber')

def display_name(name,layer=None):
    return f'{layer_label(name,layer)} · {Path(name).name}'

def named_panel_files(files,stem):
    names={'.GKO':'contorno','.GTO':'serigrafia_superior','.GBO':'serigrafia_inferior',
           '.GTS':'mascara_superior','.GBS':'mascara_inferior','.GTL':'cobre_superior','.GBL':'cobre_inferior'}
    result={}
    for name,data in files.items():
        suffix=Path(name).suffix
        label=names[suffix]+suffix if suffix in names else 'taladros_NPTH.drl'
        result[f'{stem}_{label}']=data
    return result
