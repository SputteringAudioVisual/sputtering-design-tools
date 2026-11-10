"""Responsive, reproducible bitmap tuning and reversible automatic suggestions."""
from pathlib import Path
import sys
import threading
import hashlib
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from image_tuning import DEFAULTS,PreparedCache,PreviewCancelled,auto_settings,validate_tuning,ink_preview
from gerber_silkscreen_editor import (GerberLayer,ImageToGerber,_prepare_logo_image,
    _compute_logo_raster,_image_ink_mask,_raster_ink_mask)
from design_app import DesignToolsApp
from panel_model import Reference
from test_panel import BOARD


class TuningTests(unittest.TestCase):
    def test_atkinson_keeps_legacy_points_instead_of_changing_export_for_screen_artifacts(self):
        # Golden mask from cef92a5, before the performance/Auto changes.
        source=np.full((192,224),128,dtype='float32')
        before=source.copy()
        mask=_raster_ink_mask(source,'atkinson',128)
        np.testing.assert_array_equal(mask,_raster_ink_mask(source,'atkinson',128))
        np.testing.assert_array_equal(source,before)
        self.assertEqual(hashlib.sha256(mask.tobytes()).hexdigest(),'4bedb1f727d630df4281e78c2bfdfbe5c4a5663c761bb512f780aae943c7822c')

    def test_fractional_screen_scaling_does_not_alias_fine_ink_into_large_checks(self):
        mask=Image.fromarray((np.indices((814,1085)).sum(axis=0)%2*255).astype('uint8'))
        before=mask.tobytes()
        # Fine alternating dots at screen reductions near the reported dimensions.
        for size in ((880,660),(543,407),(1100,825)):
            smooth=np.asarray(ink_preview(mask,size),dtype=float)[8:-8,8:-8]
            old=np.asarray(mask.resize(size,Image.Resampling.NEAREST),dtype=float)[8:-8,8:-8]
            self.assertAlmostEqual(smooth.mean(),127.5,delta=1)
            self.assertLess(smooth.std(),max(1.,old.std()*.6))
        self.assertEqual(mask.tobytes(),before)
        native_overview=np.asarray(ink_preview(mask,mask.size))[8:-8,8:-8]
        self.assertAlmostEqual(float(native_overview.mean()),127.5,delta=1)
        self.assertLess(float(native_overview.std()),2)
        np.testing.assert_array_equal(ink_preview(mask,(2170,1628)),mask.resize((2170,1628),Image.Resampling.NEAREST))
        edge=Image.new('L',(40,20),0);edge.paste(255,(20,0,40,20))
        small=ink_preview(edge,(4,2))
        np.testing.assert_array_equal(small,np.tile([0,0,255,255],(2,1)))

    def test_overview_near_native_size_removes_periodic_density_beats_for_all_dithers(self):
        source=np.full((192,224),128,dtype='float32')
        for algorithm in ('floyd','floyd_fast','atkinson','bayer2','bayer4','bayer8','clustered4','stucki','jarvis'):
            mask=Image.fromarray((_raster_ink_mask(source,algorithm,128)*255).astype('uint8'))
            original=mask.tobytes()
            for size in ((224,192),(227,195),(217,186)):
                with self.subTest(algorithm=algorithm,size=size):
                    overview=np.asarray(ink_preview(mask,size),dtype=float)[12:-12,12:-12]
                    self.assertAlmostEqual(overview.mean()/255,np.asarray(mask).mean()/255,delta=.02)
                    if algorithm!='clustered4':self.assertLess(overview.std(),8.)
                    # Clustered screening intentionally has larger dots. Check
                    # the low-frequency density envelope, not its dot shape.
                    h,w=overview.shape
                    blocks=overview[:h//16*16,:w//16*16].reshape(h//16,16,w//16,16).mean(axis=(1,3))
                    self.assertLess(blocks.std(),2.)
            self.assertEqual(mask.tobytes(),original)

    def test_auto_is_deterministic_distinguishes_logo_and_photo_without_mutating_source(self):
        photo=Image.linear_gradient('L').resize((80,60)).convert('RGB')
        logo=Image.new('RGBA',(80,60),'white');logo.paste('black',(0,0,40,60))
        original=photo.tobytes()
        self.assertEqual(auto_settings(photo),auto_settings(photo))
        self.assertEqual(auto_settings(photo)['algorithm'],'floyd_fast')
        self.assertEqual(auto_settings(logo)['algorithm'],'threshold')
        self.assertTrue(1<=auto_settings(logo)['threshold']<=254)
        self.assertEqual(photo.tobytes(),original)
        with self.assertRaises(ValueError):auto_settings(Image.new('RGBA',(10,10),(0,0,0,0)))
        self.assertEqual(auto_settings(Image.new('L',(10,10),128))['kind'],'imagen uniforme')

    def test_auto_expands_low_contrast_and_measures_threshold_after_adjustment(self):
        photo=Image.fromarray(np.tile(np.arange(80,171,dtype='uint8'),(60,1)))
        settings=auto_settings(photo)
        self.assertGreater(settings['contrast'],2.)
        self.assertLessEqual(settings['contrast'],3.)
        _,gray,_,_=_prepare_logo_image(photo,12,9,0,settings['contrast'],False)
        low,high=np.percentile(np.asarray(gray),(5,95))
        self.assertGreater(high-low,200)
        self.assertTrue(low<settings['threshold']<high)
        self.assertEqual(settings['contrast'],auto_settings(photo,True)['contrast'])
        self.assertEqual(auto_settings(Image.linear_gradient('L'))['contrast'],1.)
        self.assertEqual(auto_settings(Image.new('L',(10,10),128))['contrast'],1.)
        # Hidden RGB values must not affect automatic contrast.
        a=photo.convert('RGBA');a.putalpha(Image.fromarray(np.tile(np.r_[np.zeros(10),np.full(81,255)].astype('uint8'),(60,1))))
        b=a.copy();b.paste((255,255,255,0),(0,0,10,60))
        self.assertEqual(auto_settings(a),auto_settings(b))

    def test_neutral_tuning_preserves_existing_results_and_transparency_never_gets_ink(self):
        image=Image.linear_gradient('L').resize((80,60)).convert('RGB')
        a=_prepare_logo_image(image,12,9,35,1.3,True)
        b=_prepare_logo_image(image,12,9,35,1.3,True,dict(DEFAULTS))
        self.assertEqual(a[1].tobytes(),b[1].tobytes())
        clear=Image.new('RGBA',(30,20),(0,0,0,0))
        for invert in (False,True):
            result=_compute_logo_raster(clear,6,4,45,1.2,invert,.15,'floyd_fast',173,
                dict(brightness=.6,gamma=1.8,sharpness=2.,smoothing=1.))
            self.assertFalse(np.asarray(result['mask']).any())
        for bad in ({'gamma':0},{'brightness':float('nan')},{'unknown':1}):
            with self.assertRaises(ValueError):validate_tuning(bad)

    def test_threshold_and_algorithm_changes_reuse_prepared_pixels(self):
        image=Image.linear_gradient('L').resize((80,60)).convert('RGB');cache=PreparedCache()
        with patch('gerber_silkscreen_editor._prepare_logo_image',wraps=_prepare_logo_image) as prepare:
            _compute_logo_raster(image,12,9,0,1.,False,.15,'floyd_fast',128,prepared_cache=cache)
            _compute_logo_raster(image,12,9,0,1.,False,.15,'atkinson',190,prepared_cache=cache)
            self.assertEqual(prepare.call_count,1)
            _compute_logo_raster(image,12,9,0,1.,False,.15,'floyd_fast',190,{'gamma':1.4},prepared_cache=cache)
            self.assertEqual(prepare.call_count,2)

    def test_all_legacy_diffusions_cooperatively_cancel_and_new_modes_keep_endpoints(self):
        class Stop:
            def __init__(self):self.rows=0
            def is_set(self):self.rows+=1;return self.rows>=6
        for algorithm in ('floyd','atkinson','stucki','jarvis'):
            stop=Stop()
            with self.assertRaises(PreviewCancelled):_raster_ink_mask(np.full((200,200),128),algorithm,128,stop)
            self.assertEqual(stop.rows,6)
        for algorithm in ('floyd_fast','bayer2','clustered4'):
            self.assertTrue(_raster_ink_mask(np.zeros((32,32)),algorithm,128).all())
            self.assertFalse(_raster_ink_mask(np.full((32,32),255),algorithm,128).any())
        ramp=np.tile(np.arange(256),(32,1))
        self.assertLess(_raster_ink_mask(ramp,'floyd_fast',80).mean(),_raster_ink_mask(ramp,'floyd_fast',190).mean())


class ResponsiveUiTests(unittest.TestCase):
    def setUp(self):
        self.app=DesignToolsApp();self.app.withdraw()
        self.app.add_references([Reference('outline.gko',BOARD),Reference('silk.gto',BOARD)])
        self.app.overlay_image=Image.linear_gradient('L').resize((80,60)).convert('RGB')
        self.app.overlay_x_mm,self.app.overlay_y_mm=2,3
        self.app.overlay_w_mm,self.app.overlay_h_mm=12,9
        self.app.overlay_angle_deg=25
        self.app._conv_algo='atkinson';self.app._conv_contrast=1.4;self.app.overlay_threshold.set(177)
        self.app._conv_tuning=validate_tuning({'gamma':1.2})

    def tearDown(self):
        self.app.destroy()

    def walk(self,widget):
        for child in widget.winfo_children():yield child;yield from self.walk(child)

    def pump(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:self.app.update();time.sleep(.005)

    def button(self,name):
        return next(w for w in self.walk(self.app._conv_editor) if isinstance(w,tk.Button) and w.cget('text')==name)

    def field(self,name):
        row=next(w for w in self.walk(self.app._conv_editor) if w.winfo_name()==name+'_control')
        return row.nametowidget('value')

    def test_auto_is_reversible_and_conserves_physical_placement_and_polarity(self):
        a=self.app;pose=(a.overlay_x_mm,a.overlay_y_mm,a.overlay_w_mm,a.overlay_h_mm,a.overlay_angle_deg)
        a.overlay_image=Image.fromarray(np.tile(np.arange(80,171,dtype='uint8'),(60,1))).convert('RGB')
        a._conv_invert=True;a._open_conversion_editor();self.pump(.2)
        self.button('Auto · ajustar imagen').invoke();self.pump(.2)
        self.assertGreater(float(self.field('contrast').get().replace(',','.')),2.)
        self.assertEqual((a.overlay_x_mm,a.overlay_y_mm,a.overlay_w_mm,a.overlay_h_mm,a.overlay_angle_deg),pose)
        self.assertEqual(a.getvar(next(w for w in self.walk(a._conv_editor) if isinstance(w,tk.Radiobutton) and w.cget('value')=='floyd_fast').cget('variable')),'floyd_fast')
        self.button('Revertir Auto').invoke();self.pump(.2)
        self.assertEqual(a.overlay_threshold.get(),177)
        self.assertEqual(self.field('contrast').get(),'1,40')
        self.assertEqual(self.field('gamma').get(),'1,20')
        self.assertTrue(a._conv_invert)

    def test_pixel_detail_shows_the_binary_mask_at_native_size_without_changing_export(self):
        from PIL import ImageTk
        a=self.app;a._open_conversion_editor();self.pump(.3)
        a._conv_commit();self.pump(.3)
        before=a._logo_raster()['mask'].copy()
        self.button('Ver puntos 1:1…').invoke();self.pump(.1)
        detail=next(w for w in self.walk(a._conv_editor) if isinstance(w,tk.Toplevel))
        canvas=next(w for w in self.walk(detail) if isinstance(w,tk.Canvas))
        actual=ImageTk.getimage(canvas.image).convert('L')
        self.assertEqual(actual.size,before.size)
        np.testing.assert_array_equal(actual,before)
        self.assertEqual(a._logo_raster()['mask'].tobytes(),before.tobytes())
        detail.destroy()

    def test_advanced_tuning_reaches_exact_preview_and_export_without_changing_original(self):
        a=self.app;a._open_conversion_editor();self.pump(.15)
        for name,value in [('brightness','0,85'),('gamma','1,60'),('sharpness','1,4'),('smoothing','0,2')]:
            field=self.field(name);field.delete(0,'end');field.insert(0,value)
        self.button('Auto · ajustar imagen').invoke()
        # Auto is only a suggestion; manual fine controls remain available.
        for name,value in [('brightness','0,85'),('gamma','1,60'),('sharpness','1,4'),('smoothing','0,2')]:
            field=self.field(name);field.delete(0,'end');field.insert(0,value)
        before=a.overlay_image.tobytes()
        with patch('gerber_silkscreen_editor.messagebox.showinfo'):self.button('✅ Aplicar a PCB y exportación').invoke()
        self.pump(.3)
        self.assertEqual(a._conv_tuning,dict(brightness=.85,gamma=1.6,sharpness=1.4,smoothing=.2))
        raster=a._logo_raster();converter=ImageToGerber(GerberLayer())
        def capture(gray,x,y,width,height,**settings):
            return _image_ink_mask(gray,width,height,settings['dither_px_mm'],settings['dither_algo'],settings['threshold'])
        with patch.object(converter,'convert',side_effect=capture),patch.object(a,'_clip_logo_commands',side_effect=lambda commands,layer:commands):
            exported=a._export_raster(converter,a.overlay_threshold.get())
        np.testing.assert_array_equal(exported,np.asarray(raster['mask'])>0)
        self.assertEqual(a.overlay_image.tobytes(),before)

    def test_main_slider_drops_obsolete_work_and_updates_only_overlay(self):
        a=self.app;a._conv_algo='floyd_fast';a.overlay_w_mm,a.overlay_h_mm=90,70
        started=threading.Event();seen=[]
        def compute(*args,**kwargs):
            threshold=args[8];seen.append(threshold)
            if threshold==120:
                started.set()
                while not kwargs['cancel'].is_set():time.sleep(.001)
                raise PreviewCancelled()
            return _compute_logo_raster(*args,**kwargs)
        with patch('gerber_silkscreen_editor._compute_logo_raster',side_effect=compute),patch.object(a,'_redraw',side_effect=AssertionError('Full PCB repaint')):
            a.overlay_threshold.set(120);a._main_threshold_changed()
            self.assertTrue(started.wait(.5))
            a.overlay_threshold.set(205);a._main_threshold_changed()
            self.pump(.6)
            self.assertIn(205,seen)
            self.assertIsNone(a._main_preview_poll)
            key,_=a._logo_raster_request()
            self.assertIn(key,a._logo_raster_cache)

    def test_auto_controls_remain_visible_in_small_window_and_preview_stays_idle(self):
        a=self.app;a._open_conversion_editor();a._conv_editor.geometry('900x600');self.pump(.5)
        for name in ('Auto · ajustar imagen','Revertir Auto','✅ Aplicar a PCB y exportación','Cerrar y aplicar'):
            b=self.button(name)
            self.assertTrue(b.winfo_ismapped())
            self.assertLessEqual(b.winfo_rooty()+b.winfo_height(),a._conv_editor.winfo_rooty()+a._conv_editor.winfo_height())
        labels=[w for w in self.walk(a._conv_editor) if isinstance(w,tk.Label) and w.cget('image')]
        images=[w.cget('image') for w in labels]
        self.pump(.4)
        self.assertEqual([w.cget('image') for w in labels],images)


if __name__=='__main__':unittest.main()
