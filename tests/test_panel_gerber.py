import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel_model import PanelDocument, Element, Reference, geometry_bounds
from panel_gerber import package_files, export_panel
from panel_fonts import FONTS, text_mask, ink_runs, PIXEL_MM
from drill import DrillLayer


class PanelManufacturingTests(unittest.TestCase):
    def document(self):
        return PanelDocument(hp=10,elements=[Element('hole',10,10,8.128,'Pot','potentiometer'),
            Element('hole',30,10,6.1,'Jack','jack'),Element('text',25,70,4,'AOB8')])

    def test_exact_profile_npth_and_reference_layers_are_excluded(self):
        d=self.document();d.layers=[Reference('SHOULD_NOT_EXPORT.art','%FSLAX36Y36*%\n%MOMM*%\nM02*\n')]
        files,proof,report=package_files(d)
        self.assertEqual(len(files),8);self.assertFalse(any('SHOULD' in n for n in files))
        profile=Reference('panel.GKO',files['panel.GKO'].decode())
        for actual,expected in zip(geometry_bounds(profile.layer,outline=True),(0,0,d.width,128.5)):
            self.assertAlmostEqual(actual,expected,places=6)
        drill=DrillLayer(files['panel-NPTH.drl'].decode())
        self.assertEqual([(h['x'],h['y'],h['sx']) for h in drill.drawables],[(30,10,6.1),(10,10,8.128)])
        self.assertIn(b'TYPE=NON_PLATED',files['panel-NPTH.drl'])
        self.assertEqual(report['hole_count'],2);self.assertIn('fill="white"',proof)

    def test_silk_geometry_has_same_area_and_bounds_as_shared_mask(self):
        d=self.document();files,_,_=package_files(d)
        silk=Reference('panel.GTO',files['panel.GTO'].decode())
        mask=text_mask('AOB8',4);expected=sum(bool(v) for v in mask.tobytes())*PIXEL_MM**2
        area=0
        for p in silk.layer.drawables:
            if p['type']!='region':continue
            xs,ys=zip(*p['path']);area+=(max(xs)-min(xs))*(max(ys)-min(ys))
        self.assertAlmostEqual(area,expected,places=6)
        class Regions:drawables=[p for p in silk.layer.drawables if p['type']=='region']
        bounds=geometry_bounds(Regions())
        self.assertAlmostEqual((bounds[0]+bounds[2])/2,25)
        self.assertAlmostEqual((bounds[1]+bounds[3])/2,70)
        self.assertTrue(any(len(list(ink_runs(d.elements[-1]))) for _ in [0]))

    def test_copper_keeps_clearances_and_masks_have_no_openings(self):
        files,_,_=package_files(self.document())
        for side in ['GTL','GBL']:
            copper=Reference('panel.'+side,files['panel.'+side].decode()).layer.drawables
            self.assertEqual(len([p for p in copper if p['type']=='region']),1)
            flashes=[p for p in copper if p['type']=='flash']
            self.assertTrue(all(p['polarity']=='clear' for p in flashes))
            for actual,expected in zip(sorted(p['sx'] for p in flashes),[6.7,8.728]):self.assertAlmostEqual(actual,expected)
        for side in ['GTS','GBS','GBO']:
            self.assertFalse(Reference('panel.'+side,files['panel.'+side].decode()).layer.drawables)
        files,_,_=package_files(self.document(),copper=False)
        self.assertFalse(Reference('panel.GTL',files['panel.GTL'].decode()).layer.drawables)

    def test_bad_placement_small_type_and_missing_font_fail_before_writing(self):
        for e in [Element('hole',0,0,3),Element('text',0,80,3,'EDGE'),
                  Element('text',10,10,3,'ON HOLE'),Element('text',25,70,.3,'SMALL')]:
            d=self.document();d.elements.append(e)
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):export_panel(d,folder)
                self.assertFalse(list(Path(folder).iterdir()))

    def test_all_fonts_keep_counters_and_survive_portable_roundtrip(self):
        masks=[]
        for style in FONTS:
            d=self.document();d.elements[-1].font=style
            restored=PanelDocument.from_dict(d.to_dict())
            self.assertEqual(restored.elements[-1].font,style)
            files,_,_=package_files(restored)
            self.assertIn(b'G36*',files['panel.GTO'])
            masks.append(text_mask('AOB8',4,style).tobytes())
            self.assertIn('font-family=',restored.svg())
        self.assertEqual(len(set(masks)),len(FONTS))

    def test_zip_numbering_integrity_and_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            one=export_panel(self.document(),folder,'test');two=export_panel(self.document(),folder,'test')
            self.assertNotEqual(one,two)
            report=json.loads(one.with_suffix('.json').read_text())
            with zipfile.ZipFile(one) as z:
                self.assertIsNone(z.testzip())
                for name,record in report['files'].items():self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(),record['sha256'])
            self.assertFalse(list(Path(folder).glob('.panel-export-*')))

    def test_ui_font_edit_and_zip_button_export_live_unsaved_document(self):
        from panel_editor import PanelEditor
        from tkinter import ttk
        app=PanelEditor();app.withdraw()
        try:
            app.document=self.document();app.select(2)
            app.font_choice.set(FONTS['gothic'][0]);app.apply_selection()
            self.assertEqual(app.document.elements[2].font,'gothic')
            app.mode.set('text');app.font_choice.set(FONTS['console'][0])
            app.size.set('4');app.text.set('LIVE');app.add_at(25,90)
            self.assertEqual(app.document.elements[-1].font,'console')
            for _ in range(3):app.draw()
            self.assertEqual(len(app._text_images),2)
            with tempfile.TemporaryDirectory() as folder,patch('panel_editor.filedialog.askdirectory',return_value=folder),\
                    patch('panel_editor.messagebox.showinfo'),patch('panel_editor.messagebox.showerror',side_effect=AssertionError):
                app.export_gerber()
                buttons=[w for w in app._descendants(app) if isinstance(w,ttk.Button) and w.cget('text')=='Generar Gerber y ZIP…']
                self.assertEqual(len(buttons),1);buttons[0].invoke()
                package=next(Path(folder).glob('*.zip'));report=json.loads(package.with_suffix('.json').read_text())
                self.assertEqual(set(report['fonts_sha256']),{'gothic','console'})
        finally:app.destroy()


if __name__=='__main__':unittest.main()
