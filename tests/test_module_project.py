"""A module is portable through PCB, panel, artwork and manufacturing stages."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_pcb_project import package
from test_footprint_holes import sample
from footprint_holes import DEFAULT_RULES
from pcb_project import prepare_project,load_project
from panel_model import Element
from panel_gerber import export_panel
from module_project import (INDEX,read,verify,stage_path,continue_panel_artwork,last_panel_package,record_output)
from silkscreen_project import load,save


class ModuleProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.board=self.root/'test.brd';self.board.write_bytes(b'PCB source')
        self.data=sample();self.data['source_sha256']=hashlib.sha256(self.board.read_bytes()).hexdigest()
        package(self.root,4)
        self.rules=patch('pcb_project.library_rules',return_value=copy.deepcopy(DEFAULT_RULES));self.rules.start()
        result=prepare_project(self.board,data=self.data)
        self.path=Path(result['project_path']);self.module=self.path.parent

    def tearDown(self):self.rules.stop();self.temp.cleanup()

    def panel_and_art(self):
        document=load_project(self.path);document.hp=26;document.elements=[Element('text',30,80,3,'GAIN')];document.save(self.path)
        archive=export_panel(document,self.module/'exports/frontal','test',project=self.path)
        art=continue_panel_artwork(self.path,archive)
        refs,state,views,source,view=load(art)
        (art.parent/'assets').mkdir();Image.new('RGB',(20,15),'black').save(art.parent/'assets'/'photo.png')
        state.update(enabled=True,image='assets/photo.png',x_mm=-2,y_mm=3,width_mm=60,height_mm=45,angle_deg=0,
                     threshold=170,contrast=1.4,algorithm='floyd_fast',invert=False,pixel_mm=.15,dot_mm=.15)
        save(art,refs,state,views,source,view)
        return document,archive,art

    def test_default_next_to_board_and_repeated_save_does_not_invent_versions(self):
        self.assertEqual(self.module.parent,self.board.parent/'Sputtering')
        doc=load_project(self.path);before=read(self.module)['stages']['panel']['revision']
        doc.save(self.path);self.assertEqual(read(self.module)['stages']['panel']['revision'],before)
        doc.elements=[Element('text',20,70,3,'REV 2')];doc.save(self.path)
        self.assertEqual(read(self.module)['stages']['panel']['revision'],before+1)
        again=prepare_project(self.board,data=self.data)
        self.assertEqual(Path(again['project_path']),self.path)
        self.assertEqual(again['document'].elements[0].text,'REV 2')

    def test_updated_front_preserves_artwork_settings_and_records_exact_upstream(self):
        doc,archive,art=self.panel_and_art()
        self.assertEqual(last_panel_package(self.path),archive)
        old=load(art)[1]
        doc.elements[0].text='GAIN 2';doc.save(self.path)
        new=export_panel(doc,self.module/'exports/frontal','test',project=self.path)
        continue_panel_artwork(self.path,new)
        refs,state,_,source,_=load(art)
        for key in ('x_mm','y_mm','width_mm','height_mm','threshold','contrast'):self.assertEqual(state[key],old[key])
        self.assertEqual(source.read_bytes(),new.read_bytes())
        report=json.loads(new.with_suffix('.json').read_text())
        self.assertEqual(report['lineage']['project_sha256'],hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertTrue(verify(self.module)['artifacts'])

    def test_move_entire_folder_and_remove_originals(self):
        _,_,art=self.panel_and_art();relative=art.relative_to(self.module)
        before=verify(self.module);moved=self.root/'moved';shutil.copytree(self.module,moved)
        shutil.rmtree(self.module);self.board.unlink();shutil.rmtree(self.root/'Fabricacion')
        self.assertTrue(load_project(moved/self.path.name).elements)
        self.assertEqual(load(moved/relative)[1]['threshold'],170)
        self.assertEqual(verify(moved),before)
        # Both current and historical JSON inputs are checked, not just the ZIP.
        state=json.loads((moved/relative).read_text());state['image_session']['threshold']=1
        (moved/relative).write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'revisión'):verify(moved)

    def test_migration_keeps_latest_art_and_historical_packages_without_false_revision(self):
        from module_migration import consolidate
        # A legacy independent artwork project, the structure used previously.
        document=load_project(self.path);document.hp=26;document.elements=[Element('text',30,80,3,'GAIN')];document.save(self.path)
        package_path=export_panel(document,self.module/'exports/frontal','test')
        legacy=self.root/'old_art';legacy.mkdir();(legacy/'exports'/'serigrafia').mkdir(parents=True)
        from panel_model import load_references
        refs,errors=load_references([package_path]);self.assertFalse(errors)
        state=dict(schema='sputtering.image-session.v1',enabled=False)
        source=legacy/'old.silk.json';save(source,refs,state,{},package_path)
        shutil.copy2(package_path,legacy/'exports/serigrafia'/'old_export.zip')
        before=source.read_bytes();destination=self.root/'consolidated'
        index=consolidate(self.path,source,destination)
        self.assertEqual(index,destination/INDEX);self.assertEqual(source.read_bytes(),before)
        current=stage_path(destination,'panel_artwork');self.assertTrue(current.exists())
        self.assertTrue(verify(destination)['artifacts'])
        historic=next(i for i in read(destination)['artifacts'] if i['path'].endswith('old_export.zip'))
        self.assertIsNone(historic['lineage']['revision'])

    def test_app_stage_navigation_keeps_real_pcb_behind_panel_and_local_outputs(self):
        from design_app import DesignToolsApp
        from pcb_project import export_folder
        _,archive,art=self.panel_and_art()
        app=DesignToolsApp(project=art);app.withdraw()
        try:
            self.assertEqual(app.fabrication_destination,self.module/'exports'/'arte_frontal')
            app.open_panel()
            self.assertEqual(app.panel_window.project_path,str(self.path))
            self.assertEqual(app.panel_window.document.reference_bounds(),load_project(self.path).reference_bounds())
            app.panel_window.destroy();app.panel_window=None
            app.open_module_stage('pcb_silkscreen');app.save_current_project()
            self.assertEqual(app.silk_project,stage_path(self.module,'pcb_silkscreen'))
            self.assertEqual(app.fabrication_destination,self.module/'exports'/'serigrafia')
        finally:app.destroy()

    def test_recovery_creates_new_revision_and_keeps_current_and_old_outputs(self):
        from module_project import revisions,restore_revision
        doc,archive,art=self.panel_and_art()
        wanted=next(r for r in revisions(self.module) if r['stage']=='panel')
        doc.elements[0].text='NEW TEXT';doc.save(self.path)
        before=read(self.module)['stages']['panel']['revision']
        restored=restore_revision(self.module,wanted['checkpoint'])
        self.assertEqual(load_project(restored).elements[0].text,'GAIN')
        self.assertEqual(read(self.module)['stages']['panel']['revision'],before+1)
        self.assertTrue(archive.is_file());self.assertTrue(verify(self.module)['artifacts'])

    def test_recovery_button_reloads_image_controls_instead_of_overwriting_restored_state(self):
        import tkinter as tk
        from tkinter import ttk
        from design_app import DesignToolsApp
        _,_,art=self.panel_and_art()
        refs,state,views,source,view=load(art)
        state={k:v for k,v in state.items() if not k.startswith('_')};state['threshold']=201
        save(art,refs,state,views,source,view)
        app=DesignToolsApp(project=art);app.withdraw()
        def walk(w):
            for c in w.winfo_children():yield c;yield from walk(c)
        try:
            self.assertEqual(app.overlay_threshold.get(),201)
            app.show_module_versions()
            table=next(w for w in walk(app) if isinstance(w,ttk.Treeview))
            target=next(i for i in table.get_children() if table.item(i,'values')[:2]==('Imagen del frontal','0002'))
            table.selection_set(target)
            next(w for w in walk(app) if isinstance(w,ttk.Button) and w.cget('text')=='Recuperar revisión seleccionada').invoke()
            self.assertEqual(app.overlay_threshold.get(),170)
            self.assertEqual(load(art)[1]['threshold'],170)
            self.assertTrue(verify(self.module)['revisions_files'])
        finally:app.destroy()

    def test_shared_capture_allegro_root_and_legacy_project_lookup(self):
        from module_project import cad_project_root,from_board
        cad=self.root/'Mi proyecto';allegro=cad/'Allegro';allegro.mkdir(parents=True)
        capture=cad/'Capture';capture.mkdir();(capture/'test.opj').write_text('Capture project')
        board=allegro/'test.brd';board.write_bytes(self.board.read_bytes());package(allegro,4)
        self.assertEqual(cad_project_root(board),cad)
        result=prepare_project(board,data=self.data)
        path=Path(result['project_path'])
        self.assertEqual(path.parent,cad/'Sputtering'/'test')
        self.assertEqual(from_board(board),path)
        # The location used before the shared root remains discoverable.
        legacy=allegro/'Sputtering';legacy.mkdir()
        moved=legacy/path.parent.name;shutil.move(str(path.parent),moved)
        self.assertEqual(from_board(board),moved/path.name)

    def test_open_button_loads_new_cad_project_saves_exports_and_reopens_without_manual_paths(self):
        from design_app import DesignToolsApp
        import tkinter as tk
        cad=self.root/'Nuevo modulo';allegro=cad/'allegro';allegro.mkdir(parents=True)
        capture=cad/'test.opj';capture.write_text('Original Capture')
        board=allegro/'test.brd';board.write_bytes(self.board.read_bytes())
        source=package(allegro,4)
        old=load_project(self.path);old.elements=[Element('text',20,70,3,'OLD MODULE')];old.save(self.path)
        app=DesignToolsApp(project=self.path);app.withdraw()
        def walk(w):
            for child in w.winfo_children():yield child;yield from walk(child)
        try:
            with patch('design_app.filedialog.askopenfilename',return_value=str(board)),\
                 patch('pcb_project.read_pcb',return_value=copy.deepcopy(self.data)),\
                 patch('design_app.messagebox.showerror',side_effect=AssertionError):
                next(w for w in walk(app) if isinstance(w,tk.Button) and w.cget('text')=='Abrir proyecto…').invoke()
            module=cad/'Sputtering'/'test'
            self.assertEqual(app.silk_project,stage_path(module,'pcb_silkscreen'))
            self.assertEqual(app.panel_seed.elements,[])
            self.assertTrue((module/'GUIA_CARGA_PROYECTO.txt').is_file())
            app.overlay_image=Image.new('RGB',(15,12),'black')
            b=app._get_ref_bounds();app.overlay_x_mm,app.overlay_y_mm=b[0]+2,b[1]+2
            app.overlay_w_mm,app.overlay_h_mm=10,8
            with patch('design_app.filedialog.asksaveasfilename',side_effect=AssertionError('No manual save path')):
                self.assertTrue(app.save_current_project())
            item=next(i for i in app._build_export_items() if 'SILK' in i['tag'].upper())
            with patch.object(app,'_choose_export_dialog',return_value=[dict(item=item,mode='merge')]),\
                 patch('export_result.show_export_result'),patch('gerber_silkscreen_editor.messagebox.showerror',side_effect=AssertionError):
                archive=app.export_gerber()
            self.assertTrue(archive.is_relative_to(module/'exports'/'serigrafia'))
            app.close_project();app=None
            reopened=DesignToolsApp(project=module/INDEX);reopened.withdraw()
            try:self.assertEqual(reopened.overlay_image.size,(15,12))
            finally:reopened.destroy()
            self.assertEqual(capture.read_text(),'Original Capture')
            self.assertEqual(board.read_bytes(),self.board.read_bytes())
            self.assertTrue(verify(module)['artifacts'])
        finally:
            if app is not None:app.destroy()

    def test_loose_allegro_artwork_does_not_package_native_cad_sources(self):
        from pcb_project import _payload
        cad=self.root/'Loose project';allegro=cad/'allegro';allegro.mkdir(parents=True)
        board=allegro/'test.brd';board.write_bytes(self.board.read_bytes())
        (allegro/'secret.dsn').write_text('Capture source');(allegro/'test.opj').write_text('Capture project')
        source=package(allegro,4)
        with zipfile.ZipFile(source) as z:z.extractall(allegro)
        source.unlink()
        result=prepare_project(board,data=self.data)
        from pcb_project import fabrication_source
        with zipfile.ZipFile(fabrication_source(result['project_path'])) as z:
            self.assertIn('OUTLINE.art',z.namelist());self.assertIn('PCB.drl',z.namelist())
            self.assertFalse(any(Path(n).suffix.lower() in {'.brd','.dsn','.opj'} for n in z.namelist()))


if __name__=='__main__':unittest.main()
