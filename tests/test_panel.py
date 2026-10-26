import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from panel_model import PanelDocument, Reference, Element, HOLE_PRESETS, geometry_bounds, load_references


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

    def test_rack_replaces_legacy_patterns_and_keeps_control_holes_and_text(self):
        d = PanelDocument(hp=28)
        d.elements = [Element('hole',x,y,3.2,'Tornillo rack')
                      for x in (7.5,134.5,124.34) for y in (3,125.5)]
        controls = [Element('hole',7.5,3,3.2,'Custom M3','custom'),
                    Element('hole',50,60,6,'Entrada','jack'),Element('text',65,120,3,'DISTORTION')]
        d.elements += controls
        d.hp = 26
        d.mounting_holes()
        mounts = [e for e in d.elements if e.is_rack_mount]
        self.assertEqual(len(mounts),4)
        self.assertEqual(sorted({e.x for e in mounts}),[7.5,124.34])
        self.assertTrue(all(e in d.elements for e in controls))
        before=d.to_dict()
        d.mounting_holes()
        self.assertEqual(before,d.to_dict())
        d.hp=8; d.mounting_holes()
        self.assertEqual(len([e for e in d.elements if e.is_rack_mount]),2)
        self.assertTrue(all(e in d.elements for e in controls))

    def test_typed_holes_roundtrip_and_export_actual_diameter(self):
        d=PanelDocument(elements=[Element('hole',10+i*12,30,p[1],p[2],key)
                                  for i,(key,p) in enumerate(HOLE_PRESETS.items()) if p[1] is not None])
        restored=PanelDocument.from_dict(d.to_dict())
        self.assertEqual(restored.to_dict(),d.to_dict())
        circles=ET.fromstring(restored.svg()).findall('.//{http://www.w3.org/2000/svg}circle')
        self.assertEqual([float(e.attrib['r'])*2 for e in circles],[8.128,6.1,6.5,6.5,3.2])
        legacy=Element('hole',10,20,6.5,'Legacy')
        self.assertEqual(legacy.hole_type,'')
        with self.assertRaises(ValueError): Element('hole',10,20,6,'Jack','unsupported')

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
    def test_drag_existing_objects_while_placement_tool_remains_active(self):
        from panel_editor import PanelEditor
        from types import SimpleNamespace
        app=PanelEditor();app.geometry('1100x800');app.update();app.update();app.withdraw()
        try:
            app.snap.set('0')
            app.document=PanelDocument(elements=[Element('hole',30,40,7,'GAIN','potentiometer'),
                                                 Element('text',60,70,3,'DRIVE')])
            app.zoom=1.8;app.pan=[42,-27]
            self.assertGreater(app.transform()[0],1)
            for tool,index in [('hole',0),('text',1)]:
                with self.subTest(tool=tool):
                    app.mode.set(tool);app.mode_changed();app.dirty=False
                    app.history.clear();app.future.clear();app.draw()
                    obj=app.document.elements[index];origin=(obj.x,obj.y)
                    # Press away from the centre: dragging must preserve the
                    # grab offset rather than snapping the object to the mouse.
                    sx,sy=origin[0]+.4,origin[1]+.3
                    event=lambda x,y:SimpleNamespace(x=app.to_canvas(x,y)[0],y=app.to_canvas(x,y)[1])
                    app.press(event(sx,sy))
                    self.assertEqual(app.selected,index)
                    self.assertFalse(app.history)
                    with patch.object(app,'draw',wraps=app.draw) as repaint:
                        for dx,dy in [(2,3),(4,5),(8,9)]:
                            app.motion(event(sx+dx,sy+dy))
                        repaint.assert_not_called()
                    app.release(event(sx+8,sy+9))
                    self.assertEqual(len(app.document.elements),2)
                    self.assertAlmostEqual(obj.x,origin[0]+8)
                    self.assertAlmostEqual(obj.y,origin[1]+9)
                    self.assertAlmostEqual(float(app.x.get()),obj.x)
                    self.assertAlmostEqual(float(app.y.get()),obj.y)
                    self.assertEqual(len(app.history),1)
                    self.assertTrue(app.dirty)
                    app.undo()
                    self.assertEqual((app.document.elements[index].x,app.document.elements[index].y),origin)
                    app.redo()
                    self.assertAlmostEqual(app.document.elements[index].x,origin[0]+8)
        finally:app.destroy()

    def test_canvas_bindings_place_drag_and_click_without_creating_duplicates(self):
        from panel_editor import PanelEditor
        app=PanelEditor();app.geometry('1100x800');app.update();app.update()
        try:
            app.mode.set('hole');app.mode_changed();app.snap.set('0.5')
            self.assertTrue(app.canvas.winfo_viewable())
            def mouse(sequence,x,y):
                px,py=app.to_canvas(x,y)
                app.canvas.event_generate(sequence,x=round(px),y=round(py))
                app.update_idletasks()
            mouse('<ButtonPress-1>',25,30)
            mouse('<ButtonRelease-1>',25,30)
            obj=app.document.elements[0]
            self.assertAlmostEqual(float(app.x.get()),obj.x)
            self.assertAlmostEqual(float(app.y.get()),obj.y)
            app.dirty=False;app.history.clear()
            app.future=[PanelDocument()]
            mouse('<ButtonPress-1>',obj.x,obj.y)
            mouse('<ButtonRelease-1>',obj.x,obj.y)
            self.assertEqual(len(app.document.elements),1)
            self.assertFalse(app.history)
            self.assertFalse(app.dirty)
            self.assertEqual(len(app.future),1)
            mouse('<ButtonPress-1>',obj.x,obj.y)
            mouse('<B1-Motion>',40,45)
            mouse('<ButtonRelease-1>',40,45)
            self.assertEqual(len(app.document.elements),1)
            self.assertAlmostEqual(obj.x,40,delta=.5)
            self.assertAlmostEqual(obj.y,45,delta=.5)
            app.mode.set('text');app.mode_changed()
            mouse('<ButtonPress-1>',70,80)
            mouse('<B1-Motion>',75,85)
            mouse('<ButtonRelease-1>',75,85)
            self.assertEqual(len(app.document.elements),2)
            self.assertEqual(app.document.elements[-1].kind,'text')
            app.undo()
            self.assertEqual(len(app.document.elements),1)
        finally:app.destroy()

    def test_explicit_pcb_move_does_not_move_controls_and_is_undoable(self):
        from panel_editor import PanelEditor
        from types import SimpleNamespace
        app=PanelEditor();app.geometry('1100x800');app.update();app.update();app.withdraw()
        try:
            app.document=PanelDocument(layers=[Reference('outline.gbr',BOARD)],
                                       elements=[Element('hole',30,40,7,'GAIN','potentiometer')])
            app.document.center_pcb();before=(app.document.pcb_dx,app.document.pcb_dy)
            app.mode.set('pcb');app.mode_changed();app.snap.set('0')
            event=lambda x,y:SimpleNamespace(x=app.to_canvas(x,y)[0],y=app.to_canvas(x,y)[1])
            app.press(event(30,40));app.motion(event(35,46));app.release(event(35,46))
            self.assertEqual((app.document.elements[0].x,app.document.elements[0].y),(30,40))
            self.assertAlmostEqual(app.document.pcb_dx,before[0]+5)
            app.undo()
            self.assertEqual((app.document.pcb_dx,app.document.pcb_dy),before)
        finally:app.destroy()

    def test_panel_resize_replaces_mounts_in_one_undo_step(self):
        from panel_editor import PanelEditor
        app=PanelEditor();app.withdraw()
        try:
            app.document=PanelDocument(hp=28,elements=[Element('hole',60,60,6,'IN','jack')])
            app.document.mounting_holes();before=app.document.to_dict()
            app.hp.set('26');app.apply_panel()
            mounts=[e for e in app.document.elements if e.is_rack_mount]
            self.assertEqual(len(mounts),4)
            self.assertEqual(max(e.x for e in mounts),124.34)
            app.add_mounts()
            self.assertEqual(len([e for e in app.document.elements if e.is_rack_mount]),4)
            app.undo();app.undo()
            self.assertEqual(app.document.to_dict(),before)
            app.redo()
            self.assertEqual(app.document.hp,26)
            self.assertEqual(len([e for e in app.document.elements if e.is_rack_mount]),4)
        finally: app.destroy()

    def test_preset_palette_prepares_new_holes_and_keeps_manual_edits(self):
        from panel_editor import PanelEditor
        app=PanelEditor();app.withdraw()
        try:
            self.assertEqual(str(app.hole_combo.cget('state')),'readonly')
            for key in ('potentiometer','jack','spdt','dpdt','rack'):
                with self.subTest(kind=key):
                    label,diameter,name=HOLE_PRESETS[key]
                    app.hole_preset.set(label);app.choose_hole_preset()
                    self.assertEqual(app.mode.get(),'hole')
                    self.assertEqual(float(app.size.get()),diameter)
                    app.add_at(20,30)
                    obj=app.document.elements[-1]
                    self.assertEqual((obj.size,obj.hole_type,obj.text),(diameter,key,name))
            previous=app.document.to_dict()
            app.select(1)
            app.hole_preset.set(HOLE_PRESETS['potentiometer'][0]);app.choose_hole_preset()
            self.assertIsNone(app.selected)
            self.assertEqual(app.document.to_dict(),previous)
            app.size.set('7,2');app.add_at(40,50)
            app.select(len(app.document.elements)-1)
            self.assertEqual(float(app.size.get()),7.2)
            self.assertEqual(app.hole_preset.get(),HOLE_PRESETS['potentiometer'][0])
            app.text.set('Drive');app.size.set('7,3');app.apply_selection()
            self.assertEqual(app.document.elements[-1].hole_type,'potentiometer')
            app.undo();self.assertEqual(app.document.elements[-1].size,7.2)
            app.select(len(app.document.elements)-1)
            app.hole_preset.set(HOLE_PRESETS['custom'][0]);app.choose_hole_preset()
            self.assertEqual(float(app.size.get()),7.2)
            app.mode.set('text');app.mode_changed();app.add_at(45,60)
            self.assertEqual(app.document.elements[-1].hole_type,'')
        finally: app.destroy()

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
