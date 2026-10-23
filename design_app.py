"""Additive integration: the original silkscreen UI is the main application."""
import copy
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

from gerber_silkscreen_editor import GerberEditor
from panel_model import PanelDocument, Reference, load_references


class DesignToolsApp(GerberEditor):
    def __init__(self, paths=(), project=None):
        self.drill_references = []
        self.panel_window = None
        self.panel_seed = None
        self.panel_project = project
        self.zoom = 1.0
        super().__init__()
        self.geometry('1200x750')
        # Original toolbar, conversion editor, controls and callbacks stay intact.
        menu = tk.Menu(self, bg='#252535', fg='white', activebackground='#3a3a5c')
        references = tk.Menu(menu, tearoff=False, bg='#252535', fg='white')
        references.add_command(label='Añadir PCB + drills (Gerber / Excellon / ZIP)…', command=self.choose_references)
        references.add_command(label='Añadir solo drills…', command=self.choose_drills)
        menu.add_cascade(label='PCB y referencias', menu=references)
        menu.add_command(label='Frontal Eurorack 3U…', command=self.open_panel)
        self.config(menu=menu)
        if project:
            self.panel_seed = PanelDocument.load(project)
            self.add_references(self.panel_seed.layers)
        if paths:
            self.load_paths(paths)

    def choose_references(self):
        paths = filedialog.askopenfilenames(parent=self, title='Añadir PCB, serigrafía y drills',
                                           filetypes=[('PCB / referencias', '*.art *.gbr *.ger *.gto *.gbo *.gko *.drl *.xln *.exc *.zip *.txt'), ('Todos', '*.*')])
        if paths:
            self.load_paths(paths)

    def choose_drills(self):
        paths = filedialog.askopenfilenames(parent=self, title='Añadir drills Excellon (nc_param.txt se detecta al lado)',
                                           filetypes=[('Excellon / parámetros', '*.drl *.xln *.exc *.txt'), ('Todos', '*.*')])
        if paths:
            self.load_paths(paths)

    def load_paths(self, paths):
        refs, errors = load_references(paths)
        self.add_references(refs)
        if errors:
            messagebox.showwarning('Carga de referencias', '\n'.join(errors[:8]), parent=self)

    def add_references(self, references):
        for ref in references:
            if ref.coord_format is not None:
                ref = copy.deepcopy(ref)
                ref.variable = tk.BooleanVar(self, value=ref.visible)
                self.drill_references.append(ref)
            else:
                self.gerber_layers.append({'layer': ref.layer, 'name': ref.name,
                    'color': self.LAYER_COLORS[len(self.gerber_layers) % len(self.LAYER_COLORS)],
                    'var_visible': tk.BooleanVar(self, value=ref.visible),
                    'var_bbox': tk.BooleanVar(self, value=False)})
        if self.gerber_layers:
            self.gerber_layer = self.gerber_layers[0]['layer']
        self._rebuild_layers_panel()
        self.fit_view()
        count = sum(len(r.layer.drawables) for r in self.drill_references)
        self.info_var.set(f'{len(self.gerber_layers)} capas · {count} drills de referencia')

    def _rebuild_layers_panel(self):
        super()._rebuild_layers_panel()
        for ref in self.drill_references:
            row = tk.Frame(self.layers_frame, bg='#252535')
            row.pack(fill='x', pady=1)
            tk.Checkbutton(row, text=f'Drills · {ref.name}', variable=ref.variable,
                           command=self._redraw, bg='#252535', fg='#ff9955',
                           selectcolor='#1a1a2e', activebackground='#252535',
                           font=('Segoe UI', 7), anchor='w').pack(fill='x')

    def _get_all_bounds(self):
        if self.gerber_layers:
            return super()._get_all_bounds()
        layers = [ref.layer.bounds for ref in self.drill_references if ref.variable.get()]
        if layers:
            return min(b[0] for b in layers), min(b[1] for b in layers), max(b[2] for b in layers), max(b[3] for b in layers)
        return super()._get_all_bounds()

    def _drill_only_transform(self):
        if self.gerber_layers or not self.drill_references:
            return None
        b = self._get_all_bounds()
        w, h = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        scale = min(w/max(1, b[2]-b[0]), h/max(1, b[3]-b[1])) * .85 * self.zoom
        return scale, w/2+self.pan_x, h/2+self.pan_y, (b[0]+b[2])/2, (b[1]+b[3])/2

    def _mm_to_canvas(self, x_mm, y_mm):
        transform = self._drill_only_transform()
        if transform:
            scale, cx, cy, mx, my = transform
            return cx+(x_mm-mx)*scale, cy-(y_mm-my)*scale
        return super()._mm_to_canvas(x_mm, y_mm)

    def _canvas_to_mm(self, px, py):
        transform = self._drill_only_transform()
        if transform:
            scale, cx, cy, mx, my = transform
            return mx+(px-cx)/scale, my-(py-cy)/scale
        return super()._canvas_to_mm(px, py)

    def _get_mm_scale(self):
        transform = self._drill_only_transform()
        return transform[0] if transform else super()._get_mm_scale()

    def _draw_drills(self):
        if not hasattr(self, 'canvas'):
            return
        self.canvas.delete('drill_reference')
        scale = self._get_mm_scale()
        for ref in self.drill_references:
            if not ref.variable.get():
                continue
            for hit in ref.layer.drawables:
                x, y = self._mm_to_canvas(hit['x'], hit['y'])
                radius = max(1.5, hit['sx']*scale/2)
                self.canvas.create_oval(x-radius, y-radius, x+radius, y+radius,
                                        outline='#ff9955', width=1, tags='drill_reference')
                self.canvas.create_line(x-3, y, x+3, y, fill='#ff9955', tags='drill_reference')
                self.canvas.create_line(x, y-3, x, y+3, fill='#ff9955', tags='drill_reference')
        for tag in ('overlay', 'overlay_border', 'overlay_handle', 'overlay_center'):
            self.canvas.tag_raise(tag)

    def _redraw(self):
        super()._redraw()
        self._draw_drills()

    def _draw_gerber_fast(self):
        super()._draw_gerber_fast()
        self._draw_drills()

    def clear_layers(self):
        self.drill_references.clear()
        super().clear_layers()

    def open_panel(self):
        if self.panel_window is not None and self.panel_window.winfo_exists():
            self.panel_window.deiconify()
            self.panel_window.lift()
            return
        from panel_editor import PanelWindow
        try:
            document = copy.deepcopy(self.panel_seed) if self.panel_seed else PanelDocument()
            references = [Reference(e['name'], ''.join(e['layer'].raw_lines), visible=e['var_visible'].get())
                          for e in self.gerber_layers]
            for ref in self.drill_references:
                references.append(Reference(ref.name, ref.content, visible=ref.variable.get(), coord_format=ref.coord_format))
            document.layers = references
            document.choose_outline()
            document.center_pcb()
            self.panel_window = PanelWindow(master=self, document=document, project=self.panel_project)
            self.info_var.set('Frontal abierto aparte · tu edición de serigrafía sigue aquí')
        except ValueError as error:
            messagebox.showerror('Referencia del frontal', str(error), parent=self)
