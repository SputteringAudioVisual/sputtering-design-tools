"""Desktop front-panel workspace. Coordinates are millimetres from bottom left."""
import copy
from dataclasses import replace
import math
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from panel_model import PanelDocument, Element, HEIGHT_MM, HOLE_PRESETS, number, load_references, atomic_write


class PanelWorkspace:
    def __init__(self, paths=(), project=None, master=None, document=None):
        super().__init__(master) if master is not None else super().__init__()
        self.title('Sputtering Design Tools · Frontal Eurorack 3U')
        self.geometry('1240x850')
        self.minsize(950, 620)
        self.document = copy.deepcopy(document) if document is not None else (PanelDocument.load(project) if project else PanelDocument())
        self.project_path = str(project) if project else None
        self.dirty = False
        self.history, self.future = [], []
        self.selected = None
        self.drag = None
        self._drag_recorded = False
        self.footprint_dialog = None
        self.zoom = 1
        self.pan = [0, 0]
        self.mode = tk.StringVar(value='select')
        self.status = tk.StringVar(value='Carga el contorno y la serigrafía Gerber, o empieza con un panel vacío.')
        self.hp = tk.StringVar(value='16')
        self.gap = tk.StringVar(value='0.34')
        self.snap = tk.StringVar(value='0.5')
        self.show_pcb = tk.BooleanVar(value=True)
        self.dimensions = tk.StringVar()
        self.reference = tk.StringVar()
        self.x = tk.StringVar(value='0')
        self.y = tk.StringVar(value='0')
        self.size = tk.StringVar(value='6.5')
        self.text = tk.StringVar(value='DRIVE')
        self.hole_preset = tk.StringVar(value=HOLE_PRESETS['potentiometer'][0])
        self._build()
        self._apply_original_theme()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Control-s>', lambda e: self.save())
        self.bind('<Control-z>', lambda e: self.undo() if not self._editing() else None)
        self.bind('<Control-y>', lambda e: self.redo() if not self._editing() else None)
        self.bind('<Control-Shift-H>', lambda e: self.footprint_holes())
        self.bind('<Delete>', lambda e: self.delete() if not self._editing() else None)
        self.bind('<Escape>', lambda e: (self.mode.set('select'), self.mode_changed()))
        self.refresh()
        if paths:
            self.after(100, lambda: self.load_paths(paths))

    def _editing(self):
        return isinstance(self.focus_get(), (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox))

    def _apply_original_theme(self):
        """Scope the additional window's styles; leave the original controls alone."""
        self.configure(bg='#1e1e2e')
        style = ttk.Style(self)
        for widget_class in ('TFrame', 'TLabelframe', 'TLabel', 'TButton', 'TRadiobutton',
                             'TCheckbutton', 'TEntry', 'TCombobox', 'TPanedwindow'):
            style.configure('Panel.'+widget_class, background='#252535', foreground='#aaaacc',
                            fieldbackground='#1a1a2e', insertcolor='white')
            style.map('Panel.'+widget_class, background=[('active', '#3a3a5c')],
                      fieldbackground=[('readonly', '#1a1a2e')], foreground=[('disabled', '#666680')])
        style.configure('Panel.TLabelframe.Label', background='#252535', foreground='#9999dd')
        for widget in self._descendants(self):
            if isinstance(widget, ttk.Widget):
                name = widget.winfo_class()
                if name in ('TFrame', 'TLabelframe', 'TLabel', 'TButton', 'TRadiobutton',
                             'TCheckbutton', 'TEntry', 'TCombobox', 'TPanedwindow'):
                    widget.configure(style='Panel.'+name)
            elif isinstance(widget, tk.Listbox):
                widget.configure(bg='#1a1a2e', fg='#cccce0', selectbackground='#3a3a5c', highlightthickness=0)
            elif isinstance(widget, tk.Canvas) and widget is not self.canvas:
                widget.configure(bg='#252535')

    def _build(self):
        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.pack(fill='x')
        for label, command in [('Cargar PCB / Gerber', self.load_pcb), ('Abrir proyecto', self.open_project),
                               ('Guardar', self.save), ('Exportar SVG', self.export_svg),
                               ('Deshacer', self.undo), ('Rehacer', self.redo), ('Ajustar vista', self.fit)]:
            ttk.Button(toolbar, text=label, command=command).pack(side='left', padx=3)
        menu = tk.Menu(self)
        tools = tk.Menu(menu, tearoff=False)
        tools.add_command(label='Abrir editor de imágenes / Gerber original', command=self.open_legacy)
        tools.add_command(label='Guardar proyecto como…', command=lambda: self.save(save_as=True))
        tools.add_command(label='Vaciar agujeros y textos (conservar PCB)', command=self.clear_elements)
        menu.add_cascade(label='Herramientas', menu=tools)
        self.config(menu=menu)
        split = ttk.Panedwindow(self, orient='horizontal')
        split.pack(fill='both', expand=True, padx=10)
        side_host = ttk.Frame(split, width=320)
        side_canvas = tk.Canvas(side_host, width=312, highlightthickness=0)
        scrollbar = ttk.Scrollbar(side_host, orient='vertical', command=side_canvas.yview)
        side_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        side_canvas.pack(side='left', fill='both', expand=True)
        side = ttk.Frame(side_canvas, padding=(4, 0, 12, 10))
        pane = side_canvas.create_window((0, 0), window=side, anchor='nw')
        side.bind('<Configure>', lambda e: side_canvas.configure(scrollregion=side_canvas.bbox('all')))
        side_canvas.bind('<Configure>', lambda e: side_canvas.itemconfigure(pane, width=e.width))
        # Local wheel binding across descendants; no global wheel handler to steal canvas zoom.
        def scroll_side(event):
            side_canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
            return 'break'
        self._scroll_side = scroll_side
        split.add(side_host, weight=0)
        work = ttk.Frame(split)
        split.add(work, weight=1)
        self.canvas = tk.Canvas(work, bg='#17212b', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda e: self.draw())
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.motion)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.canvas.bind('<ButtonPress-3>', self.pan_start)
        self.canvas.bind('<B3-Motion>', self.pan_move)
        self.canvas.bind('<Motion>', self.coordinates)

        def section(name):
            frame = ttk.LabelFrame(side, text=name, padding=8)
            frame.pack(fill='x', pady=(0, 9))
            return frame

        def entry(frame, label, variable):
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=2)
            ttk.Label(row, text=label, width=18).pack(side='left')
            box = ttk.Entry(row, textvariable=variable, width=12)
            box.pack(side='right', fill='x', expand=True)
            box.bind('<Return>', lambda e: self.apply_selection())
            return box

        settings = section('1 · Frontal Eurorack 3U')
        entry(settings, 'Anchura (HP)', self.hp)
        entry(settings, 'Tolerancia total (mm)', self.gap)
        ttk.Label(settings, textvariable=self.dimensions).pack(anchor='w', pady=4)
        ttk.Button(settings, text='Aplicar ancho y centrar PCB', command=self.apply_panel).pack(fill='x')
        ttk.Button(settings, text='Actualizar tornillos de rack Ø3,2', command=self.add_mounts).pack(fill='x', pady=(4, 0))
        refs = section('2 · PCB de referencia · escala 1:1')
        self.layer_list = tk.Listbox(refs, height=4, exportselection=False, font=('Segoe UI', 9))
        self.layer_list.pack(fill='x')
        self.layer_list.bind('<Double-Button-1>', self.toggle_layer)
        ttk.Label(refs, text='Doble clic: mostrar / ocultar capa.', foreground='#586878').pack(anchor='w')
        ttk.Label(refs, text='Capa para centrar (elige el contorno):').pack(anchor='w', pady=(5, 0))
        self.ref_combo = ttk.Combobox(refs, textvariable=self.reference, state='readonly', width=30)
        self.ref_combo.pack(fill='x')
        self.ref_combo.bind('<<ComboboxSelected>>', self.change_reference)
        ttk.Checkbutton(refs, text='Mostrar PCB detrás del frontal', variable=self.show_pcb, command=self.draw).pack(anchor='w')
        ttk.Button(refs, text='Centrar PCB sin cambiar su tamaño', command=self.center).pack(fill='x', pady=3)
        ttk.Button(refs, text='Agujeros desde footprints…', command=self.footprint_holes).pack(fill='x', pady=3)
        ttk.Button(refs, text='Importar textos desde .brd…', command=self.import_refdes).pack(fill='x', pady=3)
        self.pcb_info = ttk.Label(refs, wraplength=265, foreground='#586878')
        self.pcb_info.pack(fill='x')
        controls = section('3 · Colocar y editar')
        modes = ttk.Frame(controls)
        modes.pack(fill='x')
        for label, value in [('Seleccionar', 'select'), ('Agujero', 'hole'), ('Texto', 'text'), ('Mover PCB', 'pcb')]:
            ttk.Radiobutton(modes, text=label, variable=self.mode, value=value,
                            command=self.mode_changed).pack(anchor='w')
        ttk.Label(controls, text='Tipo de agujero:').pack(anchor='w', pady=(6, 0))
        self.hole_combo = ttk.Combobox(controls, textvariable=self.hole_preset, state='readonly',
                                       values=[preset[0] for preset in HOLE_PRESETS.values()])
        self.hole_combo.pack(fill='x', pady=(0, 3))
        self.hole_combo.bind('<<ComboboxSelected>>', self.choose_hole_preset)
        ttk.Label(controls, text='Medida inicial editable según el casquillo de la pieza.',
                  wraplength=265, foreground='#7e8ba6').pack(anchor='w')
        entry(controls, 'Rejilla / ajuste (mm)', self.snap)
        entry(controls, 'X desde izquierda', self.x)
        entry(controls, 'Y desde abajo', self.y)
        entry(controls, 'Diám. / texto (mm)', self.size)
        entry(controls, 'Texto / nombre', self.text)
        ttk.Button(controls, text='Añadir en X / Y', command=self.add_numeric).pack(fill='x', pady=(5, 2))
        ttk.Button(controls, text='Aplicar al objeto seleccionado', command=self.apply_selection).pack(fill='x', pady=2)
        ttk.Label(controls, text='Clic vacío: colocar. Sobre un objeto: seleccionar y arrastrar, también en modo Agujero/Texto.\nEsc: seleccionar. Rueda: zoom.\nBotón derecho: desplazar la vista.',
                  wraplength=265, foreground='#586878').pack(anchor='w', pady=4)
        objects = section('4 · Objetos del frontal')
        self.object_list = tk.Listbox(objects, height=5, exportselection=False)
        self.object_list.pack(fill='x')
        self.object_list.bind('<<ListboxSelect>>', self.select_list)
        ttk.Button(objects, text='Eliminar seleccionado', command=self.delete).pack(fill='x', pady=3)
        self.warning = ttk.Label(side, foreground='#a04414', wraplength=285)
        self.warning.pack(fill='x')
        for widget in self._descendants(side):
            widget.bind('<MouseWheel>', scroll_side)
        ttk.Label(self, textvariable=self.status, padding=(12, 6), anchor='w').pack(fill='x')

    @staticmethod
    def _descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from PanelEditor._descendants(child)

    def open_legacy(self):
        subprocess.Popen([sys.executable, str(Path(__file__).with_name('gerber_silkscreen_editor.py'))])

    def remember(self):
        self.history.append(copy.deepcopy(self.document))
        self.history = self.history[-40:]
        self.future.clear()

    def changed(self):
        self.dirty = True
        self.refresh()

    def refresh(self):
        d = self.document
        self.hp.set(str(d.hp))
        self.gap.set(f'{d.gap:g}')
        self.dimensions.set(f'{d.width:.2f} × {HEIGHT_MM:g} mm · 3U')
        self.ref_combo['values'] = [f'{i+1} · {ref.name}' for i, ref in enumerate(d.layers)]
        if d.layers:
            self.ref_combo.current(d.reference_index)
        else:
            self.reference.set('Sin capas')
        self.layer_list.delete(0, 'end')
        for ref in d.layers:
            self.layer_list.insert('end', ('● ' if ref.visible else '○ ') + ref.name)
        self.object_list.delete(0, 'end')
        for i, obj in enumerate(d.elements):
            name = f'{obj.text or "Agujero"} Ø{obj.size:g}' if obj.kind == 'hole' else obj.text
            if obj.source_ref:
                name += ' · PCB'
            self.object_list.insert('end', f'{i+1} · {name} · {obj.x:.1f}, {obj.y:.1f}')
        if self.selected is not None and self.selected < len(d.elements):
            self.object_list.selection_set(self.selected)
        else:
            self.selected = None
        b = d.reference_bounds()
        self.pcb_info.config(text=(f'PCB: {b[2]-b[0]:.2f} × {b[3]-b[1]:.2f} mm\n'
                                  'Posición compartida por todas las capas.' if b else 'Carga Gerber sueltos o un ZIP.'))
        self.warning.config(text='\n'.join(d.problems()[:3]))
        name = Path(self.project_path).name if self.project_path else 'Sin guardar'
        self.title(('● ' if self.dirty else '') + f'Sputtering Design Tools · {name} · Frontal Eurorack 3U')
        self.draw()

    def load_pcb(self):
        paths = filedialog.askopenfilenames(parent=self, title='Cargar contorno y serigrafía Gerber / ZIP',
                                           filetypes=[('PCB / drills / ZIP', '*.gbr *.ger *.art *.gto *.gbo *.gko *.gm1 *.gtl *.gbl *.gts *.gbs *.pho *.drl *.xln *.exc *.zip *.txt'), ('Todos', '*.*')])
        if paths:
            self.load_paths(paths)

    def footprint_holes(self):
        from footprint_dialog import FootprintDialog
        if self.footprint_dialog is not None and self.footprint_dialog.winfo_exists():
            self.footprint_dialog.lift()
        else:
            self.footprint_dialog = FootprintDialog(self)

    def import_refdes(self):
        from footprint_dialog import FootprintDialog
        if self.footprint_dialog is not None and self.footprint_dialog.winfo_exists():
            self.footprint_dialog.lift()
        else:
            self.footprint_dialog = FootprintDialog(self, mode='texts')

    def clear_elements(self):
        if self.footprint_dialog is not None and self.footprint_dialog.winfo_exists():
            self.footprint_dialog.close()
        if not self.document.elements:
            return
        self.remember()
        self.document.elements.clear()
        self.selected = None
        self.changed()
        self.status.set('Frontal vacío: se conservan PCB, ancho y biblioteca. Deshacer recupera los objetos anteriores.')

    def load_paths(self, paths):
        refs, errors = load_references(paths)
        if refs:
            self.remember()
            self.document.layers = refs
            self.document.detach_footprint_holes()
            detected = self.document.choose_outline()
            self.document.center_pcb()
            self.show_pcb.set(True)
            self.changed()
            self.fit()
            self.status.set(f'{len(refs)} capas cargadas. ' + ('Contorno detectado y PCB centrada.' if detected else 'Elige la capa de contorno para un centrado exacto.'))
        if errors or not refs:
            messagebox.showwarning('Carga de referencia', '\n'.join(errors[:8]) if errors else
                                   'No se encontraron capas Gerber. Exporta el contorno y la serigrafía desde tu programa PCB; no se leen archivos .brd nativos.', parent=self)

    def apply_panel(self):
        try:
            checked = PanelDocument(hp=self.hp.get(), gap=self.gap.get())
            candidate = copy.deepcopy(self.document)
            candidate.hp, candidate.gap = checked.hp, checked.gap
            candidate.center_pcb()
            if any(e.is_rack_mount for e in candidate.elements):
                candidate.mounting_holes()
            self.remember()
            self.document = candidate
            self.selected = None
            self.changed()
            self.fit()
        except ValueError as error:
            messagebox.showerror('Dimensiones del panel', str(error), parent=self)

    def center(self):
        if self.document.layers:
            self.remember()
            self.document.center_pcb()
            self.changed()

    def change_reference(self, event=None):
        if self.ref_combo.current() >= 0:
            self.remember()
            self.document.reference_index = self.ref_combo.current()
            self.document.center_pcb()
            self.changed()

    def toggle_layer(self, event=None):
        selection = self.layer_list.curselection()
        if selection:
            self.remember()
            ref = self.document.layers[selection[0]]
            ref.visible = not ref.visible
            self.changed()

    def add_mounts(self):
        try:
            candidate = copy.deepcopy(self.document)
            candidate.mounting_holes()
            self.remember()
            self.document = candidate
            self.selected = None
            self.changed()
            self.status.set('Tornillos de rack actualizados para el ancho actual. Agujeros de controles conservados.')
        except ValueError as error:
            messagebox.showerror('Tornillos de rack', str(error), parent=self)

    def mode_changed(self):
        self.selected = None
        self.drag = None
        if self.mode.get() == 'text':
            self.size.set('3')
            if self.text.get() in {p[2] for p in HOLE_PRESETS.values()}:
                self.text.set('DRIVE')
        elif self.mode.get() == 'hole':
            self._apply_hole_preset()
        self.status.set('Selecciona o arrastra un objeto.' if self.mode.get() == 'select' else
                        'Clic vacío: colocar. Sobre un objeto: arrastrar para mover.')
        self.draw()

    def _hole_type(self):
        return next((key for key, value in HOLE_PRESETS.items() if value[0] == self.hole_preset.get()), 'custom')

    def _apply_hole_preset(self):
        _, diameter, name = HOLE_PRESETS[self._hole_type()]
        if diameter is not None:
            self.size.set(f'{diameter:g}')
        self.text.set(name)

    def choose_hole_preset(self, event=None):
        # The palette prepares a new hole; it does not resize an existing object.
        self.mode.set('hole')
        self.mode_changed()
        self.object_list.selection_clear(0, 'end')
        self.status.set('Tipo preparado: haz clic en el panel o usa Añadir en X / Y. Diámetro editable.')

    def add_at(self, x, y):
        if self.mode.get() not in {'hole', 'text'}:
            self.status.set('Elige Agujero o Texto para añadir un objeto.')
            return
        try:
            obj = Element(self.mode.get(), x, y, number(self.size.get(), 0.1, 200), self.text.get(),
                          self._hole_type() if self.mode.get() == 'hole' else '')
            self.remember()
            self.document.elements.append(obj)
            self.dirty = True
            self.select(len(self.document.elements)-1)
            return self.selected
        except ValueError as error:
            messagebox.showerror('Objeto del panel', str(error), parent=self)

    def add_numeric(self):
        try:
            self.add_at(number(self.x.get()), number(self.y.get()))
        except ValueError as error:
            messagebox.showerror('Coordenadas', str(error), parent=self)

    def apply_selection(self):
        if self.selected is None:
            return
        try:
            old = self.document.elements[self.selected]
            new = replace(old, x=number(self.x.get()), y=number(self.y.get()),
                          size=number(self.size.get(), 0.1, 200), text=self.text.get())
            if new.source_ref:
                new.board_x, new.board_y = new.x-self.document.pcb_dx, new.y-self.document.pcb_dy
            self.remember()
            self.document.elements[self.selected] = new
            self.changed()
        except ValueError as error:
            messagebox.showerror('Propiedades', str(error), parent=self)

    def select_list(self, event=None):
        selection = self.object_list.curselection()
        if selection:
            self.select(selection[0])

    def select(self, index):
        self.selected = index
        if index is not None:
            obj = self.document.elements[index]
            self.x.set(f'{obj.x:.3f}')
            self.y.set(f'{obj.y:.3f}')
            self.size.set(f'{obj.size:g}')
            self.text.set(obj.text)
            if obj.kind == 'hole':
                kind = 'rack' if obj.is_rack_mount else obj.hole_type or 'custom'
                self.hole_preset.set(HOLE_PRESETS[kind][0])
        self.refresh()

    def delete(self):
        if self.selected is not None:
            self.remember()
            del self.document.elements[self.selected]
            self.selected = None
            self.changed()

    def undo(self):
        if self.history:
            self.future.append(copy.deepcopy(self.document))
            self.document = self.history.pop()
            self.selected = None
            self.changed()

    def redo(self):
        if self.future:
            self.history.append(copy.deepcopy(self.document))
            self.document = self.future.pop()
            self.selected = None
            self.changed()

    def transform(self):
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        scale = max(0.05, min((width-90)/self.document.width, (height-70)/HEIGHT_MM)) * self.zoom
        return scale, width/2 + self.pan[0], height/2 + self.pan[1]

    def to_canvas(self, x, y):
        scale, cx, cy = self.transform()
        return cx+(x-self.document.width/2)*scale, cy-(y-HEIGHT_MM/2)*scale

    def from_canvas(self, x, y):
        scale, cx, cy = self.transform()
        return (x-cx)/scale+self.document.width/2, (cy-y)/scale+HEIGHT_MM/2

    def snapped(self, x, y):
        step = number(self.snap.get(), 0, 20)
        return (round(x/step)*step, round(y/step)*step) if step else (x, y)

    def fit(self):
        self.zoom, self.pan = 1, [0, 0]
        self.draw()

    def wheel(self, event):
        before = self.from_canvas(event.x, event.y)
        self.zoom = min(12, max(0.25, self.zoom * (1.15 if event.delta > 0 else 1/1.15)))
        after = self.to_canvas(*before)
        self.pan[0] += event.x-after[0]
        self.pan[1] += event.y-after[1]
        self.draw()

    def pan_start(self, event):
        self._pan_origin = (event.x, event.y, *self.pan)

    def pan_move(self, event):
        x, y, px, py = self._pan_origin
        self.pan = [px+event.x-x, py+event.y-y]
        self.draw()

    def coordinates(self, event):
        x, y = self.from_canvas(event.x, event.y)
        self.status.set(f'X {x:.2f} mm  ·  Y {y:.2f} mm  |  Arrastra objetos para moverlos  |  Escala PCB 1:1')

    def object_at(self, px, py):
        matches = self.canvas.find_overlapping(px-4, py-4, px+4, py+4)
        for item in reversed(matches):
            for tag in self.canvas.gettags(item):
                if tag.startswith('obj_'):
                    return int(tag[4:])
        return None

    def press(self, event):
        self.canvas.focus_set()
        self.drag = None
        self._drag_recorded = False
        x, y = self.from_canvas(event.x, event.y)
        mode = self.mode.get()
        if mode == 'pcb' and self.document.layers:
            self.drag = ('pcb', x, y, self.document.pcb_dx, self.document.pcb_dy)
            return
        # Existing objects take priority over every placement tool.
        index = self.object_at(event.x, event.y)
        if index is not None:
            self.select(index)
            obj = self.document.elements[index]
            self.drag = (index, x, y, obj.x, obj.y)
            return
        if mode in {'hole', 'text'}:
            if 0 <= x <= self.document.width and 0 <= y <= HEIGHT_MM:
                try:
                    added = self.add_at(*self.snapped(x, y))
                    if added is not None:
                        obj = self.document.elements[added]
                        self.drag = (added, x, y, obj.x, obj.y)
                        # Placing and dragging in one gesture is one undo action.
                        self._drag_recorded = True
                except ValueError as error:
                    messagebox.showerror('Rejilla', str(error), parent=self)
            return
        self.select(None)

    def motion(self, event):
        if self.drag:
            key, sx, sy, ox, oy = self.drag
            x, y = self.from_canvas(event.x, event.y)
            if not self._drag_recorded and math.hypot(x-sx, y-sy)*self.transform()[0] < 3:
                return
            try:
                nx, ny = self.snapped(ox+x-sx, oy+y-sy)
            except ValueError:
                return
            if key == 'pcb':
                if (nx, ny) == (self.document.pcb_dx, self.document.pcb_dy):
                    return
                if not self._drag_recorded:
                    self.remember()
                    self._drag_recorded = True
                self.document.pcb_dx, self.document.pcb_dy = nx, ny
                self.document.sync_footprint_holes()
                self.draw()
            else:
                obj = self.document.elements[key]
                if (nx, ny) == (obj.x, obj.y):
                    return
                if not self._drag_recorded:
                    self.remember()
                    self._drag_recorded = True
                scale = self.transform()[0]
                # Move only the selected drawing; do not repaint thousands of
                # Gerber reference primitives on every mouse movement.
                self.canvas.move(f'obj_{key}', (nx-obj.x)*scale, -(ny-obj.y)*scale)
                obj.x, obj.y = nx, ny
                if obj.source_ref:
                    obj.board_x, obj.board_y = nx-self.document.pcb_dx, ny-self.document.pcb_dy
                self.x.set(f'{nx:.3f}')
                self.y.set(f'{ny:.3f}')
            self.dirty = True

    def release(self, event):
        if self.drag:
            self.drag = None
            self.refresh()

    def draw(self):
        if not hasattr(self, 'canvas'):
            return
        c, d = self.canvas, self.document
        c.delete('all')
        scale = self.transform()[0]
        x0, y0 = self.to_canvas(0, HEIGHT_MM)
        x1, y1 = self.to_canvas(d.width, 0)
        c.create_rectangle(x0+5, y0+5, x1+5, y1+5, fill='#0c131a', outline='')
        c.create_rectangle(x0, y0, x1, y1, fill='#ece9e1', outline='#ffffff')
        for x in range(0, math.ceil(d.width), 5):
            px, _ = self.to_canvas(x, 0)
            c.create_line(px, y0, px, y1, fill='#d9d6ce')
        for y in range(0, 129, 5):
            _, py = self.to_canvas(0, y)
            c.create_line(x0, py, x1, py, fill='#d9d6ce')
        if self.show_pcb.get():
            colors = ['#879c9c', '#5b8595', '#9c9675', '#799775']
            for layer_index, ref in enumerate(d.layers):
                if not ref.visible:
                    continue
                def xy(x, y):
                    return self.to_canvas(x+d.pcb_dx, y+d.pcb_dy)
                for primitive in ref.layer.drawables:
                    drill = ref.coord_format is not None
                    color = '#ce602b' if drill else ('#ece9e1' if primitive.get('polarity') == 'clear' else colors[layer_index % len(colors)])
                    kind = primitive['type']
                    if kind == 'line':
                        c.create_line(*xy(primitive['x1'], primitive['y1']), *xy(primitive['x2'], primitive['y2']),
                                      fill=color, width=max(1, primitive['width']*scale), capstyle='round')
                    elif kind == 'flash':
                        x, y = primitive['x'], primitive['y']
                        sx, sy = primitive['sx']/2, primitive['sy']/2
                        box = (*xy(x-sx, y+sy), *xy(x+sx, y-sy))
                        if primitive['shape'] == 'R':
                            c.create_rectangle(*box, fill=color, outline='')
                        elif primitive['shape'] == 'O':
                            # Capsule, not an ellipse: Gerber obround aperture.
                            if sx >= sy:
                                c.create_line(*xy(x-sx+sy, y), *xy(x+sx-sy, y), fill=color,
                                              width=max(1, 2*sy*scale), capstyle='round')
                            else:
                                c.create_line(*xy(x, y-sy+sx), *xy(x, y+sy-sx), fill=color,
                                              width=max(1, 2*sx*scale), capstyle='round')
                        else:
                            c.create_oval(*box, fill='' if drill else color, outline=color if drill else '', width=1)
                            if drill:
                                px, py = xy(x, y)
                                c.create_line(px-3, py, px+3, py, fill=color)
                                c.create_line(px, py-3, px, py+3, fill=color)
                    elif kind == 'region' and len(primitive['path']) > 2:
                        points = [v for p in primitive['path'] for v in xy(*p)]
                        c.create_polygon(*points, fill=color, outline='')
            bounds = d.reference_bounds()
            if bounds:
                c.create_rectangle(*self.to_canvas(bounds[0]+d.pcb_dx, bounds[3]+d.pcb_dy),
                                   *self.to_canvas(bounds[2]+d.pcb_dx, bounds[1]+d.pcb_dy),
                                   outline='#427c8f', dash=(5, 3), width=1)
        for i, obj in enumerate(d.elements):
            x, y = self.to_canvas(obj.x, obj.y)
            selected = i == self.selected
            color = '#c34623' if selected else '#20252a'
            tag = f'obj_{i}'
            if obj.kind == 'hole':
                radius = obj.size*scale/2
                c.create_oval(x-radius, y-radius, x+radius, y+radius,
                              fill='#17212b', outline=color, width=2, tags=(tag,))
                c.create_line(x-4, y, x+4, y, fill='#9db4c3', tags=(tag,))
                c.create_line(x, y-4, x, y+4, fill='#9db4c3', tags=(tag,))
            else:
                item = c.create_text(x, y, text=obj.text, fill=color,
                                     font=('Arial', -max(1, round(obj.size*scale))), tags=(tag,))
                if selected:
                    c.create_rectangle(*c.bbox(item), outline=color, dash=(3, 2), tags=(tag,))
        c.create_text((x0+x1)/2, y0-18, text=f'{d.hp} HP  ·  {d.width:.2f} mm', fill='#d5e1e9', font=('Segoe UI', 11))
        c.create_text(x1+22, (y0+y1)/2, text='128,5 mm · 3U', angle=90, fill='#d5e1e9')
        c.create_text(x0, y1+17, text='0,0 mm', anchor='w', fill='#a4bbc9')

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel('Guardar proyecto', 'Hay cambios sin guardar. ¿Quieres guardarlos?', parent=self)
        if answer is None:
            return False
        return self.save() if answer else True

    def save(self, save_as=False):
        path = self.project_path if not save_as else None
        if not path:
            path = filedialog.asksaveasfilename(parent=self, title='Guardar proyecto de frontal',
                                               defaultextension='.panel.json', filetypes=[('Proyecto frontal', '*.panel.json')])
        if not path:
            return False
        try:
            self.document.save(path)
            self.project_path = path
            self.dirty = False
            self.refresh()
            self.status.set(f'Proyecto guardado: {Path(path).name}')
            return True
        except (OSError, ValueError) as error:
            messagebox.showerror('Guardar proyecto', str(error), parent=self)
            return False

    def open_project(self):
        if not self.confirm_discard():
            return
        path = filedialog.askopenfilename(parent=self, title='Abrir proyecto de frontal', filetypes=[('Proyecto frontal', '*.panel.json *.json')])
        if path:
            try:
                document = PanelDocument.load(path)
                self.document = document
                self.project_path = path
                self.dirty = False
                self.selected = None
                self.history.clear()
                self.future.clear()
                self.refresh()
                self.fit()
            except (OSError, ValueError, KeyError, TypeError) as error:
                messagebox.showerror('Abrir proyecto', str(error), parent=self)

    def export_svg(self):
        issues = self.document.problems()
        if issues and not messagebox.askyesno('Revisar dimensiones', '\n'.join(issues[:6]) + '\n\n¿Exportar de todas formas?', parent=self):
            return
        path = filedialog.asksaveasfilename(parent=self, title='Exportar frontal SVG a escala 1:1',
                                           defaultextension='.svg', filetypes=[('SVG', '*.svg')])
        if path:
            try:
                atomic_write(path, self.document.svg())
                self.status.set('SVG exportado a escala 1:1. Incluye frontal, agujeros y textos; la PCB es solo referencia.')
            except OSError as error:
                messagebox.showerror('Exportación SVG', str(error), parent=self)

    def close(self):
        if self.confirm_discard():
            self.destroy()


class PanelEditor(PanelWorkspace, tk.Tk):
    """Explicit standalone panel mode; the main launcher opens the original UI."""


class PanelWindow(PanelWorkspace, tk.Toplevel):
    """Additional workspace that leaves the original Gerber editor alive."""


if __name__ == '__main__':
    PanelEditor(sys.argv[1:]).mainloop()
