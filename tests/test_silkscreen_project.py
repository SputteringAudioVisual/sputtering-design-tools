"""A front-panel ZIP stays a front panel and its artwork survives reopening."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from design_app import DesignToolsApp
from layer_identity import layer_role,layer_label
from panel_model import PanelDocument,Reference,geometry_bounds
from panel_gerber import package_files,export_panel
from fabrication_export import FabricationExport
from silkscreen_project import load
from test_panel import BOARD

class SilkscreenProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.projects=patch('pcb_project.projects_root',return_value=self.root/'projects');self.projects.start()
        self.files,_,_=package_files(PanelDocument(hp=26))
        self.zip=self.root/'frontal.zip'
        with zipfile.ZipFile(self.zip,'w') as z:
            for name,raw in self.files.items():z.writestr(name,raw)
        self.app=DesignToolsApp();self.app.withdraw()

    def tearDown(self):
        editor=getattr(self.app,'_conv_editor',None)
        if editor is not None and editor.winfo_exists():editor.destroy()
        for token in self.app.tk.splitlist(self.app.tk.call('after','info')):
            self.app.after_cancel(token)
        self.app.destroy();self.projects.stop();self.temp.cleanup()

    def walk(self,widget):
        for child in widget.winfo_children():yield child;yield from self.walk(child)

    def pump(self,seconds=.25):
        end=time.monotonic()+seconds
        while time.monotonic()<end:self.app.update();time.sleep(.005)

    def test_old_panel_extensions_get_roles_and_exact_profile_even_when_hidden(self):
        a=self.app;a.load_paths([self.zip])
        expected={'GKO':'OUTLINE','GTO':'TOP_SILK','GBO':'BOTTOM_SILK','GTS':'TOP_MASK','GBS':'BOTTOM_MASK','GTL':'TOP_COPPER','GBL':'BOTTOM_COPPER'}
        for entry in a.gerber_layers:
            self.assertEqual(layer_role(entry['name'],entry['layer']),expected[Path(entry['name']).suffix[1:]])
        a._find_outline_layer()['var_visible'].set(False)
        a.add_references([Reference('cobre_lejano.gtl',BOARD.replace('X40000000','X240000000'))])
        self.assertEqual(a._get_ref_bounds(),(0,0,131.74,128.5))
        self.assertIn('131.74 × 128.50',a.board_size.get())
        labels=[e['label'] for e in a._build_export_items()]
        self.assertTrue(any('Serigrafía superior' in value and 'panel.GTO' in value for value in labels))
        self.assertTrue(a._find_loaded_layer_for_tag('TOP_SILK')['name'].endswith('.GTO'))
        self.assertEqual(layer_role('anything.art',Reference('anything.art',self.files['panel.GTO'].decode()).layer),'TOP_SILK')

    def test_opening_a_panel_package_replaces_previous_pcb_layers_and_source(self):
        a=self.app;a.add_references([Reference('old_OUTLINE.art',BOARD)])
        a.load_paths([self.zip])
        self.assertEqual(len(a.gerber_layers),7)
        self.assertFalse(any(e['name'].startswith('old') for e in a.gerber_layers))
        self.assertEqual(a.fabrication_source,self.zip)
        self.assertIsNone(a.panel_project)
        self.assertEqual(a._get_ref_bounds(),(0,0,131.74,128.5))

    def test_save_loose_zip_and_image_is_portable_and_retains_layer_state_and_recipe(self):
        a=self.app;a.load_paths([self.zip])
        a.overlay_image=Image.new('RGBA',(25,15),(70,80,90,200))
        a.overlay_x_mm,a.overlay_y_mm=-2.25,8.5;a.overlay_w_mm,a.overlay_h_mm=140,84
        a.overlay_angle_deg=13;a.overlay_threshold.set(177)
        a._conv_algo='atkinson';a._conv_contrast=1.7;a._conv_invert=True;a._conv_pxsize=.3
        a._conv_tuning=dict(brightness=.8,gamma=1.3,sharpness=1.2,smoothing=.2)
        a.logo_targets=[dict(tag='TOP_SILK',ext='.GTO',label='Logo',mode='merge')]
        a._export_preferences={'panel.GTO':dict(selected=True,mode='merge',clearance=.2)}
        a.gerber_layers[1]['var_visible'].set(False);a.gerber_layers[2]['var_bbox'].set(True)
        a.zoom=1.7;a.pan_x=12;a.pan_y=-9
        saved=self.root/'portable'/'frontal.silk.json';saved.parent.mkdir()
        with patch('design_app.filedialog.asksaveasfilename',return_value=str(saved)):
            self.assertTrue(a.save_current_project())
        source_hash=hashlib.sha256(self.zip.read_bytes()).hexdigest()
        self.assertTrue(a.fabrication_source.is_relative_to(saved.parent))
        pinned=a.fabrication_source
        for _ in range(3):a.save_project_session()
        self.assertEqual(a.fabrication_source,pinned)
        self.assertEqual(len(list((saved.parent/'fabricacion').iterdir())),1)
        moved=self.root/'moved';shutil.copytree(saved.parent,moved)
        self.zip.unlink();shutil.rmtree(saved.parent)
        b=DesignToolsApp(project=moved/saved.name);b.withdraw()
        try:
            self.assertEqual(b.overlay_image.getpixel((0,0)),(70,80,90,200))
            self.assertEqual((b.overlay_x_mm,b.overlay_y_mm,b.overlay_w_mm,b.overlay_h_mm,b.overlay_angle_deg),(-2.25,8.5,140,84,13))
            self.assertEqual((b._conv_algo,b._conv_contrast,b._conv_invert,b._conv_pxsize),('atkinson',1.7,True,.3))
            self.assertEqual(b._conv_tuning,a._conv_tuning)
            self.assertEqual(b.logo_targets,a.logo_targets);self.assertEqual(b._export_preferences,a._export_preferences)
            self.assertFalse(b.gerber_layers[1]['var_visible'].get());self.assertTrue(b.gerber_layers[2]['var_bbox'].get())
            self.assertEqual((b.zoom,b.pan_x,b.pan_y),(1.7,12,-9))
            self.assertEqual(hashlib.sha256(b.fabrication_source.read_bytes()).hexdigest(),source_hash)
            self.assertTrue(b.fabrication_destination.is_relative_to(moved))
            self.assertEqual(b._get_ref_bounds(),(0,0,131.74,128.5))
            with FabricationExport(b.fabrication_destination,{},b.fabrication_source) as package:
                _,result=package.finish([],{},{})
            with zipfile.ZipFile(result) as z:
                for name,data in self.files.items():self.assertEqual(z.read(name),data)
        finally:b.destroy()

    def test_save_button_commits_open_conversion_controls_and_cancel_does_not_close_app(self):
        a=self.app;a.load_paths([self.zip]);a.overlay_image=Image.new('RGB',(20,10),'gray')
        a._open_conversion_editor();self.pump()
        row=next(w for w in self.walk(a._conv_editor) if w.winfo_name()=='contrast_control')
        field=row.nametowidget('value');field.delete(0,'end');field.insert(0,'1,72')
        saved=self.root/'buttons.silk.json'
        button=next(w for w in self.walk(a) if isinstance(w,tk.Button) and w.cget('text')=='Guardar proyecto')
        with patch('design_app.filedialog.asksaveasfilename',return_value=str(saved)):button.invoke()
        self.assertEqual(json.loads(saved.read_text())['image_session']['contrast'],1.72)
        self.assertTrue(a.bind('<Control-s>'))
        a.silk_project=None
        with patch('design_app.filedialog.asksaveasfilename',return_value=''):a.close_project()
        self.assertTrue(a.winfo_exists())

    def test_invalid_project_is_rejected_before_replacing_current_work(self):
        a=self.app;a.load_paths([self.zip])
        saved=self.root/'good.silk.json'
        with patch('design_app.filedialog.asksaveasfilename',return_value=str(saved)):a.save_current_project()
        data=json.loads(saved.read_text());data['fabrication_sha256']='bad';saved.write_text(json.dumps(data))
        layers=a.gerber_layers[:]
        with self.assertRaises(ValueError):a.open_project_file(saved)
        self.assertEqual(a.gerber_layers,layers)
        empty=self.root/'empty.zip'
        with zipfile.ZipFile(empty,'w'):pass
        with patch('design_app.messagebox.showerror') as error:
            self.assertFalse(a.load_paths([empty]));self.assertTrue(error.called)
        self.assertEqual(a.gerber_layers,layers)

    def test_legacy_recipe_keys_with_image_save_and_export_choices_persist_immediately(self):
        a=self.app;a.load_paths([self.zip]);a.overlay_image=Image.new('RGB',(12,12),'black')
        item=next(i for i in a._build_export_items() if i['ext'].lower()=='.gto')
        legacy=(item['label'],item['tag'],item['ext'],item['is_new'])
        a._export_preferences={legacy:dict(selected=True,mode='logo_windows',clearance=.35,window_shape='contour')}
        saved=self.root/'recipes.silk.json'
        with patch('design_app.filedialog.asksaveasfilename',return_value=str(saved)):self.assertTrue(a.save_current_project())
        key=a._export_preference_key(item)
        self.assertEqual(json.loads(saved.read_text())['image_session']['preferences'][key]['window_shape'],'contour')
        def choose(items):
            a._export_preferences[key].update(clearance=.6,window_shape='rectangle')
            return [dict(item=item,mode='logo_windows',clearance=.6,window_shape='rectangle')]
        with patch.object(a,'_choose_export_dialog',side_effect=choose),patch('export_result.show_export_result'):
            archive=a.export_gerber()
        self.assertTrue(archive.is_file())
        state=load(saved)[1]
        self.assertEqual(state['preferences'][key]['window_shape'],'rectangle')
        self.assertEqual(state['preferences'][key]['clearance'],.6)
        with zipfile.ZipFile(archive) as z:self.assertEqual(json.loads(z.read('manifest.json'))['changes'][0]['window_shape'],'rectangle')

    def test_next_front_export_has_descriptive_names_and_unchanged_geometry(self):
        document=PanelDocument(hp=26)
        exported=export_panel(document,self.root/'export','distorsion_3u')
        report=json.loads(exported.with_suffix('.json').read_text())
        with zipfile.ZipFile(exported) as z:
            self.assertIn('distorsion_3u_contorno.GKO',z.namelist())
            self.assertIn('distorsion_3u_serigrafia_superior.GTO',z.namelist())
            for name,raw in self.files.items():
                role=layer_role(name,Reference(name,raw.decode()).layer)
                renamed=next(n for n in z.namelist() if layer_role(n)==role)
                self.assertEqual(z.read(renamed),raw)
                self.assertEqual(hashlib.sha256(raw).hexdigest(),report['files'][renamed]['sha256'])

    def test_standalone_panels_keep_separate_image_sessions_without_allegro_metadata(self):
        document=PanelDocument(hp=26,layers=[Reference(n,raw.decode()) for n,raw in self.files.items()])
        first=self.root/'one.panel.json';second=self.root/'two.panel.json'
        document.save(first);document.save(second)
        a=self.app;a.open_project_file(first)
        a.overlay_image=Image.new('RGB',(10,10),'black');a.overlay_w_mm,a.overlay_h_mm=70,60
        a.overlay_x_mm,a.overlay_y_mm=3,4;a.overlay_threshold.set(175)
        self.assertTrue(a.save_current_project())
        self.assertTrue((self.root/'one.image_session.json').is_file())
        a.open_project_file(second)
        self.assertIsNone(a.overlay_image)
        a.open_project_file(first)
        self.assertIsNotNone(a.overlay_image)
        self.assertEqual((a.overlay_x_mm,a.overlay_y_mm,a.overlay_w_mm,a.overlay_h_mm),(3,4,70,60))
        self.assertEqual(a.overlay_threshold.get(),175)

if __name__=='__main__':unittest.main()
