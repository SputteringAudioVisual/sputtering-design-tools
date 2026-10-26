import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel_model import Element,PanelDocument,Reference
from panel_fonts import text_mask,element_mask,PIXEL_MM
from panel_gerber import package_files
from footprint_holes import DEFAULT_RULES,anchor_point,proposals,library_rules,save_shared_library,library_coverage,validate_rules
from test_footprint_holes import sample
from test_panel import BOARD


class PortableLibraryTests(unittest.TestCase):
    def test_named_mounts_double_pot_and_mirrored_pair(self):
        d=sample();pot=d['components'][0];pot['footprint']='RK09D1130C1B'
        for i,p in enumerate([p for p in pot['pins'] if not p['number']],1):p['number']='MH'+str(i)
        items,_=proposals(d,DEFAULT_RULES,d['outline_bounds_mm']);self.assertEqual((items[0]['x_mm'],items[0]['y_mm']),(2.5,7))
        for p in pot['pins']:p['x_mm'],p['y_mm']=30-p['y_mm'],-10-p['x_mm']
        pot['side']='BOTTOM';rules=copy.deepcopy(DEFAULT_RULES);rules['RK09D1130C1B']['side']='BOTH'
        items,_=proposals(d,rules,d['outline_bounds_mm']);self.assertEqual((items[0]['x_mm'],items[0]['y_mm']),(23,-12.5))
        pot['footprint']='SPTR_RK09_DOBLE'
        for p in pot['pins']:
            if p['number'].startswith('MH'):p['number']=''
        rules['SPTR_RK09_DOBLE']['side']='BOTH'
        items,_=proposals(d,rules,d['outline_bounds_mm']);self.assertEqual((items[0]['x_mm'],items[0]['y_mm']),(23,-12.5))

    def test_pin_pair_is_explicit_and_rejects_missing_or_duplicated_pin(self):
        pin=lambda n,x,y:dict(number=n,x_mm=x,y_mm=y,padstack='MECH')
        c=dict(pins=[pin('2',1,4),pin('5',7,4)])
        rule=DEFAULT_RULES['SPTR_DPDT'];self.assertEqual(anchor_point(c,rule),(4,4))
        self.assertTrue(rule['review_required'])
        for pins in [[pin('2',1,4)],[pin('2',1,4),pin('2',7,4)]]:
            c['pins']=pins
            with self.assertRaises(ValueError):anchor_point(c,rule)
        with self.assertRaises(ValueError):validate_rules({'A':dict(rule,value='2,2')})

    def test_shared_library_is_reused_but_does_not_mutate_existing_projects(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'common.json';first=library_rules(path)
            first['MY_PART']=dict(DEFAULT_RULES['SPTR_SPDT'],value='1')
            save_shared_library(first,path);second=library_rules(path)
            self.assertIn('MY_PART',second)
            second['MY_PART']['diameter_mm']=9
            self.assertNotEqual(library_rules(path)['MY_PART']['diameter_mm'],9)
            path.write_text('{bad',encoding='utf-8')
            with self.assertRaises(ValueError):library_rules(path)

    def test_coverage_exposes_unknown_and_ambiguous_footprints(self):
        d=sample();rows={r['footprint']:r for r in library_coverage(d,DEFAULT_RULES)}
        self.assertEqual(rows['RES']['ready'],0);self.assertIn('Sin regla',rows['RES']['problems'])
        d['components'][0]['pins']=[p for p in d['components'][0]['pins'] if p['number']]
        rows={r['footprint']:r for r in library_coverage(d,DEFAULT_RULES)}
        self.assertEqual(rows['SPTR_RK09_123']['ready'],0)

    def test_new_module_has_no_old_project_objects_or_reference_cache(self):
        from panel_editor import PanelEditor
        app=PanelEditor();app.withdraw()
        try:
            app.document=PanelDocument(layers=[Reference('OUTLINE.art',BOARD)],component_data=sample(),
                                       elements=[Element('text',10,20,3,'OLD MODULE')],footprint_rules=copy.deepcopy(DEFAULT_RULES))
            app.project_path='old.panel.json';app.dirty=True
            with patch.object(app,'confirm_discard',return_value=True):app.new_panel()
            self.assertIsNone(app.project_path);self.assertIsNone(app.document.component_data)
            self.assertFalse(app.document.elements);self.assertFalse(app.document.layers)
            self.assertFalse(app.document.footprint_rules);self.assertFalse(app.history)
        finally:app.destroy()

    def test_new_module_origin_translation_does_not_change_relative_hole_positions(self):
        d=sample();items,_=proposals(d,DEFAULT_RULES,d['outline_bounds_mm'])
        for c in d['components']:
            c['x_mm']+=1000;c['y_mm']-=500
            for p in c['pins']:p['x_mm']+=1000;p['y_mm']-=500
        d['outline_bounds_mm']=[980,-550,1040,-450]
        other,_=proposals(d,DEFAULT_RULES,d['outline_bounds_mm'])
        for first,second in zip(other,items):
            self.assertAlmostEqual(first['x_mm']-1000,second['x_mm'])
            self.assertAlmostEqual(first['y_mm']+500,second['y_mm'])


class TextOptionsTests(unittest.TestCase):
    def test_rotation_width_tracking_multiline_and_alignment(self):
        base=text_mask('AB8',4);rot=text_mask('AB8',4,angle=90)
        self.assertEqual(rot.size,(base.height,base.width))
        self.assertGreater(text_mask('AB8',4,width_scale=1.5).width,base.width)
        self.assertGreater(text_mask('AB8',4,tracking=.4).width,base.width)
        center=text_mask('LONG\nI',4,align='center');left=text_mask('LONG\nI',4,align='left');right=text_mask('LONG\nI',4,align='right')
        self.assertGreater(center.height,base.height)
        self.assertNotEqual(left.tobytes(),right.tobytes())
        self.assertNotEqual(center.tobytes(),right.tobytes())
        with self.assertRaises(ValueError):text_mask('A\n'*9,4)
        with self.assertRaises(ValueError):text_mask('W'*400,1,angle=45)
        with self.assertRaises(ValueError):Element('text',30,70,4,'A',width_scale=0)

    def test_transformed_text_roundtrip_svg_and_gerber_have_identical_ink_area(self):
        e=Element('text',40,70,4,'A8\nBC',angle=37,width_scale=1.3,tracking=.2,line_spacing=1.5,align='right',ink_gain=.1)
        d=PanelDocument(hp=20,elements=[e]);restored=PanelDocument.from_dict(d.to_dict())
        self.assertEqual(restored.to_dict(),d.to_dict());self.assertIn('rotate(-37)',d.svg())
        files,_,report=package_files(restored)
        from gerber_silkscreen_editor import GerberLayer
        layer=GerberLayer();layer.raw_lines=files['panel.GTO'].decode().splitlines(keepends=True);layer._parse()
        area=0
        for p in layer.drawables:
            if p['type']=='region':
                xs,ys=zip(*p['path']);area+=(max(xs)-min(xs))*(max(ys)-min(ys))
        self.assertAlmostEqual(area,sum(bool(v) for v in element_mask(e).tobytes())*PIXEL_MM**2,places=5)
        self.assertEqual(report['text_styles'][0]['angle'],37)
        self.assertEqual(report['ink_expansion_mm'],.1)

    def test_refdes_formatting_sides_offsets_and_preservation(self):
        d=PanelDocument(layers=[Reference('OUTLINE.art',BOARD)]);d.center_pcb()
        labels,_=d.refdes_labels(sample(),DEFAULT_RULES,position='left',prefix='[',suffix=']',remove_numbers=True,dx=1,dy=2)
        e=labels[0];self.assertEqual(e.text,'[P]')
        self.assertAlmostEqual(e.x,2.5+d.pcb_dx-8.128/2-1-element_mask(e).width*PIXEL_MM/2+1)
        self.assertAlmostEqual(e.y,7+d.pcb_dy+2)
        d.apply_refdes_labels(sample(),DEFAULT_RULES,['P1'],prefix='CV ')
        original=copy.deepcopy(d.to_dict());d.apply_refdes_labels(sample(),DEFAULT_RULES,['P1'],prefix='CHANGED ')
        self.assertEqual(original,d.to_dict())
        other=PanelDocument(layers=[Reference('OUTLINE.art',BOARD)],elements=[Element('text',1,1,3,'P')]);other.center_pcb()
        count,_,_=other.apply_refdes_labels(sample(),DEFAULT_RULES,['P1'],remove_numbers=True)
        self.assertEqual(count,1)

    def test_bulk_style_duplicate_and_multiline_editor_are_undoable(self):
        from panel_editor import PanelEditor
        app=PanelEditor();app.withdraw()
        try:
            app.document=PanelDocument(elements=[Element('text',20,50,3,'OLD'),Element('hole',10,10,3)])
            app.select(0);app.text.set('LINE 1\nLINE 2');self.assertEqual(app.text_box.get('1.0','end-1c'),'LINE 1\nLINE 2')
            app.text_angle.set('90');app.text_width.set('120');app.text_tracking.set('0.2');app.apply_selection()
            self.assertEqual(app.document.elements[0].angle,90)
            self.assertEqual(app.document.elements[0].width_scale,1.2)
            before=app.document.to_dict();app.duplicate_selected();self.assertEqual(len(app.document.elements),3)
            self.assertFalse(app.document.elements[-1].source_ref)
            app.undo();self.assertEqual(app.document.to_dict(),before)
            app.text_angle.set('180');app.style_all_texts()
            self.assertEqual(app.document.elements[0].angle,180)
            self.assertEqual((app.document.elements[1].x,app.document.elements[1].y),(10,10))
            app.undo();self.assertEqual(app.document.to_dict(),before)
        finally:app.destroy()

    def test_review_required_rules_are_not_selected_by_default_or_mark_all(self):
        from panel_editor import PanelEditor
        from footprint_dialog import FootprintDialog
        app=PanelEditor();app.withdraw()
        try:
            data=sample();data['components'][2]['footprint']='SPTR_MINISPDT'
            app.document=PanelDocument(layers=[Reference('OUTLINE.art',BOARD)],component_data=data);app.document.center_pcb();app.refresh()
            with patch('footprint_dialog.library_rules',return_value=copy.deepcopy(DEFAULT_RULES)):
                dialog=FootprintDialog(app)
            self.assertNotIn('S1',dialog.checked);dialog.mark_all(True);self.assertNotIn('S1',dialog.checked)
            dialog.table.selection_set('S1');dialog.toggle();self.assertIn('S1',dialog.checked);dialog.close()
        finally:app.destroy()


if __name__=='__main__':unittest.main()
