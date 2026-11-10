"""Manufacturing output keeps its editable source and exposes a usable path."""
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from export_result import show_export_result
from panel_editor import PanelEditor
from panel_model import Element


def descendants(widget):
    for child in widget.winfo_children():yield child;yield from descendants(child)


class OutputFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.app=PanelEditor();self.app.withdraw()

    def tearDown(self):self.app.destroy();self.temp.cleanup()

    def button(self,text):
        return next(w for w in descendants(self.app) if isinstance(w,(tk.Button,ttk.Button)) and w.cget('text')==text)

    def test_copy_path_and_open_folder_use_the_exact_generated_output(self):
        path=self.folder/'con espacios'/'nuevo.zip';path.parent.mkdir();path.write_bytes(b'example')
        win=show_export_result(self.app,'Exportado',path)
        with patch.object(win,'clipboard_clear') as clear,patch.object(win,'clipboard_append') as append:
            self.button('Copiar ruta').invoke()
            clear.assert_called_once();append.assert_called_once_with(str(path.resolve()))
        with patch('export_result.os.startfile') as open_folder:
            self.button('Abrir carpeta').invoke()
            open_folder.assert_called_once_with(str(path.parent.resolve()))
        field=next(w for w in descendants(win) if isinstance(w,tk.Entry))
        self.assertEqual(field.get(),str(path.resolve()))
        self.button('Cerrar').invoke()

    def test_cancel_first_save_or_save_error_creates_no_manufacturing_files(self):
        a=self.app;a.document.elements=[Element('text',20,50,3,'GAIN')];a.dirty=True
        for saved in ('',str(self.folder/'frontal.panel.json')):
            a.export_gerber()
            with patch('panel_editor.filedialog.asksaveasfilename',return_value=saved),\
                 patch('panel_editor.messagebox.showerror') as error,\
                 patch('panel_gerber.export_panel') as export:
                if saved:
                    with patch.object(a.document,'save',side_effect=OSError('No se puede guardar')):
                        self.button('Guardar proyecto y generar ZIP').invoke()
                    self.assertTrue(error.called)
                else:self.button('Guardar proyecto y generar ZIP').invoke()
                export.assert_not_called()
                self.assertTrue(a.dirty);self.assertIsNone(a.project_path)
                self.assertFalse(list(self.folder.rglob('*.zip')))
            next(w for w in a.winfo_children() if isinstance(w,tk.Toplevel)).destroy()


if __name__=='__main__':unittest.main()
