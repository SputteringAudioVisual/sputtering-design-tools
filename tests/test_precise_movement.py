"""Precise group positioning without repainting or copying the PCB geometry."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel_editor import PanelEditor
from panel_model import PanelDocument,Element,Reference
from test_panel import BOARD


class PreciseMovementTests(unittest.TestCase):
    def setUp(self):
        doc=PanelDocument(layers=[Reference('outline.gko',BOARD)],pcb_dx=2,pcb_dy=3,elements=[
            Element('text',20,80,3,'GAIN',source_ref='P1',source_footprint='POT',board_x=18,board_y=77),
            Element('text',50,50,3,'OUT',source_ref='J1',source_footprint='JACK',board_x=48,board_y=47),
            Element('hole',20,70,8.128,'P1','potentiometer'),Element('text',40,110,4,'TITLE')])
        self.app=PanelEditor(document=doc);self.app.geometry('1100x800');self.app.update();self.app.update()
        self.app.snap.set('0')

    def tearDown(self):self.app.destroy()

    def test_exact_offsets_keep_holes_title_links_and_relative_spacing(self):
        a=self.app;a.select_pcb_labels()
        self.assertEqual(a.selection,{0,1})
        before=a.document.to_dict();geometry=a.document.layers[0].layer
        with patch.object(a,'draw',wraps=a.draw) as full,patch.object(a,'_draw_objects',wraps=a._draw_objects) as objects:
            a.move_selection(1.25,5.5)
            full.assert_not_called();objects.assert_not_called()
        self.assertEqual((a.document.elements[0].x,a.document.elements[0].y),(21.25,85.5))
        self.assertEqual((a.document.elements[1].x,a.document.elements[1].y),(51.25,55.5))
        self.assertEqual((a.document.elements[0].board_x,a.document.elements[0].board_y),(19.25,82.5))
        self.assertEqual(a.document.to_dict()['elements'][2:],before['elements'][2:])
        self.assertIs(a.history[-1].layers[0].layer,geometry)
        self.assertIsNot(a.history[-1].layers[0],a.document.layers[0])
        a.undo();self.assertEqual(a.document.to_dict(),before)
        a.redo();self.assertEqual(a.document.elements[1].y,55.5)

    def test_text_only_guard_and_alignment_reference(self):
        a=self.app;a.select(0);a.select(1,extend=True);a.select(2,extend=True)
        before=a.document.to_dict();a.move_selection(0,2)
        self.assertEqual(a.document.elements[2].y,70)
        a.select(1,extend=True);a.align_selection('y')
        self.assertEqual([a.document.elements[i].y for i in (0,1)],[52,52])
        a.undo();a.undo();self.assertEqual(a.document.to_dict(),before)
        a.select(2);a.move_text_only.set(False);a.move_selection(2,1)
        self.assertEqual((a.document.elements[2].x,a.document.elements[2].y),(22,71))

    def test_keyboard_step_modifiers_repeat_one_undo_and_text_editing(self):
        a=self.app;a.select_pcb_labels();a.canvas.focus_force();a.update()
        a.move_step.set('0,5')
        a.canvas.event_generate('<Right>');a.update()
        a.canvas.event_generate('<Right>');a.update()
        self.assertEqual(a.document.elements[0].x,21)
        self.assertEqual(len(a.history),1)
        a.canvas.event_generate('<KeyRelease-Right>');a.update()
        a.canvas.event_generate('<Shift-Up>');a.update()
        a.canvas.event_generate('<KeyRelease-Up>');a.update()
        self.assertEqual(a.document.elements[0].y,85)
        self.assertEqual(len(a.history),2)
        a.nudge(-1,0,SimpleNamespace(state=0x8))
        self.assertAlmostEqual(a.document.elements[0].x,20.95)
        a.text_box.focus_force();a.update();before=a.document.to_dict()
        self.assertIsNone(a.nudge(1,0,SimpleNamespace(state=0)))
        self.assertEqual(a.document.to_dict(),before)

    def test_selection_drag_release_and_undo_keep_background_items(self):
        a=self.app
        background=a.canvas.find_withtag('panel_background')
        images=tuple(a._text_images)
        def event(x,y,state=0):
            px,py=a.to_canvas(x,y);return SimpleNamespace(x=px,y=py,state=state)
        with patch.object(a,'draw',wraps=a.draw) as full,patch.object(a,'_draw_objects',wraps=a._draw_objects) as objects:
            a.select(0);a.select(1,extend=True)
            a.press(event(20,80));a.motion(event(25,83));a.release(event(25,83))
            full.assert_not_called();objects.assert_not_called()
        self.assertEqual(tuple(a._text_images),images)
        self.assertEqual(a.canvas.find_withtag('panel_background'),background)
        self.assertAlmostEqual(a.document.elements[1].x,55)
        self.assertAlmostEqual(a.document.elements[1].y,53)
        a.undo()
        self.assertEqual(a.canvas.find_withtag('panel_background'),background)
        a.document.layers[0].visible=False;a.draw()
        self.assertNotEqual(a.canvas.find_withtag('panel_background'),background)
        self.assertTrue(a.document.layers[0].visible is False)

    def test_escape_cancels_drag_and_invalid_offsets_are_atomic(self):
        a=self.app;a.select_pcb_labels();before=a.document.to_dict()
        px,py=a.to_canvas(20,80);a.press(SimpleNamespace(x=px,y=py,state=0))
        px,py=a.to_canvas(25,86);a.motion(SimpleNamespace(x=px,y=py,state=0))
        a.escape();self.assertEqual(a.document.to_dict(),before)
        a.select_pcb_labels()
        with self.assertRaises(ValueError):a.move_selection(float('nan'),2)
        self.assertEqual(a.document.to_dict(),before)

    def test_controls_fit_minimum_window_and_dialog_accepts_decimal_comma(self):
        from tkinter import ttk
        a=self.app;a.geometry('950x620');a.update();a.select_pcb_labels()
        for w in a._descendants(a):
            if isinstance(w,ttk.Button) and w.cget('text') in {'Mover…','Etiquetas PCB','Misma X','Misma Y'}:
                self.assertGreaterEqual(w.winfo_width(),w.winfo_reqwidth())
                self.assertLessEqual(w.winfo_x()+w.winfo_width(),w.master.winfo_width())
        a.move_dialog();a.update()
        dialog=next(w for w in a.winfo_children() if w.winfo_class()=='Toplevel')
        entries=[w for w in a._descendants(dialog) if isinstance(w,ttk.Entry)]
        entries[0].delete(0,'end');entries[0].insert(0,'1,5')
        entries[1].delete(0,'end');entries[1].insert(0,'4')
        apply=next(w for w in a._descendants(dialog) if isinstance(w,ttk.Button) and w.cget('text')=='Mover selección')
        apply.invoke()
        self.assertEqual((a.document.elements[0].x,a.document.elements[0].y),(21.5,84))
        self.assertEqual(a.document.elements[2].y,70)

    def test_pcb_reference_is_one_cached_image_with_clear_shapes_and_drill_centres(self):
        a=self.app
        content=('%FSLAX36Y36*%\n%MOMM*%\n%ADD10R,2X1*%\n%ADD11O,4X1*%\n%ADD12C,2*%\n'
                 'D10*\nX10000000Y20000000D03*\nD11*\nX20000000Y20000000D03*\n'
                 '%LPC*%\nD12*\nX30000000Y20000000D03*\nM02*')
        a.document.layers.append(Reference('pads.gtl',content))
        a.document.layers.append(Reference('holes.drl','M48\nMETRIC,TZ\nT01C1\n%\nT01\nX10.0Y35.0\nM30',coord_format=(3,6)))
        a.document.layers[0].layer.drawables*=1000
        a._background_key=None;a.draw();a.update_idletasks()
        self.assertEqual(len(a.canvas.find_withtag('pcb_reference')),1)
        self.assertLess(len(a.canvas.find_all()),150)
        raster=a._reference_raster()
        self.assertEqual(a.canvas.itemcget(a.canvas.find_withtag('panel_background')[0],'fill'),'#000000')
        for x,y,color in [(10,20,(91,133,149)),(20,20,(91,133,149)),(30,20,(0,0,0)),(10,35,(206,96,43))]:
            px,py=a.to_canvas(x+a.document.pcb_dx,y+a.document.pcb_dy)
            actual=raster.getpixel((round(px),round(py)))
            self.assertGreater(actual[3],180)
            self.assertLess(sum(abs(v-e) for v,e in zip(actual[:3],color)),100)
        cached=a._reference_image
        a.select_pcb_labels();a.move_selection(0,3)
        self.assertIs(a._reference_image,cached)


if __name__=='__main__':unittest.main()
