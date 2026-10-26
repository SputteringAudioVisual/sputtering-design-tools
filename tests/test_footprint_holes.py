import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from footprint_holes import (DEFAULT_RULES, SCHEMA, proposals, validate_data, validate_rules,
                             parse_allegro_reports, read_pcb)
from panel_model import PanelDocument, Element, Reference
from test_panel import BOARD


def sample():
    pin=lambda n,p,x,y:dict(number=n,padstack=p,x_mm=x,y_mm=y)
    return dict(schema=SCHEMA,units='mm',board_name='test.brd',source_sha256='test',
        outline_bounds_mm=[-20,-50,40,50],unplaced=[],components=[
        dict(refdes='P1',footprint='SPTR_RK09_123',x_mm=0,y_mm=0,rotation_deg=0,side='TOP',
             pins=[pin('1','SIGNAL',0,0),pin('2','SIGNAL',2.5,0),pin('3','SIGNAL',5,0),
                   pin('','MECH',-1.9,7),pin('','MECH',6.9,7)]),
        dict(refdes='J1',footprint='SPTR_PJ301M',x_mm=10,y_mm=0,rotation_deg=0,side='TOP',
             pins=[pin('1','SIGNAL',10,0),pin('','C150_H300',10,6.48)]),
        dict(refdes='S1',footprint='SPTR_SPDT',x_mm=20,y_mm=20,rotation_deg=0,side='TOP',
             pins=[pin('1','SIGNAL',20,20),pin('2','SIGNAL',20,15.3),pin('3','SIGNAL',20,10.6)]),
        dict(refdes='R1',footprint='RES',x_mm=5,y_mm=5,rotation_deg=0,side='TOP',pins=[])])


def reports(units='millimeters'):
    header=f'J!board.brd!!0!0!60!100!0.01!{units}!board!\n'
    return {'components':'A!REFDES!COMP_PACKAGE!SYM_X!SYM_Y!SYM_ROTATE!SYM_MIRROR!\n'+header+
                'S!P1!SPTR_RK09_123!0!0!0!NO!\nS!U9!DIP!!!!!\n',
            'pins':'A!REFDES!PIN_NUMBER!PAD_STACK_NAME!PIN_X!PIN_Y!\n'+header+
                'S!P1!!MECH!-1.9!7!\nS!P1!!MECH!6.9!7!\n',
            'outline':'A!GRAPHIC_DATA_NAME!GRAPHIC_DATA_1!GRAPHIC_DATA_2!GRAPHIC_DATA_3!GRAPHIC_DATA_4!\n'+header+
                'S!RECTANGLE!-20!-50!40!50!\n'}


class FootprintGeometryTests(unittest.TestCase):
    def test_mechanical_anchors_use_shaft_not_origin_or_electrical_centroid(self):
        items,skipped=proposals(sample(),DEFAULT_RULES,[-20,-50,40,50])
        self.assertFalse(skipped)
        self.assertEqual([(p['refdes'],p['x_mm'],p['y_mm']) for p in items],
                         [('P1',2.5,7),('J1',10,6.48),('S1',20,15.3)])
        self.assertEqual([p['diameter_mm'] for p in items],[8.128,6.1,6.5])

    def test_world_pin_coordinates_handle_rotated_and_bottom_components(self):
        data=sample();pot=data['components'][0]
        pot.update(side='BOTTOM',rotation_deg=90)
        # Explicit mirrored/rotated coordinates supplied by the PCB exporter.
        for p in pot['pins']:p['x_mm'],p['y_mm']=10-p['y_mm'],20-p['x_mm']
        rules=copy.deepcopy(DEFAULT_RULES);rules['SPTR_RK09_123']['side']='BOTTOM'
        items,_=proposals(data,rules,[-20,-50,40,50])
        self.assertEqual((items[0]['x_mm'],items[0]['y_mm']),(3,17.5))
        items,skipped=proposals(data,DEFAULT_RULES,[-20,-50,40,50])
        self.assertNotIn('P1',[p['refdes'] for p in items]);self.assertEqual(skipped[0][0],'P1')

    def test_ambiguous_anchor_and_unknown_footprint_are_never_guessed(self):
        data=sample();data['components'][0]['pins'].append(dict(number='',padstack='MECH',x_mm=0,y_mm=9))
        items,skipped=proposals(data,DEFAULT_RULES,[-20,-50,40,50])
        self.assertEqual([p['refdes'] for p in items],['J1','S1'])
        self.assertEqual(skipped[0][0],'P1')
        with self.assertRaises(ValueError):proposals(data,DEFAULT_RULES,[0,0,60,100])
        with self.assertRaises(ValueError):proposals(sample(),DEFAULT_RULES,[-20,-50,40,50],[(0,0)])
        shifted=[(p['x_mm']+.06,p['y_mm']) for c in sample()['components'] for p in c['pins']]
        with self.assertRaises(ValueError):proposals(sample(),DEFAULT_RULES,[-20,-50,40,50],shifted)

    def test_extracta_units_unplaced_and_bad_data(self):
        d=parse_allegro_reports(reports())
        self.assertEqual(d['outline_bounds_mm'],[-20,-50,40,50])
        self.assertEqual(d['unplaced'],['U9'])
        inches=parse_allegro_reports(reports('inches'))
        self.assertAlmostEqual(inches['components'][0]['pins'][0]['y_mm'],7*25.4)
        bad=reports();bad['components']=bad['components'].replace('millimeters','unspecified')
        with self.assertRaises(ValueError):parse_allegro_reports(bad)
        for alter in ('units','nan','duplicate'):
            bad=sample()
            if alter=='units':bad['units']='unknown'
            elif alter=='nan':bad['components'][0]['x_mm']='nan'
            else:bad['components'].append(copy.deepcopy(bad['components'][0]))
            with self.assertRaises(ValueError):validate_data(bad)

    def test_read_only_extracta_snapshots_board_and_runs_separate_queries(self):
        with tempfile.TemporaryDirectory() as folder:
            board=Path(folder)/'PCB ñ.brd';board.write_bytes(b'original board')
            def run(args,**kwargs):
                self.assertEqual(Path(args[-2]).read_bytes(),b'original board')
                self.assertNotEqual(Path(args[-2]),board)
                key=Path(args[-1]).stem
                return SimpleNamespace(returncode=0,stdout=reports()[key].encode('cp1252'),stderr=b'')
            with patch('footprint_holes.subprocess.run',side_effect=run) as command:
                data=read_pcb(board,extracta='extracta.exe')
                self.assertEqual(command.call_count,3)
            self.assertEqual(board.read_bytes(),b'original board')
            self.assertEqual(data['board_name'],board.name)
            reference=Path(folder)/'components.json';reference.write_text(json.dumps(data))
            self.assertEqual(read_pcb(reference),data)

    def test_custom_rules_require_explicit_supported_anchor_and_diameter(self):
        rules={'TEST':dict(hole_type='custom',diameter_mm='6,2',anchor='pin',value='2',side='TOP')}
        self.assertEqual(validate_rules(rules)['TEST']['diameter_mm'],6.2)
        for key,value in [('anchor','guess'),('diameter_mm','nan'),('value',''),('side','unknown')]:
            bad=copy.deepcopy(rules);bad['TEST'][key]=value
            with self.assertRaises(ValueError):validate_rules(bad)


class FootprintDocumentTests(unittest.TestCase):
    def document(self):
        d=PanelDocument(layers=[Reference('OUTLINE.art',BOARD)],elements=[Element('text',30,120,3,'FX')])
        d.center_pcb();return d

    def test_apply_is_idempotent_keeps_manual_objects_and_roundtrips_portably(self):
        d=self.document();manual=copy.deepcopy(d.elements)
        count,collisions,_=d.apply_footprint_holes(sample(),DEFAULT_RULES,['P1','J1','S1'])
        self.assertEqual((count,collisions),(3,[]))
        self.assertEqual(d.elements[:1],manual)
        pot=next(e for e in d.elements if e.source_ref=='P1')
        self.assertEqual((pot.x,pot.y),(2.5+d.pcb_dx,7+d.pcb_dy))
        before=copy.deepcopy(d.to_dict())
        d.apply_footprint_holes(sample(),DEFAULT_RULES,['P1','J1','S1'])
        self.assertEqual(d.to_dict(),before)
        self.assertEqual(PanelDocument.from_dict(d.to_dict()).to_dict(),before)
        with tempfile.TemporaryDirectory() as tmp:
            d.save(Path(tmp)/'p.panel.json')
            self.assertEqual(PanelDocument.load(Path(tmp)/'p.panel.json').to_dict(),before)

    def test_manual_hole_at_same_centre_is_not_deleted_or_duplicated(self):
        d=self.document();manual=Element('hole',10+d.pcb_dx,6.48+d.pcb_dy,6.2,'Manual input','jack')
        d.elements.append(manual)
        count,collisions,_=d.apply_footprint_holes(sample(),DEFAULT_RULES,['J1'])
        self.assertEqual((count,collisions),(0,['J1']))
        self.assertIs(d.elements[-1],manual)

    def test_recentering_moves_linked_holes_only_and_invalid_import_is_atomic(self):
        d=self.document();d.apply_footprint_holes(sample(),DEFAULT_RULES,['P1'])
        hole=d.elements[-1];manual=Element('hole',10,10,6,'Manual','jack');d.elements.append(manual)
        d.hp=20;d.center_pcb()
        self.assertEqual((hole.x,hole.y),(hole.board_x+d.pcb_dx,hole.board_y+d.pcb_dy))
        self.assertEqual((manual.x,manual.y),(10,10))
        before=copy.deepcopy(d.to_dict())
        with self.assertRaises(ValueError):d.apply_footprint_holes(sample(),DEFAULT_RULES,['NO_SUCH_REF'])
        self.assertEqual(d.to_dict(),before)

    def test_nearby_manual_hole_requires_review_instead_of_overlapping_drills(self):
        d=self.document();d.elements.append(Element('hole',10.5+d.pcb_dx,6.48+d.pcb_dy,6,'Hand placed','jack'))
        before=copy.deepcopy(d.to_dict())
        with self.assertRaisesRegex(ValueError,'solapa'):
            d.apply_footprint_holes(sample(),DEFAULT_RULES,['J1'])
        self.assertEqual(d.to_dict(),before)


class FootprintWindowTests(unittest.TestCase):
    def test_rule_library_export_import_can_be_reused_and_cancel_keeps_project(self):
        from panel_editor import PanelEditor
        from footprint_dialog import FootprintDialog
        app=PanelEditor();app.withdraw()
        try:
            app.document=PanelDocument(layers=[Reference('OUTLINE.art',BOARD)],component_data=sample())
            app.document.center_pcb();app.refresh();before=copy.deepcopy(app.document.to_dict())
            dialog=FootprintDialog(app)
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'my-library.json'
                with patch('footprint_dialog.filedialog.asksaveasfilename',return_value=str(path)):
                    dialog.export_rules()
                dialog.rules={}
                with patch('footprint_dialog.filedialog.askopenfilename',return_value=str(path)):
                    dialog.import_rules()
                self.assertEqual(dialog.rules,DEFAULT_RULES)
            dialog.close();self.assertEqual(app.document.to_dict(),before)
        finally:app.destroy()

    def test_preview_toggle_cancel_apply_and_undo_do_not_damage_existing_layout(self):
        from panel_editor import PanelEditor
        from footprint_dialog import FootprintDialog
        app=PanelEditor();app.withdraw()
        try:
            app.document=PanelDocument(layers=[Reference('OUTLINE.art',BOARD)],component_data=sample())
            app.document.center_pcb();app.refresh()
            before=copy.deepcopy(app.document.to_dict())
            dialog=FootprintDialog(app)
            self.assertEqual(len(dialog.items),3)
            self.assertEqual(dialog.checked,{'P1','J1','S1'})
            self.assertEqual(len(app.canvas.find_withtag('footprint_preview')),3)
            dialog.table.selection_set('J1');dialog.toggle()
            self.assertNotIn('J1',dialog.checked)
            dialog.close()
            self.assertEqual(app.document.to_dict(),before)
            self.assertFalse(app.canvas.find_withtag('footprint_preview'))
            dialog=FootprintDialog(app);dialog.apply()
            self.assertEqual(len([e for e in app.document.elements if e.source_ref]),3)
            app.undo();self.assertEqual(app.document.to_dict(),before)
            app.redo();self.assertEqual(len(app.document.elements),3)
        finally:app.destroy()

    def test_drag_and_numeric_edits_keep_link_to_pcb_and_follow_its_movement(self):
        from panel_editor import PanelEditor
        app=PanelEditor();app.geometry('1100x800');app.update();app.update();app.withdraw()
        try:
            app.document=PanelDocument(layers=[Reference('OUTLINE.art',BOARD)])
            app.document.center_pcb();app.document.apply_footprint_holes(sample(),DEFAULT_RULES,['P1'])
            app.select(0);app.x.set('40');app.y.set('80');app.size.set('7.2');app.apply_selection()
            h=app.document.elements[0]
            self.assertEqual(h.source_ref,'P1');self.assertEqual(h.board_x,40-app.document.pcb_dx)
            app.mode.set('select');app.snap.set('0');app.draw()
            event=lambda x,y:SimpleNamespace(x=app.to_canvas(x,y)[0],y=app.to_canvas(x,y)[1])
            app.press(event(40,80));app.motion(event(45,84));app.release(event(45,84))
            self.assertAlmostEqual(h.board_x,45-app.document.pcb_dx)
            relative=(h.board_x,h.board_y)
            app.document.hp=20;app.document.center_pcb()
            self.assertAlmostEqual(h.x,relative[0]+app.document.pcb_dx)
            self.assertEqual(h.size,7.2)
        finally:app.destroy()


class RefdesLabelTests(unittest.TestCase):
    def document(self):
        d=PanelDocument(layers=[Reference('OUTLINE.art',BOARD)],component_data=sample())
        d.center_pcb()
        return d

    def test_only_components_with_registered_holes_get_labels(self):
        from panel_fonts import element_mask,PIXEL_MM
        d=self.document();labels,_=d.refdes_labels(sample(),DEFAULT_RULES)
        self.assertEqual([e.text for e in labels],['P1','J1','S1'])
        pot=labels[0]
        self.assertEqual(pot.x,2.5+d.pcb_dx)
        self.assertAlmostEqual(pot.y,7+d.pcb_dy+8.128/2+1+element_mask(pot).height*PIXEL_MM/2)
        below,_=d.refdes_labels(sample(),DEFAULT_RULES,size=3,gap=2,position='below')
        self.assertAlmostEqual(below[0].y,7+d.pcb_dy-8.128/2-2-element_mask(below[0]).height*PIXEL_MM/2)

    def test_label_uses_actual_moved_hole_and_its_edited_diameter(self):
        from panel_fonts import element_mask,PIXEL_MM
        d=self.document();d.apply_footprint_holes(sample(),DEFAULT_RULES,['P1'])
        h=d.elements[0];h.x+=2;h.y+=3;h.size=8
        labels,_=d.refdes_labels(sample(),DEFAULT_RULES)
        self.assertEqual((labels[0].x,labels[0].y),(h.x,h.y+4+1+element_mask(labels[0]).height*PIXEL_MM/2))

    def test_repeat_preserves_edited_labels_and_hole_regeneration_keeps_text(self):
        d=self.document();d.apply_refdes_labels(sample(),DEFAULT_RULES,['P1','J1'])
        label=d.elements[0];label.text='Manual name';label.x+=2;label.board_x+=2
        count,preserved,_=d.apply_refdes_labels(sample(),DEFAULT_RULES,['P1','J1'])
        self.assertEqual((count,set(preserved)),(0,{'P1','J1'}))
        d.apply_footprint_holes(sample(),DEFAULT_RULES,['P1','J1'])
        self.assertEqual(len(d.elements),4)
        self.assertIn(label,d.elements)
        before=[(e.text,e.x,e.y) for e in d.elements if e.kind=='text']
        d.apply_footprint_holes(sample(),DEFAULT_RULES,['P1'])
        self.assertEqual([(e.text,e.x,e.y) for e in d.elements if e.kind=='text'],before)

    def test_manual_refdes_is_not_duplicated_and_roundtrip_follows_pcb(self):
        d=self.document();manual=Element('text',10,10,2.5,' j1 ');d.elements.append(manual)
        count,preserved,_=d.apply_refdes_labels(sample(),DEFAULT_RULES,['P1','J1'])
        self.assertEqual((count,preserved),(1,['J1']))
        d=PanelDocument.from_dict(d.to_dict());label=d.elements[1];old=label.x
        d.hp+=4;d.center_pcb()
        self.assertAlmostEqual(label.x,old+4*5.08/2)
        self.assertEqual((d.elements[0].x,d.elements[0].y),(10,10))
        self.assertIn('P1',d.svg())

    def test_invalid_label_import_is_atomic(self):
        d=self.document();before=d.to_dict()
        for options in [dict(size=0),dict(position='diagonal'),dict(gap=-1),dict(gap=50)]:
            with self.assertRaises(ValueError):d.apply_refdes_labels(sample(),DEFAULT_RULES,['S1'],**options)
            self.assertEqual(d.to_dict(),before)
        with self.assertRaises(ValueError):d.apply_refdes_labels(sample(),DEFAULT_RULES,['R1'])
        self.assertEqual(d.to_dict(),before)

    def test_text_preview_cancel_apply_undo_and_clear(self):
        from panel_editor import PanelEditor
        from footprint_dialog import FootprintDialog
        app=PanelEditor();app.withdraw()
        try:
            app.document=self.document();app.refresh();before=app.document.to_dict()
            dialog=FootprintDialog(app,mode='texts')
            self.assertEqual(dialog.checked,{'P1','J1','S1'})
            self.assertEqual({app.canvas.type(i) for i in app.canvas.find_withtag('footprint_preview')},{'image'})
            dialog.close();self.assertEqual(app.document.to_dict(),before)
            dialog=FootprintDialog(app,mode='texts');dialog.text_gap.set('-1');dialog.refresh()
            self.assertFalse(dialog.checked)
            dialog.text_gap.set('1');dialog.refresh();dialog.apply()
            self.assertEqual(len(app.document.elements),3)
            app.undo();self.assertEqual(app.document.to_dict(),before)
            app.redo();self.assertEqual(len(app.document.elements),3)
            dialog=FootprintDialog(app,mode='texts');self.assertFalse(dialog.checked);dialog.close()
            saved=app.document.to_dict();app.clear_elements()
            self.assertFalse(app.document.elements);self.assertTrue(app.document.component_data)
            app.undo();self.assertEqual(app.document.to_dict(),saved)
        finally:app.destroy()

    def test_label_numeric_edit_and_drag_preserve_pcb_link(self):
        from panel_editor import PanelEditor
        app=PanelEditor();app.geometry('1100x800');app.update();app.update();app.withdraw()
        try:
            app.document=self.document();app.document.apply_refdes_labels(sample(),DEFAULT_RULES,['P1'])
            app.select(0);app.x.set('40');app.y.set('80');app.text.set('DRIVE');app.size.set('3');app.apply_selection()
            label=app.document.elements[0]
            app.mode.set('select');app.snap.set('0');app.draw()
            event=lambda x,y:SimpleNamespace(x=app.to_canvas(x,y)[0],y=app.to_canvas(x,y)[1])
            app.press(event(40,80));app.motion(event(45,84));app.release(event(45,84))
            self.assertAlmostEqual(label.board_x,45-app.document.pcb_dx)
            app.document.hp+=4;app.document.center_pcb()
            self.assertAlmostEqual(label.x,45+4*5.08/2)
            self.assertEqual(label.text,'DRIVE')
        finally:app.destroy()


if __name__=='__main__':unittest.main()
