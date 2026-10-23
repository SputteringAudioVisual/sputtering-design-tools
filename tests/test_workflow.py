"""Regression checks for the original silkscreen workflow and additive drills."""
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from design_app import DesignToolsApp
from drill import DrillLayer
from gerber_silkscreen_editor import GerberEditor, ImageToGerber
from panel_model import Reference, PanelDocument, load_references
from test_panel import BOARD

DRILLS = 'M48\nMETRIC,TZ\nT01C0.7\n%\nG90\nT01\nX1500000Y2000000\nX2500000\nM30\n'


class DrillTests(unittest.TestCase):
    def test_format_required_and_modal_coordinates(self):
        with self.assertRaises(ValueError):
            DrillLayer(DRILLS)
        layer = DrillLayer(DRILLS, (5, 5))
        self.assertEqual([(h['x'], h['y'], h['sx']) for h in layer.drawables], [(15, 20, .7), (25, 20, .7)])

    def test_parameter_file_and_portable_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder/'test.drl').write_text(DRILLS)
            (folder/'nc_param.txt').write_text('INTEGER-PLACES 5\nDECIMAL-PLACES 5\n')
            refs, errors = load_references([folder/'test.drl'])
            self.assertFalse(errors)
            self.assertEqual(len(refs[0].layer.drawables), 2)
            document = PanelDocument(layers=[Reference('outline.gko', BOARD), *refs])
            restored = PanelDocument.from_dict(document.to_dict())
            self.assertEqual(document.to_dict(), restored.to_dict())
            self.assertEqual(restored.layers[1].layer.drawables[0]['x'], 15)

    def test_explicit_decimals_and_zero_modes(self):
        decimal = DrillLayer('M48\nINCH,TZ\nT01C.1\n%\nT01\nX1.0Y2.0\nM30')
        self.assertAlmostEqual(decimal.drawables[0]['x'], 25.4)
        self.assertAlmostEqual(decimal.drawables[0]['sx'], 2.54)
        leading = DrillLayer('M48\nMETRIC,LZ,000.000\nT01C1\n%\nT01\nX01Y02\nM30')
        self.assertEqual(leading.drawables[0]['x'], 10)
        with self.assertRaises(ValueError):
            DrillLayer(DRILLS.replace('G90', 'G91'), (5, 5))


class OriginalWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.app = DesignToolsApp()
        self.app.withdraw()
        self.app.add_references([Reference('outline.gko', BOARD), Reference('silk.gto', BOARD),
                                 Reference('test.drl', DRILLS, coord_format=(5, 5))])

    def tearDown(self):
        # Original conversion dialogs can schedule preview work; cancel on teardown.
        for timer in self.app.tk.splitlist(self.app.tk.call('after', 'info')):
            self.app.tk.call('after', 'cancel', timer)
        self.app.destroy()

    def test_original_toolbar_theme_and_methods_are_preserved(self):
        for name in ('import_image', '_open_conversion_editor', 'export_gerber', 'generate_new_layer',
                     '_build_controls', '_build_ui', '_choose_logo_layers', '_align_edge',
                     '_build_logo_cmds', '_choose_export_dialog', '_choose_base_layer',
                     '_choose_target_layer', '_choose_new_layer_type'):
            self.assertIs(getattr(DesignToolsApp, name), getattr(GerberEditor, name))
        labels = [w.cget('text') for w in self.walk(self.app) if isinstance(w, tk.Button)]
        for label in ('📂 Añadir capa', '🖼 Importar Imagen', '💾 Exportar Gerber', '✨ Generar capa nueva',
                      '🔬 Editor de conversión'):
            self.assertIn(label, labels)
        self.assertEqual(self.app.canvas.cget('bg'), '#0d1a0d')
        self.assertEqual(self.app.entry_x.cget('bg'), '#1a1a2e')

    @staticmethod
    def walk(widget):
        for child in widget.winfo_children():
            yield child
            yield from OriginalWorkflowTests.walk(child)

    def import_logo(self, folder):
        from PIL import Image
        path = Path(folder)/'logo.png'
        Image.new('RGB', (20, 10), 'black').save(path)
        with patch('gerber_silkscreen_editor.filedialog.askopenfilename', return_value=str(path)), \
             patch.object(self.app, '_choose_logo_layers'):
            self.app.import_image()

    def test_png_import_alignment_and_original_conversion_dialog(self):
        with tempfile.TemporaryDirectory() as folder:
            self.import_logo(folder)
            self.assertIsNotNone(self.app.overlay_image)
            self.app._center_both()
            self.assertTrue(self.app.overlay_w_mm > 0)
            self.app._rotate_by(90)
            self.assertEqual(self.app.overlay_angle_deg, 90)
            self.app._open_conversion_editor()
            self.assertTrue(any(isinstance(w, tk.Toplevel) for w in self.app.winfo_children()))

    def test_drills_visible_but_not_exported_as_gerber(self):
        self.app.update_idletasks()
        self.app._redraw()
        self.assertEqual(len(self.app.canvas.find_withtag('drill_reference')), 6)
        self.assertEqual(len(self.app._build_export_items()), 2)
        self.assertNotIn('test.drl', [item['label'] for item in self.app._build_export_items()])
        self.app.drill_references[0].variable.set(False)
        self.app._redraw()
        self.assertFalse(self.app.canvas.find_withtag('drill_reference'))

    def test_front_panel_does_not_reset_logo_or_main_window(self):
        with tempfile.TemporaryDirectory() as folder:
            self.import_logo(folder)
            logo = self.app.overlay_image
            self.app.overlay_x_mm = 14
            self.app._conv_algo = 'bayer4'
            self.app.open_panel()
            panel = self.app.panel_window
            self.assertIs(panel.master, self.app)
            self.assertEqual(len(panel.document.layers), 3)
            panel.destroy()
            self.assertTrue(self.app.winfo_exists())
            self.assertIs(self.app.overlay_image, logo)
            self.assertEqual(self.app.overlay_x_mm, 14)
            self.assertEqual(self.app._conv_algo, 'bayer4')

    def test_original_raster_export_new_over_under(self):
        with tempfile.TemporaryDirectory() as folder:
            self.import_logo(folder)
            layer = self.app.gerber_layer
            commands = self.app._build_logo_cmds(ImageToGerber(layer), 128)
            self.assertTrue(any(cmd.startswith('%ADD') for cmd in commands))
            for mode in ('new', 'before', 'after'):
                target = Path(folder)/(mode+'.gbr')
                if mode == 'new':
                    layer.export_new_layer(commands, target)
                else:
                    layer.export_with_overlay(commands, target, position=mode)
                content = target.read_text()
                self.assertIn('M02*', content)
                self.assertNotIn('M48', content)
                self.assertIn('%ADD', content)


if __name__ == '__main__':
    unittest.main()
