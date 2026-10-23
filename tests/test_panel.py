import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from panel_model import PanelDocument, Reference, Element, geometry_bounds, load_references


BOARD = '''G04 Synthetic reference board, not the distortion PCB*
%FSLAX36Y36*%
%MOMM*%
%ADD10C,0.1*%
G54D10*
X-20000000Y-50000000D02*
X40000000Y-50000000D01*
X40000000Y50000000*
X-20000000Y50000000*
X-20000000Y-50000000*
M02*
'''


class GeometryTests(unittest.TestCase):
    def test_conventional_blocks_modal_and_g54(self):
        ref = Reference('outline.gbr', BOARD)
        self.assertEqual(len(ref.layer.drawables), 4)
        self.assertEqual(ref.layer.used_apertures, {10})
        self.assertEqual(geometry_bounds(ref.layer, outline=True), (-20, -50, 40, 50))
        self.assertAlmostEqual(ref.layer.drawables[0]['width'], .1)

    def test_inches_convert_coordinates_and_apertures(self):
        ref = Reference('inch.gbr', '%FSLAX24Y24*%\n%MOIN*%\n%ADD10C,0.1*%\nD10*\nX10000Y0D03*\nM02*')
        item = ref.layer.drawables[0]
        self.assertAlmostEqual(item['x'], 25.4)
        self.assertAlmostEqual(item['sx'], 2.54)

    def test_centering_preserves_scale_and_all_layer_registration(self):
        d = PanelDocument(layers=[Reference('outline.gbr', BOARD), Reference('silk.gto', BOARD)])
        d.center_pcb()
        self.assertAlmostEqual(d.pcb_dx, d.width/2 - 10)
        self.assertAlmostEqual(d.pcb_dy, 64.25)
        self.assertEqual(d.layers[0].layer.drawables, d.layers[1].layer.drawables)
        self.assertEqual(d.reference_bounds(), (-20, -50, 40, 50))
        d.hp = 20
        d.center_pcb()
        self.assertEqual(d.reference_bounds(), (-20, -50, 40, 50))

    def test_bounds_include_aperture_and_arc_extrema(self):
        ref = Reference('arc.gbr', '%FSLAX36Y36*%\n%MOMM*%\n%ADD10C,2*%\nD10*\nX10000000Y0D02*\nG03X-10000000Y0I-10000000J0D01*\nM02*')
        self.assertAlmostEqual(ref.layer.bounds[3], 11, places=5)
        self.assertAlmostEqual(ref.layer.bounds[0], -11, places=5)

    def test_no_silent_unsupported_reference(self):
        for content in ['%AMTEST*1,1,1,0,0*%\n'+BOARD, '%FSTAX24Y24*%\n'+BOARD]:
            with self.assertRaises(ValueError):
                Reference('unsupported.gbr', content)

    def test_allegro_grouped_identity_transforms(self):
        identity = '%IR0*IPPOS*OFA0.00000B0.00000*MIA0B0*SFA1.00000B1.00000*%\n'
        self.assertEqual(len(Reference('allegro.art', identity+BOARD).layer.drawables), 4)
        for bad in ('OFA1B0', 'MIA1B0', 'SFA2B1', 'IR90', 'IPNEG'):
            with self.assertRaises(ValueError):
                Reference('bad.art', '%IR0*'+bad+'*%\n'+BOARD)

    def test_circular_aperture_hole_does_not_change_outer_diameter(self):
        ref = Reference('flash.gbr', '%FSLAX36Y36*%\n%MOMM*%\n%ADD10C,2X0.5*%\nD10*\nX0Y0D03*\nM02*')
        self.assertEqual(ref.layer.drawables[0]['sx'], 2)
        self.assertEqual(ref.layer.drawables[0]['sy'], 2)

    def test_validated_dimensions(self):
        self.assertEqual(PanelDocument(hp='12', gap='0,34').width, 60.62)
        for hp in ('nan', 'inf', '12.5', '-1', '0'):
            with self.assertRaises(ValueError):
                PanelDocument(hp=hp)
        with self.assertRaises(ValueError):
            Element('hole', 1, 2, -1)

    def test_mounting_grid_and_no_duplicate_holes(self):
        d = PanelDocument(hp=16)
        d.mounting_holes()
        self.assertEqual(len(d.elements), 4)
        self.assertAlmostEqual(d.elements[2].x-d.elements[0].x, 13*5.08)
        self.assertEqual([e.y for e in d.elements], [3, 125.5, 3, 125.5])
        d.mounting_holes()
        self.assertEqual(len(d.elements), 4)

    def test_outside_board_and_overlapping_holes_reported(self):
        d = PanelDocument(hp=4, layers=[Reference('outline.gbr', BOARD)])
        d.center_pcb()
        d.elements = [Element('hole', 10, 20, 6), Element('hole', 11, 20, 6)]
        self.assertEqual(len(d.problems()), 2)

    def test_portable_project_roundtrip(self):
        d = PanelDocument(layers=[Reference('outline.gbr', BOARD)],
                          elements=[Element('text', 20, 30, 3, 'GAIN & <TONE>')])
        d.center_pcb()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'test.panel.json'
            d.save(path)
            loaded = PanelDocument.load(path)
            self.assertEqual(d.to_dict(), loaded.to_dict())
        with self.assertRaises(ValueError):
            PanelDocument.from_dict({'schema': 'unknown'})

    def test_svg_physical_dimensions_holes_text_and_no_pcb(self):
        d = PanelDocument(layers=[Reference('outline.gbr', BOARD)],
                          elements=[Element('hole', 12, 20, 6.5), Element('text', 12, 30, 3, 'GAIN & <TONE>')])
        root = ET.fromstring(d.svg())
        ns = {'s': 'http://www.w3.org/2000/svg'}
        self.assertEqual(root.attrib['height'], '128.5mm')
        circle = root.find('.//s:circle', ns)
        self.assertEqual(circle.attrib, {'cx': '12', 'cy': '108.5', 'r': '3.25'})
        self.assertEqual(root.find('.//s:text', ns).text, 'GAIN & <TONE>')
        self.assertNotIn('Synthetic reference', d.svg())

    def test_zip_reads_without_extracting_and_retains_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'board.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('nested/outline.gbr', BOARD)
                archive.writestr('../other.txt', 'not a gerber')
                archive.writestr('bad.gto', 'no geometry')
            refs, errors = load_references([path])
            self.assertEqual(len(refs), 1)
            self.assertEqual(len(errors), 1)
            self.assertEqual(list(Path(tmp).iterdir()), [path])


class WorkspaceTests(unittest.TestCase):
    def test_edit_history_and_canvas_roundtrip(self):
        from panel_editor import PanelEditor
        app = PanelEditor()
        app.withdraw()
        try:
            app.document = PanelDocument(layers=[Reference('outline.gbr', BOARD)])
            app.document.center_pcb()
            app.mode.set('hole')
            app.add_at(15, 20)
            self.assertEqual(len(app.document.elements), 1)
            app.select(0)
            app.x.set('18,5')
            app.y.set('30')
            app.size.set('7')
            app.apply_selection()
            self.assertEqual(app.document.elements[0].x, 18.5)
            app.undo()
            self.assertEqual(app.document.elements[0].x, 15)
            app.redo()
            self.assertEqual(app.document.elements[0].size, 7)
            point = (19.5, 27.25)
            result = app.from_canvas(*app.to_canvas(*point))
            self.assertAlmostEqual(result[0], point[0])
            self.assertAlmostEqual(result[1], point[1])
            app.select(0)
            app.delete()
            self.assertFalse(app.document.elements)
            app.undo()
            self.assertEqual(len(app.document.elements), 1)
        finally:
            app.destroy()


if __name__ == '__main__':
    unittest.main()
