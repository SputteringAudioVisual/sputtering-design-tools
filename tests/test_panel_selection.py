"""Selection gestures, batch text changes and direct canvas editing."""
from dataclasses import asdict
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from panel_editor import PanelEditor
from panel_model import PanelDocument, Element


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.app = PanelEditor(document=PanelDocument(elements=[
            Element('text', 20, 90, 3, 'Drive\nÁcido', font='console', angle=15,
                    source_ref='P1', source_footprint='POT', board_x=18, board_y=87),
            Element('text', 50, 60, 3, 'Output'),
            Element('hole', 20, 30, 6.1, 'Jack', 'jack'),
            Element('text', 50, 20, 3, 'untouched')], pcb_dx=2, pcb_dy=3))
        self.app.geometry('1100x800')
        self.app.update()
        self.app.update()
        self.app.snap.set('0')

    def tearDown(self):
        self.app.cancel_inline()
        self.app.destroy()

    def event(self, x, y, state=0):
        px, py = self.app.to_canvas(x, y)
        return SimpleNamespace(x=px, y=py, state=state)

    def click(self, index, state=0):
        obj = self.app.document.elements[index]
        event = self.event(obj.x, obj.y, state)
        self.app.press(event)
        self.app.release(event)

    def test_control_shift_and_list_selection_stay_in_sync(self):
        a = self.app
        self.click(0); self.click(1, 4)
        self.assertEqual(a.selection, {0, 1})
        self.assertEqual(set(a.object_list.curselection()), {0, 1})
        self.click(0, 4)
        self.assertEqual(a.selection, {1})
        self.click(2, 1)
        self.assertEqual(a.selection, {1, 2})
        a.object_list.selection_clear(0, 'end')
        a.object_list.selection_set(0); a.object_list.selection_set(3)
        a.object_list.activate(3); a.select_list()
        self.assertEqual(a.selection, {0, 3})
        self.assertEqual(a.selected, 3)
        a.update()
        self.assertEqual(a.selection, {0, 3})
        self.assertFalse(a.history)
        a.object_list.selection_anchor(3); a.refresh()
        self.assertEqual(a.object_list.index('anchor'), 3)

    def test_rectangle_selects_group_and_drag_keeps_spacing_and_links(self):
        a = self.app
        a.press(self.event(10, 100)); a.motion(self.event(60, 50)); a.release(self.event(60, 50))
        self.assertEqual(a.selection, {0, 1})
        before = a.document.to_dict()
        a.press(self.event(20, 90))
        with patch.object(a, 'draw', wraps=a.draw) as repaint:
            a.motion(self.event(25, 93)); a.motion(self.event(27, 95))
            repaint.assert_not_called()
        a.release(self.event(27, 95))
        for obj, expected in zip(a.document.elements[:2], [(27, 95), (57, 65)]):
            self.assertAlmostEqual(obj.x, expected[0]); self.assertAlmostEqual(obj.y, expected[1])
        self.assertAlmostEqual(a.document.elements[0].board_x, 25)
        self.assertAlmostEqual(a.document.elements[0].board_y, 92)
        self.assertEqual((a.document.elements[2].x, a.document.elements[2].y), (20, 30))
        self.assertEqual(len(a.history), 1)
        a.undo(); self.assertEqual(a.document.to_dict(), before)
        a.redo(); self.assertAlmostEqual(a.document.elements[1].x, 57)

    def test_case_change_is_atomic_selected_text_only_and_undoable(self):
        a = self.app
        a.select(0); a.select(1, extend=True); a.select(2, extend=True)
        before = a.document.to_dict()
        a.change_case(True)
        self.assertEqual([e.text for e in a.document.elements], ['DRIVE\nÁCIDO', 'OUTPUT', 'Jack', 'untouched'])
        for i in (0, 1):
            old, new = dict(before['elements'][i]), asdict(a.document.elements[i])
            old.pop('text'); new.pop('text'); self.assertEqual(new, old)
        self.assertEqual(a.selection, {0, 1, 2})
        a.change_case(False)
        self.assertEqual(a.document.elements[0].text, 'drive\nácido')
        a.undo(); a.undo(); self.assertEqual(a.document.to_dict(), before)
        a.select(0); a.select(1, extend=True)
        with patch('panel_editor.element_mask', side_effect=[None, ValueError('glyph missing')]), \
             patch('panel_editor.messagebox.showerror'):
            a.change_case(True)
        self.assertEqual(a.document.to_dict(), before)
        self.assertFalse(a.history)

    def test_selected_style_duplicate_and_delete_use_one_undo_each(self):
        a = self.app
        a.select(0); a.select(1, extend=True); a.select(2, extend=True)
        before = a.document.to_dict()
        a.font_choice.set('Industrial · Bahnschrift'); a.size.set('4')
        a.style_selected_texts()
        self.assertEqual([e.font for e in a.document.elements], ['industrial', 'industrial', 'sans', 'sans'])
        self.assertEqual([e.text for e in a.document.elements[:2]], ['Drive\nÁcido', 'Output'])
        a.undo(); self.assertEqual(a.document.to_dict(), before)
        a.select(0); a.select(1, extend=True)
        a.duplicate_selected()
        self.assertEqual(len(a.document.elements), 6)
        self.assertEqual(a.selection, {4, 5})
        self.assertTrue(all(not e.source_ref for e in a.document.elements[4:]))
        self.assertEqual(a.document.elements[0].source_ref, 'P1')
        a.undo(); self.assertEqual(a.document.to_dict(), before)
        a.select(0); a.select(2, extend=True); a.delete()
        self.assertEqual([e.text for e in a.document.elements], ['Output', 'untouched'])
        a.undo(); self.assertEqual(a.document.to_dict(), before)

    def test_inline_commit_cancel_validation_resize_and_project_save(self):
        a = self.app
        before = a.document.to_dict()
        a.edit_text_at(self.event(20, 90))
        self.assertIsNotNone(a.inline_editor)
        editor = a.inline_editor['text']
        editor.delete('1.0', 'end'); editor.insert('1.0', 'Nuevo\nTEXTO')
        a.draw(); a.update_idletasks()
        self.assertTrue(editor.winfo_ismapped())
        a.cancel_inline()
        self.assertEqual(a.document.to_dict(), before)
        self.assertFalse(a.history)
        a.edit_text_at(self.event(20, 90))
        editor = a.inline_editor['text']
        editor.delete('1.0', 'end')
        with patch('panel_editor.messagebox.showerror'):
            self.assertFalse(a.commit_inline())
        self.assertIsNotNone(a.inline_editor)
        self.assertEqual(a.document.to_dict(), before)
        editor.insert('1.0', 'Nuevo\nTEXTO')
        with tempfile.TemporaryDirectory() as folder:
            a.project_path = str(Path(folder)/'inline.panel.json')
            self.assertTrue(a.save())
            self.assertEqual(PanelDocument.load(a.project_path).elements[0].text, 'Nuevo\nTEXTO')
        self.assertIsNone(a.inline_editor)
        old, new = dict(before['elements'][0]), asdict(a.document.elements[0])
        old.pop('text'); new.pop('text'); self.assertEqual(old, new)
        self.assertEqual(len(a.history), 1)
        a.undo(); self.assertEqual(a.document.to_dict(), before)

    def test_keyboard_editing_does_not_select_or_delete_panel_objects(self):
        a = self.app
        a.canvas.focus_force(); a.select_all()
        self.assertEqual(a.selection, {0, 1, 2, 3})
        a.edit_text_at(self.event(50, 60))
        editor = a.inline_editor['text']; editor.focus_force(); a.update()
        self.assertIsNone(a.select_all())
        self.assertEqual(a.selection, {1})
        apply_button = next(w for w in a._descendants(a.inline_editor['frame'])
                            if w.winfo_class() == 'TButton' and w.cget('text') == 'Aplicar texto')
        apply_button.focus_force(); a.update()
        apply_button.event_generate('<Delete>'); apply_button.event_generate('<Control-z>'); a.update()
        self.assertEqual(len(a.document.elements), 4)
        self.assertIsNotNone(a.inline_editor)
        editor.focus_force(); a.update()
        editor.event_generate('<Escape>'); a.update()
        self.assertIsNone(a.inline_editor)
        self.assertFalse(a.history)

    def test_real_double_click_and_enter_bindings_edit_without_duplicate(self):
        a = self.app
        a.mode.set('text'); a.mode_changed()
        event = self.event(50, 60)
        for sequence, time in [('<ButtonPress-1>', 10000), ('<ButtonRelease-1>', 10020),
                               ('<ButtonPress-1>', 10100), ('<ButtonRelease-1>', 10120)]:
            a.canvas.event_generate(sequence, x=round(event.x), y=round(event.y), time=time)
            a.update()
        self.assertIsNotNone(a.inline_editor)
        self.assertEqual(len(a.document.elements), 4)
        editor = a.inline_editor['text']
        editor.focus_force(); a.update()
        editor.delete('1.0', 'end'); editor.insert('1.0', 'LINE 1')
        editor.mark_set('insert', 'end-1c')
        editor.event_generate('<Shift-Return>'); a.update()
        editor.insert('insert', 'LINE 2')
        self.assertEqual(editor.get('1.0', 'end-1c'), 'LINE 1\nLINE 2')
        editor.event_generate('<Return>'); a.update()
        self.assertIsNone(a.inline_editor)
        self.assertEqual(a.document.elements[1].text, 'LINE 1\nLINE 2')
        self.assertEqual(len(a.history), 1)


if __name__ == '__main__':
    unittest.main()
