"""Regression checks for the original silkscreen workflow and additive drills."""
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from design_app import DesignToolsApp
from drill import DrillLayer
from gerber_silkscreen_editor import GerberEditor, GerberLayer, ImageToGerber, _raster_ink_mask
from panel_model import Reference, PanelDocument, load_references
from test_panel import BOARD

DRILLS = 'M48\nMETRIC,TZ\nT01C0.7\n%\nG90\nT01\nX1500000Y2000000\nX2500000\nM30\n'
ALGOS = ('threshold', 'floyd', 'atkinson', 'bayer4', 'bayer8', 'stucki', 'jarvis')


class ConversionTests(unittest.TestCase):
    def test_all_algorithms_keep_black_ink_and_white_empty(self):
        import numpy as np
        for algo in ALGOS:
            with self.subTest(algo=algo):
                self.assertTrue(_raster_ink_mask(np.zeros((16, 16)), algo, 128).all())
                self.assertFalse(_raster_ink_mask(np.full((16, 16), 255), algo, 128).any())

    def test_bayer_ramp_has_even_tonal_progression(self):
        import numpy as np
        for algo in ('bayer4', 'bayer8'):
            for value in (32, 64, 128, 192, 224):
                with self.subTest(algo=algo, gray=value):
                    coverage = _raster_ink_mask(np.full((16, 16), value), algo, 128).mean()
                    self.assertAlmostEqual(coverage, 1-value/255, delta=.04)

    def test_export_draws_only_the_black_half_for_every_algorithm(self):
        from PIL import Image
        image = Image.new('L', (24, 12), 255)
        image.paste(0, (0, 0, 12, 12))
        for algo in ALGOS:
            with self.subTest(algo=algo):
                commands = ImageToGerber(GerberLayer()).convert(
                    image, 0, 0, 3.6, 1.8, dither_algo=algo)
                layer = GerberLayer()
                layer.raw_lines = ['%FSLAX36Y36*%\n', '%MOMM*%\n', *commands, 'M02*']
                layer._parse()
                self.assertTrue(layer.drawables)
                for drawable in layer.drawables:
                    self.assertLess(drawable['x1'], 1.8)
                    self.assertLess(drawable['x2'], 1.8)


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

    def pump_events(self, seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            self.app.update()
            time.sleep(.01)

    def test_conversion_preview_settles_after_controls_and_resize(self):
        from PIL import Image
        self.app.overlay_image = Image.linear_gradient('L').resize((700, 500)).convert('RGB')
        self.app.overlay_w_mm, self.app.overlay_h_mm = 70, 50
        self.app._open_conversion_editor()
        win = self.app._conv_editor
        errors = []
        self.app.report_callback_exception = lambda *args: errors.append(args)

        def snapshot():
            return [(str(w.cget('image')), w.winfo_geometry()) for w in self.walk(win)
                    if isinstance(w, tk.Label) and w.cget('image')]

        def assert_settled():
            self.pump_events(1.0)
            previous = snapshot()
            self.assertEqual(len(previous), 2)
            self.pump_events(.6)
            self.assertEqual(snapshot(), previous, 'Preview keeps repainting while idle')
            self.assertFalse(any('vista rápida' in w.cget('text') for w in self.walk(win)
                                 if isinstance(w, tk.Label)))
            return previous

        initial = assert_settled()
        threshold = next(w for w in self.walk(win) if isinstance(w, tk.Scale)
                         and float(w.cget('to')) == 255)
        threshold.set(185)
        changed = assert_settled()
        self.assertNotEqual(initial[0][0], changed[0][0])
        win.geometry('1000x700')
        resized = assert_settled()
        self.assertNotEqual(changed[0][1], resized[0][1])
        for radio in (w for w in self.walk(win) if isinstance(w, tk.Radiobutton)):
            radio.invoke()
            self.pump_events(.02)
        assert_settled()
        self.assertFalse(errors)

    def test_conversion_close_cancels_pending_preview(self):
        from PIL import Image
        self.app.overlay_image = Image.new('RGB', (40, 30), 'gray')
        self.app.overlay_w_mm, self.app.overlay_h_mm = 4, 3
        self.app._open_conversion_editor()
        self.pump_events(.08)
        win = self.app._conv_editor
        errors = []
        self.app.report_callback_exception = lambda *args: errors.append(args)
        win.destroy()
        self.pump_events(.5)
        self.assertIsNone(self.app._conv_refresh_id)
        self.assertIsNone(self.app._conv_quality_id)
        self.assertFalse(errors)
        self.app._open_conversion_editor()
        self.pump_events(.6)
        self.assertTrue(self.app._conv_editor.winfo_exists())

    def test_conversion_enlarges_both_views_and_preserves_polarity(self):
        from PIL import Image, ImageTk
        from tkinter import font as tkfont
        self.app.overlay_image = Image.new('RGB', (40, 20), 'white')
        self.app.overlay_image.paste('black', (0, 0, 20, 20))
        self.app.overlay_w_mm, self.app.overlay_h_mm = 6, 3
        self.app._conv_algo = 'atkinson'
        self.app._conv_pxsize = .2
        self.app._open_conversion_editor()
        win = self.app._conv_editor
        self.pump_events(.7)
        labels = [w for w in self.walk(win) if isinstance(w, tk.Label) and w.cget('image')]
        self.assertEqual(len(labels), 2)
        width, height = labels[0].image.width(), labels[0].image.height()
        self.assertGreater(width, 150, 'Small source must enlarge to fit the viewport')
        self.assertEqual((width, height), (labels[1].image.width(), labels[1].image.height()))
        self.assertGreaterEqual(width, labels[0].master.winfo_width()-6)
        radios = [w for w in self.walk(win) if isinstance(w, tk.Radiobutton)]
        self.assertEqual(self.app.getvar(radios[0].cget('variable')), 'atkinson')
        self.assertGreaterEqual(tkfont.Font(win, font=radios[0].cget('font')).cget('size'), 11)
        for radio in radios:
            with self.subTest(algo=radio.cget('value')):
                radio.invoke()
                self.pump_events(.6)
                image = ImageTk.getimage(labels[1].image).convert('L')
                self.assertEqual(image.getpixel((width//4, height//2)), 0)
                self.assertEqual(image.getpixel((width*3//4, height//2)), 255)
        invert = next(w for w in self.walk(win) if isinstance(w, tk.Checkbutton))
        invert.invoke()
        self.pump_events(.5)
        original = ImageTk.getimage(labels[0].image).convert('L')
        self.assertEqual(original.getpixel((width//4, height//2)), 0)
        self.assertEqual(original.getpixel((width*3//4, height//2)), 255)
        converted = ImageTk.getimage(labels[1].image).convert('L')
        self.assertEqual(converted.getpixel((width//4, height//2)), 255)
        self.assertEqual(converted.getpixel((width*3//4, height//2)), 0)

    def test_conversion_precise_values_steps_validation_and_apply(self):
        from PIL import Image
        self.app.overlay_image = Image.linear_gradient('L').resize((40, 30)).convert('RGB')
        self.app.overlay_w_mm, self.app.overlay_h_mm = 6, 4.5
        self.app._open_conversion_editor()
        win = self.app._conv_editor
        self.pump_events(.6)
        controls = {w.winfo_name(): w for w in self.walk(win)
                    if w.winfo_name() in ('threshold_control', 'contrast_control', 'pixel_control')}

        def edit(name, text):
            entry = controls[name+'_control'].nametowidget('value')
            entry.delete(0, 'end')
            entry.insert(0, text)
            return entry

        def button(name, caption):
            return next(w for w in controls[name+'_control'].winfo_children()
                        if isinstance(w, tk.Button) and w.cget('text') == caption)

        entry = edit('contrast', '1,27')
        button('contrast', '+').invoke()
        self.assertEqual(entry.get(), '1,28')
        button('contrast', '−').invoke()
        self.assertEqual(entry.get(), '1,27')
        button('contrast', 'Restablecer').invoke()
        self.assertEqual(entry.get(), '1,00')
        entry = edit('threshold', '255')
        button('threshold', '+').invoke()
        self.assertEqual(entry.get(), '255')
        entry = edit('pixel', '0,15')
        button('pixel', '−').invoke()
        self.assertEqual(entry.get(), '0,15')

        # Incomplete/non-finite input must never leak into export parameters.
        apply = next(w for w in self.walk(win) if isinstance(w, tk.Button)
                     and w.cget('text') == '✅ Aplicar a exportación')
        win.geometry('900x600')
        self.pump_events(.6)
        self.assertTrue(apply.winfo_ismapped())
        self.assertLess(apply.winfo_rooty()+apply.winfo_height(), win.winfo_rooty()+win.winfo_height())
        errors = []
        self.app.report_callback_exception = lambda *args: errors.append(args)
        with patch('gerber_silkscreen_editor.messagebox.showinfo') as notice:
            for invalid in ('', '-', 'nan', 'inf', 'texto'):
                edit('contrast', invalid)
                apply.invoke()
                self.assertFalse(notice.called)
                self.assertFalse(hasattr(self.app, '_conv_contrast'))
            edit('contrast', '1,27')
            edit('threshold', '174')
            edit('pixel', '0,23')
            apply.invoke()
            self.assertTrue(notice.called)
        self.assertEqual(self.app._conv_contrast, 1.27)
        self.assertEqual(self.app.overlay_threshold.get(), 174)
        self.assertEqual(self.app._conv_pxsize, .23)
        self.pump_events(.6)
        self.assertFalse(errors)
        self.assertFalse(any(w.cget('text').startswith('Error:') for w in self.walk(win)
                             if isinstance(w, tk.Label)))

    def test_conversion_keeps_original_and_selected_algorithm_during_adjustment(self):
        from PIL import Image, ImageTk
        self.app.overlay_image = Image.linear_gradient('L').resize((40, 30)).convert('RGB')
        self.app.overlay_w_mm, self.app.overlay_h_mm = 6, 4.5
        self.app._conv_algo = 'floyd'
        self.app._open_conversion_editor()
        win = self.app._conv_editor
        self.pump_events(.6)
        labels = [w for w in self.walk(win) if isinstance(w, tk.Label) and w.cget('image')]
        original = ImageTk.getimage(labels[0].image).tobytes()
        contrast = next(w for w in self.walk(win) if isinstance(w, tk.Scale)
                        and float(w.cget('to')) == 3)
        with patch('gerber_silkscreen_editor._raster_ink_mask', wraps=_raster_ink_mask) as mask:
            contrast.set(1.63)
            self.pump_events(.15)
            self.assertTrue(mask.called)
            self.assertTrue(all(call.args[1] == 'floyd' for call in mask.call_args_list))
        self.pump_events(.6)
        self.assertEqual(ImageTk.getimage(labels[0].image).tobytes(), original)
        threshold = next(w for w in self.walk(win) if isinstance(w, tk.Scale)
                         and float(w.cget('to')) == 255)
        radios = {w.cget('value'): w for w in self.walk(win) if isinstance(w, tk.Radiobutton)}
        radios['bayer4'].invoke()
        self.assertEqual(threshold.cget('state'), 'disabled')
        radios['atkinson'].invoke()
        self.assertEqual(threshold.cget('state'), 'normal')

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
