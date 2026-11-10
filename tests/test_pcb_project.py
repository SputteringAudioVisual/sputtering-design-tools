"""Portable PCB folders, automatic fabrication discovery and routed pads."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from drill import RouteLayer
from panel_model import PanelDocument,Element,load_references
from pcb_project import prepare_project,fabrication_source,project_info,export_folder,local_path
from footprint_holes import DEFAULT_RULES,proposals
from test_footprint_holes import sample
from test_panel import BOARD


def package(root,version=1,offset=0):
    folder=root/'Fabricacion';folder.mkdir(exist_ok=True)
    d=sample()
    pins=[p for c in d['components'] if c['refdes']!='S1' for p in c['pins']]
    drill='M48\nMETRIC,TZ\nT01C0.7\n%\nG90\nT01\n'+''.join(f'X{p["x_mm"]+offset:.5f}Y{p["y_mm"]:.5f}\n' for p in pins)+'M30\n'
    route='M48\nMETRIC,TZ\nT01C1.1\n%\nG90\nT01\n'
    for p in d['components'][2]['pins']:
        route+=f'G00X{p["x_mm"]-.55+offset:.5f}Y{p["y_mm"]:.5f}\nM15\nG01X{p["x_mm"]+.55+offset:.5f}Y{p["y_mm"]:.5f}\nM16\n'
    route+='M30\n'
    files={'OUTLINE.art':BOARD.encode(),'SILK_TOP.art':BOARD.encode(),
           'PCB.drl':drill.encode(),'PCB_SLOTS.rou':route.encode(),
           'parametros/nc_param.txt':b'INTEGER-PLACES 5\nDECIMAL-PLACES 5\n'}
    manifest=dict(board='test',fabrication_version=version,files=[dict(name=n,bytes=len(v),sha256=hashlib.sha256(v).hexdigest()) for n,v in files.items()])
    files['manifest.json']=json.dumps(manifest).encode()
    path=folder/f'test_fab_v{version:03d}.zip'
    with zipfile.ZipFile(path,'w') as archive:
        for n,v in files.items():archive.writestr(n,v)
    return path


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.board=self.root/'test.brd';self.board.write_bytes(b'CAD original')
        self.data=sample();self.data['source_sha256']=hashlib.sha256(self.board.read_bytes()).hexdigest()
        self.rules=patch('pcb_project.library_rules',return_value=copy.deepcopy(DEFAULT_RULES));self.rules.start()

    def tearDown(self):
        self.rules.stop();self.temp.cleanup()

    def test_discovers_newest_original_and_copies_all_sources(self):
        package(self.root,1);latest=package(self.root,4)
        edited=latest.with_name('test_fab_v004_edit_v999.zip');shutil.copy2(latest,edited)
        original=self.board.read_bytes();raw=latest.read_bytes()
        p=prepare_project(self.board,root=self.root/'projects',data=self.data)
        doc=p['document'];path=Path(p['project_path']);info=project_info(path)
        self.assertEqual(info['fabrication_version'],4)
        self.assertEqual(fabrication_source(path).read_bytes(),raw)
        self.assertEqual(local_path(path.parent,info['pcb']).read_bytes(),original)
        self.assertEqual(len(doc.layers),4)
        self.assertEqual(len([r for r in doc.layers if r.name.endswith('.rou')][0].layer.drawables),3)
        points=[(v['x'],v['y']) for r in doc.layers if r.coord_format for v in r.layer.drawables]
        items,_=proposals(self.data,DEFAULT_RULES,doc.reference_bounds(),points)
        self.assertEqual(len(items),3)
        self.assertEqual(self.board.read_bytes(),original);self.assertEqual(latest.read_bytes(),raw)
        self.assertTrue(export_folder(path,'frontal').is_relative_to(path.parent))

    def test_relocated_project_works_without_original_board_or_zip(self):
        package(self.root,4)
        p=prepare_project(self.board,root=self.root/'projects',data=self.data)
        old=Path(p['project_path']);moved=self.root/'moved'
        shutil.copytree(old.parent,moved)
        self.board.rename(self.board.with_suffix('.unavailable'))
        (self.root/'Fabricacion').rename(self.root/'old_fabrication')
        new=moved/old.name
        self.assertTrue(fabrication_source(new).exists())
        doc=PanelDocument.load(new)
        self.assertEqual(doc.component_data,self.data)
        info=project_info(new)
        again=prepare_project(local_path(moved,info['pcb']),doc,new,data=self.data)
        self.assertEqual(again['document'].component_data,self.data)

    def test_reimport_preserves_user_layout_and_backs_up_project(self):
        package(self.root,4)
        p=prepare_project(self.board,root=self.root/'projects',data=self.data)
        doc=p['document'];doc.hp=26;doc.pcb_dx=12.345;doc.pcb_dy=-9.87
        doc.elements=[Element('text',40,90,4,'My label',font='gothic',angle=45),Element('hole',25,50,8.128,'P1','potentiometer')]
        path=Path(p['project_path']);doc.save(path);before=doc.to_dict();raw=path.read_bytes()
        again=prepare_project(self.board,doc,path,data=self.data)
        after=again['document'].to_dict()
        for key in ('hp','gap','pcb_dx','pcb_dy','elements'):self.assertEqual(after[key],before[key])
        self.assertTrue(any(f.read_bytes()==raw for f in (path.parent/'historial').glob('*/*.panel.json')))

    def test_newer_mismatched_revision_does_not_fall_back_or_touch_project(self):
        package(self.root,1)
        p=prepare_project(self.board,root=self.root/'projects',data=self.data)
        path=Path(p['project_path']);before=path.read_bytes()
        package(self.root,2,offset=.06)
        with self.assertRaisesRegex(ValueError,'no coincide'):
            prepare_project(self.board,p['document'],path,data=self.data)
        self.assertEqual(path.read_bytes(),before)

    def test_cancelled_or_stale_source_does_not_create_project(self):
        package(self.root,4)
        stopped=threading.Event();stopped.set()
        with self.assertRaisesRegex(ValueError,'cancelada'):
            prepare_project(self.board,root=self.root/'projects',data=self.data,cancel=stopped)
        self.assertFalse((self.root/'projects').exists())
        bad=copy.deepcopy(self.data);bad['source_sha256']='old'
        with self.assertRaises(ValueError):prepare_project(self.board,root=self.root/'projects',data=bad)

    def test_bad_manifest_and_path_escape_are_rejected(self):
        path=package(self.root,4)
        with zipfile.ZipFile(path) as z:files={n:z.read(n) for n in z.namelist()}
        files['PCB.drl']+=b'corruption'
        with zipfile.ZipFile(path,'w') as z:
            for n,v in files.items():z.writestr(n,v)
        with self.assertRaisesRegex(ValueError,'manifiesto'):
            prepare_project(self.board,root=self.root/'projects',data=self.data)
        with self.assertRaises(ValueError):local_path(self.root,'../escape')

    def test_exact_linked_release_can_open_without_mechanical_footprint_rules(self):
        from test_release_contract import original,write_archive
        from release_contract import SCHEMA,inventory
        from pcb_project import discover_fabrication
        from unittest.mock import patch
        import uuid
        cad=self.root/'Cad';allegro=cad/'allegro';allegro.mkdir(parents=True)
        board=allegro/'test.brd';board.write_bytes(b'CAD original')
        data=copy.deepcopy(self.data);data['source_sha256']=hashlib.sha256(board.read_bytes()).hexdigest()
        fabrication=allegro/'Fabricacion';fabrication.mkdir()
        source=package(fabrication,1)
        from package_integrity import read_archive
        files,_=read_archive(source);files.pop('manifest.json')
        _,_,manifest=original(fabrication,'template.zip')
        manifest=copy.deepcopy(manifest)
        (fabrication/'template.zip').unlink()
        manifest.update(schema=SCHEMA,project_id=str(uuid.uuid4()),project_name='Test PCB',pcb_revision='1.0',
            source_board_sha256=data['source_sha256'],source_saved_board_sha256=data['source_sha256'],
            source_saved_board_observed_utc='2026-11-08T00:00:00Z',source_saved_board_observation='export_requested')
        manifest['source_board'].update(sha256=data['source_sha256'],bytes=len(board.read_bytes()))
        manifest['files']=inventory(files)
        write_archive(source,files,manifest)
        registry=cad/'Sputtering'/'pcb'/manifest['project_id']/'project.json';registry.parent.mkdir(parents=True)
        registry.write_text(json.dumps(dict(schema='sputtering.pcb-identity.v1',project_id=manifest['project_id'],
            revisions={'1.0':{}},latest_declared_revision='1.0')))
        link=allegro/'Asistente'/'test'/'identidad_pcb.json';link.parent.mkdir(parents=True)
        link.write_text(json.dumps(dict(project_id=manifest['project_id'],pcb_revision='1.0',
            project_relative_path=registry.relative_to(cad).as_posix())))
        with patch('pcb_project.proposals',return_value=([],[])):
            result=discover_fabrication(board,data,{},explicit=source)
        self.assertEqual(result['source'],source)
        self.assertEqual(result['verified_components'],0)
        self.assertEqual(result['fabrication_check'],'identity_and_source_hash')
        with patch('pcb_project.proposals',return_value=([],[])):
            prepared=prepare_project(board,data=data,fabrication=source)
        meta=project_info(prepared['project_path'])
        self.assertEqual(meta['fabrication_check'],'identity_and_source_hash')
        self.assertEqual(meta['fabrication_association']['release_label'],'F001')

    def test_historical_zip_requires_explicit_selection_when_footprints_are_unrecognized(self):
        from pcb_project import discover_fabrication
        source=package(self.root,1)
        with patch('pcb_project.proposals',return_value=([],[])):
            result=discover_fabrication(self.board,self.data,{},explicit=source)
        self.assertEqual(result['source'],source)
        self.assertEqual(result['fabrication_check'],'explicit_outline_only')


    def test_importing_panel_texts_reuses_the_open_front_panel_window(self):
        from design_app import DesignToolsApp
        from unittest.mock import Mock
        from types import SimpleNamespace
        window=Mock();window.winfo_exists.return_value=True
        app=SimpleNamespace(panel_window=window,open_panel=Mock())
        DesignToolsApp.import_panel_texts(app)
        app.open_panel.assert_called_once_with()
        window.import_refdes.assert_called_once_with()


class RouteTests(unittest.TestCase):
    def test_ambiguous_arcs_incremental_and_diagonal_routes_are_rejected(self):
        good='M48\nMETRIC,TZ\nT01C1.1\n%\nG90\nT01\nG00X10.0Y20.0\nM15\nG01X11.1Y20.0\nM16\nM30'
        layer=RouteLayer(good)
        self.assertAlmostEqual(layer.drawables[0]['x'],10.55)
        self.assertAlmostEqual(layer.drawables[0]['sx'],2.2)
        for bad in (good.replace('10.0','1000').replace('11.1','1110'),
                    good.replace('G90','G91'),good.replace('G01','G02'),good.replace('Y20.0\nM16','Y21.0\nM16')):
            with self.assertRaises(ValueError):RouteLayer(bad)


class ProjectUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.board=self.root/'test.brd';self.board.write_bytes(b'CAD original')
        self.data=sample();self.data['source_sha256']=hashlib.sha256(self.board.read_bytes()).hexdigest()
        package(self.root,4)
        self.rules=patch('pcb_project.library_rules',return_value=copy.deepcopy(DEFAULT_RULES));self.rules.start()
        self.prepared=prepare_project(self.board,root=self.root/'projects',data=self.data)
        self.path=Path(self.prepared['project_path'])

    def tearDown(self):self.rules.stop();self.temp.cleanup()

    def test_image_session_survives_moving_folder_and_keeps_export_local(self):
        from design_app import DesignToolsApp
        from PIL import Image
        app=DesignToolsApp(project=self.path);app.withdraw()
        try:
            app.overlay_image=Image.new('RGBA',(25,15),'white');app.overlay_svg_path=None
            app.overlay_x_mm,app.overlay_y_mm=1.25,2.5;app.overlay_w_mm,app.overlay_h_mm=6,3.6
            app.overlay_angle_deg=45;app.overlay_threshold.set(193)
            app._conv_algo='floyd_fast';app._conv_contrast=1.4;app._conv_invert=True;app._conv_pxsize=.3
            app._conv_tuning=dict(brightness=.9,gamma=1.4,sharpness=1.2,smoothing=.3)
            app.save_project_session()
        finally:app.destroy()
        moved=self.root/'moved';shutil.copytree(self.path.parent,moved)
        app=DesignToolsApp(project=moved/self.path.name);app.withdraw()
        try:
            self.assertEqual(app.overlay_image.size,(25,15))
            self.assertEqual((app.overlay_x_mm,app.overlay_y_mm),(1.25,2.5))
            self.assertEqual((app.overlay_w_mm,app.overlay_h_mm),(6,3.6))
            self.assertEqual(app.overlay_angle_deg,45);self.assertEqual(app.overlay_threshold.get(),193)
            self.assertEqual((app._conv_algo,app._conv_contrast,app._conv_pxsize),('floyd_fast',1.4,.3))
            self.assertEqual(app._conv_tuning,dict(brightness=.9,gamma=1.4,sharpness=1.2,smoothing=.3))
            self.assertTrue(app.fabrication_source.is_relative_to(moved))
            self.assertEqual(app.fabrication_destination,moved/'exports'/'serigrafia')
            self.assertEqual(len(app.drill_references),2)
        finally:app.destroy()

    def test_footprint_dialog_prepares_and_adopts_complete_project(self):
        from panel_editor import PanelEditor
        from footprint_dialog import FootprintDialog
        import time
        app=PanelEditor(project=self.path);app.withdraw()
        try:
            # Simulate the previous project's missing milling reference.
            app.document.layers=[r for r in app.document.layers if not r.name.endswith('.rou')]
            dialog=FootprintDialog(app)
            with patch('pcb_project.read_pcb',return_value=copy.deepcopy(self.data)):
                dialog.start_read(str(self.board))
                deadline=time.monotonic()+6
                while dialog.busy and time.monotonic()<deadline:
                    app.update();time.sleep(.01)
            self.assertFalse(dialog.busy)
            self.assertEqual(set(dialog.items),{'P1','J1','S1'})
            self.assertTrue(any(r.name.endswith('.rou') for r in app.document.layers))
            self.assertEqual(app.document.component_data,self.data)
            dialog.close()
        finally:app.destroy()

    def test_panel_export_uses_project_folder_and_open_preserves_manual_translation(self):
        from panel_editor import PanelEditor
        from design_app import DesignToolsApp
        from tkinter import ttk
        document=PanelDocument.load(self.path);document.pcb_dx=12.34;document.pcb_dy=-4.56;document.save(self.path)
        app=DesignToolsApp(project=self.path);app.withdraw()
        try:
            app.open_panel()
            self.assertEqual((app.panel_window.document.pcb_dx,app.panel_window.document.pcb_dy),(12.34,-4.56))
        finally:app.destroy()
        panel=PanelEditor(project=self.path);panel.withdraw()
        try:
            with patch('panel_editor.filedialog.askdirectory') as ask,patch('panel_gerber.export_panel',return_value=Path('test.zip')) as export,patch('panel_editor.messagebox.showinfo'):
                panel.export_gerber()
                button=next(w for w in panel._descendants(panel) if isinstance(w,ttk.Button) and w.cget('text')=='Guardar proyecto y generar ZIP')
                button.invoke()
                ask.assert_not_called()
                self.assertEqual(export.call_args.args[1],self.path.parent/'exports'/'frontal')
        finally:panel.destroy()


if __name__=='__main__':unittest.main()
