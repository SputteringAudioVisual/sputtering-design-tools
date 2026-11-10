"""Original Allegro releases and Gerber derivatives share one immutable chain."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from release_contract import SCHEMA,association,inventory,validate_release,compare_packages,freshness
from package_integrity import read_archive
from fabrication_export import FabricationExport
from panel_gerber import package_files
from panel_model import PanelDocument,Element,load_references


def original(root,filename='F001.zip'):
    payload,_,_=package_files(PanelDocument(hp=10,elements=[Element('text',20,70,3,'TEST')]))
    snap=b'SYNTHETIC PCB; NOT FOR FABRICATION'
    identity=dict(schema=SCHEMA,project_id=str(uuid.uuid4()),project_name='Synthetic test board',pcb_revision='1.0',
        fabrication_release_id=str(uuid.uuid4()),release_kind='allegro_original',release_label='F001',fabrication_sequence=1,
        parent_release_id=None,parent_archive_sha256=None,parent_manifest_sha256=None,
        source_board_sha256=hashlib.sha256(snap).hexdigest(),source_board=dict(project_relative_path='sources/test.brd',sha256=hashlib.sha256(snap).hexdigest(),bytes=len(snap)),
        created_utc='2000-01-01T00:00:00Z',tools=[dict(name='test fixture',version='1')],profile={},
        release_status='pending_cam_review',provenance_status='verified',status='EXPORTADO_SIN_AVISOS',
        board='test',fabrication_version=1,example_only=True,files=inventory(payload))
    identity['base_fabrication_release_id']=identity['fabrication_release_id']
    path=Path(root)/filename;write_archive(path,payload,identity)
    return path,payload,identity


def write_archive(path,payload,manifest):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for name,raw in payload.items():z.writestr(name,raw)
        if manifest is not None:z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))


class ReleaseContractTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_chain_preserves_pcb_identity_exact_parent_hashes_and_untouched_members(self):
        source,payload,m=original(self.root);source_bytes=source.read_bytes();out=self.root/'exports'
        previous=source;ids={m['fabrication_release_id']}
        for n in (1,2):
            with FabricationExport(out,{},previous) as p:
                p.path_for('panel.GTO').write_bytes(b'G04 test edit*\n'+payload['panel.GTO'])
                _,target=p.finish([dict(file='panel.GTO',mode='merge')],dict(pcb_revision='99.0'))
            contents,child=read_archive(target)
            self.assertEqual(child['release_label'],f'E{n:03d}')
            self.assertEqual(child['project_id'],m['project_id']);self.assertEqual(child['pcb_revision'],'1.0')
            self.assertEqual(child['base_fabrication_release_id'],m['fabrication_release_id'])
            self.assertEqual(child['source_board_sha256'],m['source_board_sha256'])
            self.assertEqual(child['parent_archive_sha256'],hashlib.sha256(previous.read_bytes()).hexdigest())
            with zipfile.ZipFile(previous) as z:self.assertEqual(child['parent_manifest_sha256'],hashlib.sha256(z.read('manifest.json')).hexdigest())
            self.assertNotIn(child['fabrication_release_id'],ids);ids.add(child['fabrication_release_id'])
            self.assertTrue(child['example_only'])
            for name,raw in payload.items():
                if name!='panel.GTO':self.assertEqual(contents[name],raw)
            previous=target
        with FabricationExport(out,{},source) as p:_,third=p.finish([],{})
        self.assertEqual(association(third)['release_label'],'E003')
        self.assertEqual(source.read_bytes(),source_bytes)
        self.assertIn('panel.GTO',compare_packages(source,previous)['changed'])

    def test_legacy_derivative_does_not_invent_pcb_revision_or_original_id(self):
        source=self.root/'historical.zip';payload={'top.gto':b'G04 Old*\nM02*\n'}
        write_archive(source,payload,None);before=source.read_bytes()
        with FabricationExport(self.root/'exports',{},source) as p:_,target=p.finish([],{'pcb_revision':'8.3','project_id':str(uuid.uuid4())})
        _,m=read_archive(target)
        for key in ('project_id','pcb_revision','base_fabrication_release_id','source_board_sha256','parent_release_id','parent_manifest_sha256'):self.assertIsNone(m[key])
        self.assertEqual(m['provenance_status'],'incomplete');self.assertEqual(source.read_bytes(),before)

    def test_loose_layers_have_an_exact_retained_parent_snapshot(self):
        with FabricationExport(self.root,{'top.gto':b'G04 Old*\nM02*\n'}) as p:_,target=p.finish([],{})
        payload,m=read_archive(target)
        self.assertEqual(hashlib.sha256(payload[m['parent_archive_member']]).hexdigest(),m['parent_archive_sha256'])

    def test_v1_rejects_extra_reports_alias_conflicts_wrong_roles_and_invalid_root(self):
        source,payload,m=original(self.root)
        for change in ('unlisted','alias','role','root'):
            contents=copy.deepcopy(payload);manifest=copy.deepcopy(m)
            if change=='unlisted':contents['unknown.txt']=b'extra'
            elif change=='alias':manifest['files'][0]['name']='wrong.gto'
            elif change=='role':
                item=next(f for f in manifest['files'] if f['role']=='profile');item.update(role='copper.top',layer='TOP')
            else:manifest['base_fabrication_release_id']=str(uuid.uuid4())
            bad=self.root/(change+'.zip');write_archive(bad,contents,manifest)
            with self.subTest(change=change),self.assertRaises(ValueError):read_archive(bad)

    def test_sealed_package_rejects_loaded_layers_from_another_release(self):
        source,_,_=original(self.root)
        with self.assertRaisesRegex(ValueError,'Capa ajena'):
            with FabricationExport(self.root/'out',{'another.gbl':b'foreign copper'},source):pass

    def test_module_binding_detects_reused_release_id_and_portable_project_roundtrip(self):
        from module_project import create,stage_path
        from silkscreen_project import save,load
        source,payload,m=original(self.root)
        module=self.root/'module';create(module,'test')
        project=stage_path(module,'pcb_silkscreen');refs,errors=load_references([source]);self.assertFalse(errors)
        state=dict(schema='sputtering.image-session.v1',enabled=False)
        save(project,refs,state,{},source);before=project.read_bytes()
        self.assertEqual(json.loads(before)['fabrication_association']['project_id'],m['project_id'])
        self.assertEqual(load(project)[3].read_bytes(),source.read_bytes())
        payload['panel.GTO']=b'G04 changed*\n'+payload['panel.GTO'];m['files']=inventory(payload)
        forged=self.root/'forged.zip';write_archive(forged,payload,m)
        with self.assertRaisesRegex(ValueError,'reutilizado'):save(project,refs,state,{},forged)
        self.assertEqual(project.read_bytes(),before)

    def test_freshness_distinguishes_disk_revision_and_unknown_memory(self):
        source,_,m=original(self.root);value=association(source)
        board=self.root/'test.brd';board.write_bytes(b'Observed source')
        value['source_saved_board_sha256']=hashlib.sha256(board.read_bytes()).hexdigest()
        meta=dict(source_board=str(board),fabrication_association=dict(value))
        (self.root/'project.json').write_text(json.dumps(meta))
        self.assertIn('memoria de Allegro sin comprobar',freshness(value,self.root))
        board.write_bytes(b'New source');self.assertIn('BRD guardado cambiado',freshness(value,self.root))
        meta['fabrication_association']['pcb_revision']='2.0';(self.root/'project.json').write_text(json.dumps(meta))
        self.assertIn('PCB 2.0',freshness(value,self.root))

    def test_explicit_allegro_identity_link_survives_board_rename(self):
        from pcb_project import _candidates
        cad=self.root/'Cad';folder=cad/'allegro';folder.mkdir(parents=True)
        board=folder/'renamed.brd';board.write_bytes(b'not inferred from this name')
        fab=folder/'Fabricacion';fab.mkdir();source,payload,m=original(fab,'old_filename_fab_v001.zip')
        registry=cad/'Sputtering'/'pcb'/m['project_id']/'project.json';registry.parent.mkdir(parents=True)
        registry.write_text(json.dumps(dict(schema='sputtering.pcb-identity.v1',project_id=m['project_id'],revisions={'1.0':{}},latest_declared_revision='1.0')))
        link=folder/'Asistente'/board.stem/'identidad_pcb.json';link.parent.mkdir(parents=True)
        link.write_text(json.dumps(dict(project_id=m['project_id'],pcb_revision='1.0',project_relative_path=registry.relative_to(cad).as_posix())))
        self.assertEqual(_candidates(board)[0][-1],source)
        self.assertIn('Paquete comprobado',freshness(association(source),cad_root=cad))
        data=json.loads(registry.read_text());data['latest_declared_revision']='2.0';registry.write_text(json.dumps(data))
        self.assertIn('Allegro declara PCB 2.0',freshness(association(source),cad_root=cad))
        m['project_id']=str(uuid.uuid4());write_archive(source,payload,m)
        self.assertFalse(_candidates(board))

    def test_prepared_module_resumes_after_explicitly_linked_board_rename(self):
        from unittest.mock import patch
        from pcb_project import prepare_project
        from module_project import from_board
        from test_pcb_project import package
        from test_footprint_holes import sample
        from footprint_holes import DEFAULT_RULES
        cad=self.root/'Cad';folder=cad/'allegro';folder.mkdir(parents=True)
        board=folder/'test.brd';board.write_bytes(b'Synthetic saved board')
        source=package(folder)
        payload,_=read_archive(source);payload.pop('manifest.json')
        _,_,m=original(self.root)
        m['files']=inventory(payload);write_archive(source,payload,m)
        registry=cad/'Sputtering'/'pcb'/m['project_id']/'project.json';registry.parent.mkdir(parents=True)
        registry.write_text(json.dumps(dict(schema='sputtering.pcb-identity.v1',project_id=m['project_id'],revisions={'1.0':{}},latest_declared_revision='1.0')))
        def bind(path):
            link=folder/'Asistente'/path.stem/'identidad_pcb.json';link.parent.mkdir(parents=True)
            link.write_text(json.dumps(dict(project_id=m['project_id'],pcb_revision='1.0',project_relative_path=registry.relative_to(cad).as_posix())))
        bind(board);data=sample();data['source_sha256']=hashlib.sha256(board.read_bytes()).hexdigest()
        before=source.read_bytes()
        with patch('pcb_project.library_rules',return_value=copy.deepcopy(DEFAULT_RULES)):
            first=prepare_project(board,data=data);path=Path(first['project_path'])
            doc=first['document'];doc.elements=[Element('text',25,60,3,'Keep me')];doc.save(path)
            renamed=board.with_name('other_name.brd');board.rename(renamed);bind(renamed)
            data['board_name']=renamed.name
            self.assertEqual(from_board(renamed),path)
            second=prepare_project(renamed,data=data)
        self.assertEqual(second['project_path'],str(path))
        self.assertEqual(second['document'].elements[0].text,'Keep me')
        self.assertEqual(second['metadata']['fabrication_association']['project_id'],m['project_id'])
        self.assertEqual(source.read_bytes(),before)
        documents={p:p.read_bytes() for p in (path,path.parent/'project.json')}
        payload['report.txt']=b'Changed sealed release';m['files']=inventory(payload);write_archive(source,payload,m)
        with patch('pcb_project.library_rules',return_value=copy.deepcopy(DEFAULT_RULES)):
            with self.assertRaisesRegex(ValueError,'reutilizado'):prepare_project(renamed,data=data)
        for p,raw in documents.items():self.assertEqual(p.read_bytes(),raw)

    def test_ui_displays_source_identity_and_release_comparison_preserves_archives(self):
        import tkinter as tk
        from tkinter import ttk
        from unittest.mock import patch
        from design_app import DesignToolsApp
        from module_project import create,stage_path
        from silkscreen_project import save
        source,payload,m=original(self.root);original_bytes=source.read_bytes()
        module=self.root/'module';create(module,'test')
        path=stage_path(module,'pcb_silkscreen');refs,errors=load_references([source]);self.assertFalse(errors)
        save(path,refs,dict(schema='sputtering.image-session.v1',enabled=False),{},source)
        app=DesignToolsApp(project=path);app.withdraw()
        def walk(w):
            for c in w.winfo_children():yield c;yield from walk(c)
        try:
            self.assertIn('PCB 1.0',app.fabrication_info.get());self.assertIn('F001',app.fabrication_info.get())
            item=next(i for i in app._build_export_items() if i['ext'].lower()=='.gto')
            with patch.object(app,'_choose_export_dialog',return_value=[dict(item=item,mode='base')]),patch('export_result.show_export_result'):
                output=app.export_gerber()
            self.assertTrue(output.is_file());before=output.read_bytes()
            app.show_release_history()
            table=next(w for w in walk(app) if isinstance(w,ttk.Treeview))
            self.assertEqual(len(table.get_children()),2)
            self.assertEqual({table.item(i,'values')[2] for i in table.get_children()},{'F001','E001'})
            table.selection_set(table.get_children())
            next(w for w in walk(app) if isinstance(w,ttk.Button) and w.cget('text')=='Comparar seleccionados').invoke()
            self.assertTrue(any(isinstance(w,tk.Text) for w in walk(app)))
            self.assertEqual(source.read_bytes(),original_bytes);self.assertEqual(output.read_bytes(),before)
        finally:app.destroy()


if __name__=='__main__':unittest.main()
