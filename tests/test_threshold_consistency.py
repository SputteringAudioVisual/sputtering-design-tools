"""The editor, main B/W control and actual Gerber retain the same ink."""
import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from design_app import DesignToolsApp
from gerber_silkscreen_editor import (GerberLayer, ImageToGerber, _image_ink_mask,
                                      _compute_logo_raster)
from panel_model import Reference
from test_panel import BOARD

ALGOS = ('threshold','floyd','floyd_fast','atkinson','bayer2','bayer4','bayer8','clustered4','stucki','jarvis')


class RasterFidelityTests(unittest.TestCase):
    def test_large_preview_reduces_binary_mask_not_source_gray(self):
        gray = Image.fromarray(np.tile(np.repeat([40, 220], 2), (1000, 400)).astype('uint8'))
        full = _image_ink_mask(gray, 120, 75, .15, 'threshold', 170)
        preview = _image_ink_mask(gray, 120, 75, .15, 'threshold', 170, 600)
        expected = Image.fromarray(full).resize((600, 375), Image.Resampling.NEAREST)
        np.testing.assert_array_equal(preview, np.asarray(expected))
        self.assertAlmostEqual(float(full.mean()), .5)
        self.assertAlmostEqual(float(preview.mean()), .5, delta=.005)

    def test_actual_gerber_keeps_every_dither_pixel_including_isolated_dots(self):
        checker = Image.fromarray((np.indices((10, 12)).sum(axis=0) % 2 * 255).astype('uint8'))
        gray = Image.new('L', (12, 10), 128)
        for algorithm in ALGOS:
            for image in (checker, gray):
                for clearance in (0, .2):
                    with self.subTest(algorithm=algorithm, clearance=clearance, checker=image is checker):
                        expected = _image_ink_mask(image, 1.8, 1.5, .15, algorithm, 170)
                        commands = ImageToGerber(GerberLayer()).convert(image, 0, 0, 1.8, 1.5,
                            threshold=170, dither_algo=algorithm, clearance_mm=clearance)
                        layer = GerberLayer()
                        layer.raw_lines = ['%FSLAX36Y36*%\n', '%MOMM*%\n', *commands, 'M02*']
                        layer._parse()
                        actual = np.zeros(expected.shape, dtype=bool)
                        for row in range(10):
                            for col in range(12):
                                x, y = (col+.5)*.15, 1.5-(row+.5)*.15
                                ink = False
                                for item in layer.drawables:
                                    if item['type'] == 'flash':
                                        hit = math.hypot(x-item['x'], y-item['y']) <= item['sx']/2
                                    elif item['type'] == 'line':
                                        nearest_x = max(min(item['x1'], item['x2']), min(x, max(item['x1'], item['x2'])))
                                        hit = math.hypot(x-nearest_x, y-item['y1']) <= item['width']/2
                                    else:
                                        self.fail('Unexpected raster geometry')
                                    if hit: ink = item.get('polarity', 'dark') == 'dark'
                                actual[row, col] = ink
                        np.testing.assert_array_equal(actual, expected)
                        if image is checker:
                            self.assertTrue(any(p['type']=='flash' for p in layer.drawables))


class ThresholdWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.app = DesignToolsApp()
        self.app.withdraw()
        self.app.add_references([Reference('outline.gko', BOARD), Reference('silk.gto', BOARD)])
        self.app.overlay_image = Image.linear_gradient('L').resize((40, 30)).convert('RGB')
        self.app.overlay_w_mm, self.app.overlay_h_mm = 6, 4.5
        self.app._open_conversion_editor()
        self.win = self.app._conv_editor
        self.pump(.1)

    def tearDown(self):
        if self.win.winfo_exists(): self.win.destroy()
        for timer in self.app.tk.splitlist(self.app.tk.call('after', 'info')):
            self.app.tk.call('after', 'cancel', timer)
        self.app.destroy()

    def pump(self, seconds):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            self.app.update(); time.sleep(.01)

    def edit(self, name, value):
        control = next(w for w in self.walk(self.win) if w.winfo_name()==name+'_control')
        entry = control.nametowidget('value')
        entry.delete(0, 'end'); entry.insert(0, value)
        return control, entry

    def walk(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self.walk(child)

    def button(self, caption):
        return next(w for w in self.walk(self.win) if isinstance(w, tk.Button) and w.cget('text')==caption)

    def test_main_and_editor_share_threshold_and_close_applies_other_values(self):
        control, entry = self.edit('threshold', '172')
        next(w for w in control.winfo_children() if isinstance(w, tk.Button) and w.cget('text')=='+').invoke()
        self.assertEqual(self.app.overlay_threshold.get(), 173)
        self.app.overlay_threshold.set(201); self.pump(.1)
        self.assertEqual(entry.get(), '201')
        self.edit('contrast', '1,42'); self.edit('pixel', '0,23')
        self.button('Cerrar y aplicar').invoke()
        self.assertFalse(self.win.winfo_exists())
        self.assertEqual(self.app._conv_contrast, 1.42)
        self.assertEqual(self.app._conv_pxsize, .23)
        self.assertEqual(self.app.overlay_threshold.get(), 201)
        # A shared variable must not keep callbacks to destroyed numeric fields.
        self.app.overlay_threshold.set(202); self.pump(.1)
        self.app._open_conversion_editor(); self.win = self.app._conv_editor
        self.pump(.1)
        self.assertEqual(self.edit('threshold', '202')[1].get(), '202')

    def test_export_confirms_typed_values_without_requiring_apply(self):
        self.edit('threshold', '209'); self.edit('contrast', '1,42'); self.edit('pixel', '0,23')
        next(w for w in self.walk(self.win) if isinstance(w, tk.Radiobutton) and w.cget('value')=='jarvis').invoke()
        item = self.app._build_export_items()[1]
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(self.app, '_choose_export_dialog', return_value=[dict(item=item,mode='new')]), \
             patch('gerber_silkscreen_editor.filedialog.askdirectory', return_value=folder), \
             patch('gerber_silkscreen_editor.messagebox.showinfo'), \
             patch('gerber_silkscreen_editor.messagebox.showerror', side_effect=AssertionError):
            output = self.app.export_gerber()
            self.assertIsNotNone(output)
            with zipfile.ZipFile(output) as archive:
                settings = json.loads(archive.read('manifest.json'))['conversion']
            self.assertEqual(settings['threshold'], 209)
            self.assertEqual(settings['contrast'], 1.42)
            self.assertEqual(settings['pixel_mm'], .23)
            self.assertEqual(settings['algorithm'], 'jarvis')

    def test_invalid_pending_value_blocks_close_export_and_new_layer(self):
        _, entry = self.edit('contrast', 'nan')
        entry.event_generate('<FocusOut>')
        self.assertEqual(entry.get(), 'nan')
        self.button('Cerrar y aplicar').invoke()
        self.assertTrue(self.win.winfo_exists())
        with patch.object(self.app, '_choose_export_dialog') as choices, \
             patch.object(self.app, '_choose_new_layer_type') as new_type, \
             patch('gerber_silkscreen_editor.filedialog.askdirectory') as folder:
            self.assertIsNone(self.app.export_gerber())
            self.app.generate_new_layer()
            choices.assert_not_called(); new_type.assert_not_called(); folder.assert_not_called()
        self.assertFalse(hasattr(self.app, '_conv_contrast'))

    def test_large_dither_worker_keeps_tk_responsive_and_stops_polling_on_close(self):
        self.win.destroy()
        self.app.overlay_w_mm, self.app.overlay_h_mm = 45, 35
        self.app._conv_algo = 'jarvis'
        gate = threading.Event()
        started = threading.Event()
        def compute(*parameters,**kwargs):
            started.set(); gate.wait(3)
            return _compute_logo_raster(*parameters,**kwargs)
        with patch('gerber_silkscreen_editor._compute_logo_raster', side_effect=compute):
            self.app._open_conversion_editor(); self.win = self.app._conv_editor
            heartbeat = []
            self.app.after(60, lambda: heartbeat.append(True))
            try:
                self.pump(.2)
                self.assertTrue(started.is_set())
                self.assertEqual(heartbeat, [True])
                self.assertIsNotNone(self.app._conv_poll_id)
                self.win.destroy()
                self.assertIsNone(self.app._conv_poll_id)
                self.assertIsNone(self.app._conv_refresh_id)
            finally:
                gate.set()


if __name__ == '__main__': unittest.main()
