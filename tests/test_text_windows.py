"""Keep complete labels readable over artwork, including standalone exports."""
import json
import math
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from design_app import DesignToolsApp
from panel_model import PanelDocument,Element,Reference
from panel_gerber import package_files
from panel_fonts import element_mask,PIXEL_MM
from silkscreen_windows import text_boxes,clear_commands,element_box,box_comment

def ink_at(layer,x,y):
    result=False
    for d in layer.drawables:
        if d.get('region_edge'):continue
        hit=False
        if d['type']=='region':
            points=d['path'];inside=False
            for a,b in zip(points,points[1:]+points[:1]):
                if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:inside=not inside
            hit=inside
        elif d['type']=='flash':hit=math.hypot(x-d['x'],y-d['y'])<=d['sx']/2
        elif d['type']=='line':
            dx,dy=d['x2']-d['x1'],d['y2']-d['y1'];length=dx*dx+dy*dy
            t=max(0,min(1,((x-d['x1'])*dx+(y-d['y1'])*dy)/length)) if length else 0
            hit=math.hypot(x-d['x1']-t*dx,y-d['y1']-t*dy)<=d['width']/2
        if hit:result=d.get('polarity','dark')!='clear'
    return result

class TextWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.document=PanelDocument(hp=10,elements=[Element('text',25,80,2.5,'GAIN',ink_gain=.05)])
        files,_,_=package_files(self.document)
        self.silk=Reference('panel.GTO',files['panel.GTO'].decode())
        self.outline=Reference('panel.GKO',files['panel.GKO'].decode())
        self.app=DesignToolsApp();self.app.withdraw()
        self.app.add_references([self.outline,self.silk])
        self.app.overlay_image=Image.new('RGB',(20,20),'black')
        self.app.overlay_w_mm,self.app.overlay_h_mm=self.document.width,128.5
        self.app.overlay_x_mm=self.app.overlay_y_mm=0
        self.app.logo_targets=[dict(tag='TOP_SILK',label='Serigrafía TOP',ext='.gto',def_mode='logo_windows',def_clearance=1.)]

    def tearDown(self):self.app.destroy();self.temp.cleanup()

    def item(self):return next(i for i in self.app._build_export_items() if i['ext'].lower()=='.gto')

    def assert_labels(self,path):
        layer=Reference(path.name,path.read_text()).layer
        x0,y0,x1,y1=text_boxes(self.silk.layer)[0]
        self.assertFalse(ink_at(layer,x0-.5,(y0+y1)/2),'Image must leave a rectangular margin, not only trace contours.')
        self.assertFalse(ink_at(layer,(x0+x1)/2,y1+.5))
        self.assertTrue(ink_at(layer,x0-2,(y0+y1)/2),'Image outside the margin must remain.')
        mask=element_mask(self.document.elements[0]);row=mask.height//2
        lit=next(x for x in range(mask.width) if mask.getpixel((x,row)))
        x=x0+(lit+.5)*PIXEL_MM;y=y1-(row+.5)*PIXEL_MM
        self.assertTrue(ink_at(layer,x,y),'Original letter ink must be redrawn after the cutout.')

    def test_box_matches_physical_glyph_bounds_and_margin(self):
        actual=text_boxes(self.silk.layer)[0];expected=element_box(self.document.elements[0])
        for a,b in zip(actual,expected):self.assertAlmostEqual(a,b,places=6)
        expanded=text_boxes(self.silk.layer,1.)[0]
        self.assertEqual(expanded,(actual[0]-1,actual[1]-1,actual[2]+1,actual[3]+1))
        self.assertEqual(clear_commands(self.silk.layer)[-2:],['%LPD*%','G01*'])

    def test_combined_export_contains_image_exact_letters_and_rectangular_clearance(self):
        path=self.root/'combined.gto'
        self.app._write_export_layer(dict(item=self.item(),mode='logo_windows',clearance=1.),str(path),128)
        self.assert_labels(path)
        # Region outlines must not become extra stroked shapes on re-emission.
        redraw=self.silk.layer.emit_drawables()
        self.assertFalse(any(command.startswith('%ADD') for command in redraw))
        self.assertEqual(redraw.count('G36*'),sum(d['type']=='region' for d in self.silk.layer.drawables))

    def test_generate_front_layer_keeps_text_instead_of_exporting_only_image(self):
        path=self.root/'standalone.gto'
        with patch.object(self.app,'_choose_new_layer_type',return_value=('Serigrafía TOP','TOP_SILK','.gto')),\
             patch('gerber_silkscreen_editor.filedialog.asksaveasfilename',return_value=str(path)),\
             patch('gerber_silkscreen_editor.messagebox.showinfo'),\
             patch('gerber_silkscreen_editor.messagebox.showerror',side_effect=AssertionError):
            self.app.generate_new_layer()
        self.assert_labels(path)

    def test_extension_recipe_and_dialog_preferences_survive_json(self):
        item=self.item()
        self.assertEqual(self.app._default_export_recipe(item),('logo_windows',1.))
        self.app.logo_targets=[]
        self.assertEqual(self.app._default_export_recipe(item),('logo_windows',1.))
        def accept(win):
            def walk(w):
                for c in w.winfo_children():yield c;yield from walk(c)
            next(w for w in walk(win) if isinstance(w,tk.Button) and w.cget('text')=='Exportar seleccionadas').invoke()
        with patch.object(self.app,'wait_window',side_effect=accept):choices=self.app._choose_export_dialog([item])
        self.assertEqual(choices[0]['mode'],'logo_windows')
        self.assertEqual(choices[0]['clearance'],1.)
        saved=json.loads(json.dumps(self.app._export_preferences))
        self.assertIn(self.app._export_preference_key(item),saved)

    def test_contour_erodes_image_around_ink_but_keeps_image_between_letters(self):
        from panel_gerber import header,rectangle
        source=header('Legend,Top')+box_comment((10,30,16.5,34))+rectangle((10,30,10.5,34))+rectangle((16,30,16.5,34))+'M02*\n'
        base=Reference('strokes.GTO',source)
        item=dict(self.item(),base_entry=dict(name=base.name,layer=base.layer))
        for shape in ('rectangle','contour'):
            with self.subTest(shape=shape):
                path=self.root/(shape+'.gto')
                self.app._write_export_layer(dict(item=item,mode='logo_windows',clearance=.2,window_shape=shape),str(path),128)
                layer=Reference(path.name,path.read_text()).layer
                self.assertTrue(ink_at(layer,10.25,32),'The original letter must remain.')
                self.assertFalse(ink_at(layer,9.9,32),'A margin must surround each letter.')
                self.assertTrue(ink_at(layer,9.6,32),'Image beyond the chosen margin must remain.')
                self.assertEqual(ink_at(layer,13,32),shape=='contour')
                # Preview consumes these same clear rectangles, no independent dilation.
                commands=clear_commands(base.layer,.2,(0,0,self.document.width,128.5),shape)
                self.assertTrue(commands)

    def test_contour_respects_clear_regions_before_dilating(self):
        from panel_gerber import header,rectangle
        source=header('Legend,Top')+rectangle((10,30,16,36))+'%LPC*%\n'+rectangle((11,31,15,35))+'M02*\n'
        base=Reference('counter.GTO',source)
        commands=clear_commands(base.layer,.2,None,'contour')
        path=self.root/'clear.gto'
        self.outline.layer.export_new_layer(commands,str(path))
        clear=Reference(path.name,path.read_text()).layer
        regions=[d for d in clear.drawables if d['type']=='region']
        self.assertTrue(regions)
        # All emitted regions clear image; the original large counter stays open.
        self.assertFalse(any(min(p[0] for p in d['path'])<13<max(p[0] for p in d['path']) and
                             min(p[1] for p in d['path'])<33<max(p[1] for p in d['path']) for d in regions))

    def test_recipe_preview_opens_both_shapes_and_accepts_decimal_comma(self):
        from PIL import ImageTk
        def walk(widget):
            for child in widget.winfo_children():yield child;yield from walk(child)
        for shape in ('rectangle','contour'):
            self.app._preview_layer(self.item(),'logo_windows',clearance='0,25',window_shape=shape)
            win=next(w for w in self.app.winfo_children() if isinstance(w,tk.Toplevel))
            labels=[w for w in walk(win) if isinstance(w,tk.Label)]
            self.assertTrue(any('0.25 mm' in w.cget('text') for w in labels))
            shown=ImageTk.getimage(next(w for w in labels if w.cget('image')).image)
            self.assertEqual(shown.size,(700,int(128.5*700/self.document.width)))
            next(w for w in walk(win) if isinstance(w,tk.Button) and w.cget('text')=='Cerrar preview').invoke()

    def test_base_preview_before_importing_an_image(self):
        self.app.overlay_image=None
        self.app._preview_layer(self.item(),'base')
        windows=[w for w in self.app.winfo_children() if isinstance(w,tk.Toplevel)]
        self.assertEqual(len(windows),1)
        windows[0].destroy()

if __name__=='__main__':unittest.main()
