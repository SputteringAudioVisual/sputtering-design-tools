"""Desktop front-panel workspace. Coordinates are millimetres from bottom left."""
import copy
from dataclasses import replace
import math
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageDraw
from panel_fonts import FONTS, element_mask, PIXEL_MM
from panel_theme import configure_styles, apply_theme

from panel_model import PanelDocument, Element, HEIGHT_MM, HOLE_PRESETS, number, load_references, atomic_write


class PanelWorkspace:
    def __init__(self, paths=(), project=None, master=None, document=None):
        if project:
            from module_migration import resolve_redirect
            project=resolve_redirect(project)
        if project:
            from module_project import INDEX,stage_path
            if Path(project).name==INDEX:project=stage_path(Path(project).parent,'panel')
        super().__init__(master) if master is not None else super().__init__()
        self.title('Sputtering Design Tools · Frontal Eurorack 3U')
        self.geometry('1240x850')
        self.minsize(950, 620)
        from pcb_project import load_project
        self.document = copy.deepcopy(document) if document is not None else (load_project(project) if project else PanelDocument())
        self.project_path = str(project) if project else None
        self.input_project_directory=None
        self.dirty = False
        self.history, self.future = [], []
        self.selected = None
        self.drag = None
        self.marquee = None
        self.inline_editor = None
        self._drag_origins = {}
        self._drag_recorded = False
        self._drawn_objects = {}
        self._background_key = None
        self._reference_image = None
        self._nudge_group = None
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
        self.text = tk.StringVar(value='TEXTO')
        self.selection_info = tk.StringVar(value='Sin selección')
        self.selection_count = tk.StringVar(value='Sin selección')
        self.move_step = tk.StringVar(value='0.5')
        self.move_text_only = tk.BooleanVar(value=True)
        self.font_choice = tk.StringVar(value=FONTS['sans'][0])
        self.text_angle=tk.StringVar(value='0')
        self.text_width=tk.StringVar(value='100')
        self.text_tracking=tk.StringVar(value='0')
        self.text_lines=tk.StringVar(value='1.2')
        self.text_gain=tk.StringVar(value='0.075')
        self.text_align=tk.StringVar(value='Centrado')
        self._text_images = []
        self.hole_preset = tk.StringVar(value=HOLE_PRESETS['potentiometer'][0])
        self._build()
        self._apply_original_theme()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Control-s>', lambda e: self.save())
        self.bind('<Control-Shift-S>', lambda e: self.save(save_as=True))
        self.bind('<Control-z>', lambda e: self.undo() if self.inline_editor is None and not self._editing() else None)
        self.bind('<Control-y>', lambda e: self.redo() if self.inline_editor is None and not self._editing() else None)
        self.bind('<Control-Shift-H>', lambda e: self.footprint_holes())
        self.bind('<Delete>', lambda e: self.delete() if self.inline_editor is None and not self._editing() else None)
        self.bind('<Escape>', self.escape)
        self.bind('<Control-a>', self.select_all)
        self.refresh()
        if paths:
            self.after(100, lambda: self.load_paths(paths))

    def _editing(self):
        return isinstance(self.focus_get(), (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox))

    @property
    def selected(self):
        """Active object, retaining compatibility with single-object commands."""
        return self._selected

    @selected.setter
    def selected(self, index):
        self._selected = index
        self.selection = {index} if index is not None else set()

    def escape(self, event=None):
        if self.inline_editor is not None:
            self.cancel_inline()
        else:
            if self.drag and self._drag_recorded:
                self.drag = None
                self.undo()
            self.mode.set('select')
            self.mode_changed()
        return 'break'

    def _apply_original_theme(self):
        """Scope the additional window's styles; leave the original controls alone."""
        self.configure(bg='#1e1e2e')
        configure_styles(self)
        apply_theme(self, self._descendants)
        for widget in self._descendants(self):
            if isinstance(widget, tk.Canvas) and widget is not self.canvas:
                widget.configure(bg='#252535')

    def _build(self):
        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.pack(fill='x')
        for label, command in [('Abrir proyecto…', self.open_project),
                               ('Guardar proyecto', self.save), ('Guardar como…',lambda:self.save(save_as=True)),('Exportar dibujo SVG…', self.export_svg),
                               ('Deshacer', self.undo), ('Rehacer', self.redo), ('Ajustar vista', self.fit)]:
            ttk.Button(toolbar, text=label, command=command).pack(side='left', padx=3)
        workflow = ttk.Frame(self, padding=(10, 0, 10, 8))
        workflow.pack(fill='x')
        for label, command in [('1. Cargar PCB / Gerber…', self.load_pcb),
                               ('2. Importar agujeros…', self.footprint_holes),
                               ('3. Importar textos…', self.import_refdes),
                               ('4. Exportar Gerber / ZIP…', self.export_gerber)]:
            ttk.Button(workflow, text=label, command=command,
                       style='Primary.Panel.TButton').pack(side='left', padx=3)
        ttk.Button(workflow,text='5. Imagen del frontal…',command=self.edit_artwork).pack(side='left',padx=3)
        ttk.Label(self, text='Carga la PCB → ajusta el ancho y centra → añade agujeros y textos → exporta para fabricar.',
                  style='Hint.Panel.TLabel', padding=(14, 0, 10, 8)).pack(fill='x')
        self.project_location=tk.StringVar()
        ttk.Label(self,textvariable=self.project_location,style='Hint.Panel.TLabel',padding=(14,0,10,6)).pack(fill='x')
        menu = tk.Menu(self)
        files=tk.Menu(menu,tearoff=False)
        files.add_command(label='Abrir proyecto…',command=self.open_project)
        files.add_command(label='Guardar proyecto',command=self.save,accelerator='Ctrl+S')
        files.add_command(label='Guardar proyecto como…',command=lambda:self.save(save_as=True),accelerator='Ctrl+Mayús+S')
        menu.add_cascade(label='Archivo',menu=files)
        tools = tk.Menu(menu, tearoff=False)
        tools.add_command(label='Abrir editor de imágenes / Gerber original', command=self.open_legacy)
        tools.add_command(label='Guardar proyecto como…', command=lambda: self.save(save_as=True))
        tools.add_command(label='Nuevo módulo / frontal',command=self.new_panel)
        tools.add_command(label='Vaciar agujeros y textos (conservar PCB)', command=self.clear_elements)
        menu.add_cascade(label='Herramientas', menu=tools)
        module=tk.Menu(menu,tearoff=False)
        module.add_command(label='Serigrafía de la PCB…',command=self.open_legacy)
        module.add_command(label='Imagen del frontal…',command=self.edit_artwork)
        module.add_command(label='Versiones y recuperación…',command=self.show_module_versions)
        module.add_command(label='Abrir carpeta del módulo',command=self.open_module_folder)
        menu.add_cascade(label='Módulo',menu=module)
        from loading_guide import show_guide
        help_menu=tk.Menu(menu,tearoff=False)
        help_menu.add_command(label='Guía rápida de carga…',command=lambda:show_guide(self))
        menu.add_cascade(label='Ayuda',menu=help_menu)
        self.config(menu=menu)
        split = ttk.Panedwindow(self, orient='horizontal')
        split.pack(fill='both', expand=True, padx=10)
        side_host = ttk.Frame(split, width=350)
        side_canvas = tk.Canvas(side_host, width=342, highlightthickness=0)
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
        quick_text = ttk.Frame(work, padding=(6, 4))
        quick_text.pack(fill='x')
        ttk.Button(quick_text, text='MAYÚSCULAS', command=lambda: self.change_case(True)).pack(side='left', padx=(0, 4))
        ttk.Button(quick_text, text='minúsculas', command=lambda: self.change_case(False)).pack(side='left', padx=(0, 8))
        ttk.Label(quick_text, textvariable=self.selection_count, style='Hint.Panel.TLabel').pack(side='left')
        movement = ttk.Frame(work, padding=(6, 2))
        movement.pack(fill='x')
        ttk.Label(movement, text='Paso (mm):').pack(side='left')
        ttk.Combobox(movement, textvariable=self.move_step, values=['0.1','0.25','0.5','1','2','5'], width=5).pack(side='left',padx=4)
        for label, dx, dy in [('←',-1,0),('↑',0,1),('↓',0,-1),('→',1,0)]:
            ttk.Button(movement,text=label,width=2,command=lambda x=dx,y=dy:self.nudge(x,y)).pack(side='left',padx=1)
        ttk.Button(movement,text='Mover…',command=self.move_dialog).pack(side='left',padx=4)
        ttk.Button(movement,text='Etiquetas PCB',command=self.select_pcb_labels).pack(side='left')
        align = ttk.Frame(work,padding=(6,2))
        align.pack(fill='x')
        ttk.Checkbutton(align,text='Solo textos',variable=self.move_text_only).pack(side='left',padx=(0,5))
        ttk.Button(align,text='Misma X',command=lambda:self.align_selection('x')).pack(side='left',padx=2)
        ttk.Button(align,text='Misma Y',command=lambda:self.align_selection('y')).pack(side='left',padx=2)
        ttk.Label(align,text='Flechas: mover · Mayús: ×10 · Alt: fino',style='Hint.Panel.TLabel').pack(side='left',padx=5)
        self.canvas = tk.Canvas(work, bg='#17212b', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda e: self.draw())
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.motion)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<Double-Button-1>', self.edit_text_at)
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.canvas.bind('<ButtonPress-3>', self.pan_start)
        self.canvas.bind('<B3-Motion>', self.pan_move)
        self.canvas.bind('<Motion>', self.coordinates)
        self.canvas.bind('<FocusOut>',lambda event:setattr(self,'_nudge_group',None))
        for key, dx, dy in [('Left',-1,0),('Right',1,0),('Up',0,1),('Down',0,-1)]:
            self.canvas.bind('<'+key+'>',lambda event,x=dx,y=dy:self.nudge(x,y,event))
            self.canvas.bind('<KeyRelease-'+key+'>',lambda event:setattr(self,'_nudge_group',None))

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

        settings = section('Tamaño del frontal · Eurorack 3U')
        entry(settings, 'Anchura (HP)', self.hp)
        entry(settings, 'Tolerancia total (mm)', self.gap)
        ttk.Label(settings, textvariable=self.dimensions).pack(anchor='w', pady=4)
        ttk.Button(settings, text='Aplicar ancho y centrar PCB', command=self.apply_panel,
                   style='Primary.Panel.TButton').pack(fill='x')
        ttk.Button(settings, text='Actualizar tornillos de rack Ø3,2', command=self.add_mounts).pack(fill='x', pady=(4, 0))
        refs = section('PCB de referencia · escala 1:1')
        self.layer_list = tk.Listbox(refs, height=4, exportselection=False, font=('Segoe UI', 9))
        self.layer_list.pack(fill='x')
        self.layer_list.bind('<Double-Button-1>', self.toggle_layer)
        ttk.Label(refs, text='Doble clic: mostrar / ocultar capa.', style='Hint.Panel.TLabel').pack(anchor='w')
        ttk.Label(refs, text='Capa para centrar (elige el contorno):').pack(anchor='w', pady=(5, 0))
        self.ref_combo = ttk.Combobox(refs, textvariable=self.reference, state='readonly', width=30)
        self.ref_combo.pack(fill='x')
        self.ref_combo.bind('<<ComboboxSelected>>', self.change_reference)
        ttk.Checkbutton(refs, text='Mostrar PCB detrás del frontal', variable=self.show_pcb, command=self.draw).pack(anchor='w')
        ttk.Button(refs, text='Centrar PCB sin cambiar su tamaño', command=self.center).pack(fill='x', pady=3)
        ttk.Button(refs, text='Importar agujeros desde .brd…', command=self.footprint_holes).pack(fill='x', pady=3)
        ttk.Button(refs, text='Importar textos desde .brd…', command=self.import_refdes).pack(fill='x', pady=3)
        self.pcb_info = ttk.Label(refs, wraplength=295, style='Hint.Panel.TLabel')
        self.pcb_info.pack(fill='x')
        controls = section('Edición manual · agujeros y textos')
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
                  wraplength=295, style='Hint.Panel.TLabel').pack(anchor='w')
        entry(controls, 'Rejilla / ajuste (mm)', self.snap)
        entry(controls, 'X desde izquierda', self.x)
        entry(controls, 'Y desde abajo', self.y)
        entry(controls, 'Diám. / texto (mm)', self.size)
        ttk.Label(controls,text='Texto / nombre · admite varias líneas:').pack(anchor='w')
        self.text_box=tk.Text(controls,height=3,width=24,wrap='none',undo=True)
        self.text_box.pack(fill='x',pady=3)
        self.text_box.insert('1.0',self.text.get());self.text_box.edit_modified(False)
        def text_changed(event=None):
            if self.text_box.edit_modified():
                self.text.set(self.text_box.get('1.0','end-1c'));self.text_box.edit_modified(False)
        def sync_text(*args):
            if self.text_box.get('1.0','end-1c')!=self.text.get():
                self.text_box.delete('1.0','end');self.text_box.insert('1.0',self.text.get());self.text_box.edit_modified(False)
        self.text_box.bind('<<Modified>>',text_changed);self.text.trace_add('write',sync_text)
        case_row = ttk.Frame(controls)
        case_row.pack(fill='x', pady=(0, 4))
        ttk.Button(case_row, text='MAYÚSCULAS', command=lambda: self.change_case(True)).pack(side='left', fill='x', expand=True, padx=(0, 2))
        ttk.Button(case_row, text='minúsculas', command=lambda: self.change_case(False)).pack(side='left', fill='x', expand=True, padx=(2, 0))
        ttk.Label(controls, textvariable=self.selection_info, wraplength=295,
                  style='Hint.Panel.TLabel').pack(fill='x', pady=(0, 4))
        ttk.Label(controls,text='Tipografía del texto:').pack(anchor='w')
        ttk.Combobox(controls,textvariable=self.font_choice,state='readonly',
                     values=[v[0] for v in FONTS.values()]).pack(fill='x',pady=3)
        entry(controls,'Giro del texto (°)',self.text_angle)
        entry(controls,'Ancho de texto (%)',self.text_width)
        entry(controls,'Espacio letras (mm)',self.text_tracking)
        entry(controls,'Interlineado',self.text_lines)
        entry(controls,'Engrosado (mm/lado)',self.text_gain)
        ttk.Combobox(controls,textvariable=self.text_align,state='readonly',
                     values=['Izquierda','Centrado','Derecha']).pack(fill='x',pady=3)
        ttk.Button(controls, text='Añadir nuevo en X / Y', command=self.add_numeric).pack(fill='x', pady=(5, 2))
        ttk.Button(controls, text='Actualizar objeto activo', command=self.apply_selection,
                   style='Primary.Panel.TButton').pack(fill='x', pady=2)
        ttk.Button(controls, text='Aplicar estilo a textos seleccionados', command=self.style_selected_texts).pack(fill='x', pady=2)
        ttk.Button(controls,text='Aplicar estilo a todos los textos',command=self.style_all_texts).pack(fill='x',pady=2)
        ttk.Button(controls,text='Duplicar selección',command=self.duplicate_selected).pack(fill='x',pady=2)
        ttk.Label(controls, text='Ctrl + clic: añadir o quitar selección. Arrastra en vacío para seleccionar un grupo en modo Seleccionar.\nArrastra un objeto para mover la selección. Doble clic en texto: editar.\nCtrl+A: seleccionar todo. Esc: cancelar. Rueda: zoom. Botón derecho: desplazar vista.',
                  wraplength=295, style='Hint.Panel.TLabel').pack(anchor='w', pady=4)
        objects = section('Objetos del frontal')
        self.object_list = tk.Listbox(objects, height=5, exportselection=False, selectmode='extended')
        self.object_list.pack(fill='x')
        self.object_list.bind('<<ListboxSelect>>', self.select_list)
        ttk.Button(objects, text='Eliminar selección', command=self.delete,
                   style='Danger.Panel.TButton').pack(fill='x', pady=3)
        self.warning = ttk.Label(side, style='Warning.Panel.TLabel', wraplength=295)
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
        from module_project import find_root,stage_path
        root=find_root(self.project_path)
        if root:
            path=stage_path(root,'pcb_silkscreen')
            if not path.exists():path=self.project_path
            subprocess.Popen([sys.executable,str(Path(__file__).with_name('sputtering_design_tools.py')),'--project',str(path)])
        else:subprocess.Popen([sys.executable, str(Path(__file__).with_name('gerber_silkscreen_editor.py'))])

    def edit_artwork(self):
        if not self.save():return
        try:
            from pcb_project import export_folder
            from panel_gerber import export_panel
            from module_project import continue_panel_artwork,create,find_root,last_panel_package
            if find_root(self.project_path) is None:
                create(Path(self.project_path).parent,Path(self.project_path).name.removesuffix('.panel.json'),self.project_path)
                self.document.save(self.project_path)
            archive=last_panel_package(self.project_path)
            if archive is None:
                archive=export_panel(self.document,export_folder(self.project_path,'frontal'),
                    Path(self.project_path).name.removesuffix('.panel.json'),project=self.project_path)
            path=continue_panel_artwork(self.project_path,archive)
            subprocess.Popen([sys.executable,str(Path(__file__).with_name('sputtering_design_tools.py')),'--project',str(path)])
            self.status.set('Imagen del frontal abierta dentro del mismo módulo. Se conservan los ajustes si ya existían.')
        except (OSError,ValueError) as error:messagebox.showerror('Imagen del frontal',str(error),parent=self)

    def open_module_folder(self):
        from module_project import find_root
        root=find_root(self.project_path)
        if root:
            import os
            os.startfile(str(root))

    def show_module_versions(self):
        from module_versions import show_versions
        def reload(path):
            if not str(path).endswith('.panel.json'):
                subprocess.Popen([sys.executable,str(Path(__file__).with_name('sputtering_design_tools.py')),'--project',str(path)])
                return
            from pcb_project import load_project
            self.document=load_project(path);self.project_path=str(path);self.dirty=False
            self.selected=None;self.history.clear();self.future.clear();self.refresh();self.fit()
        show_versions(self,self.project_path,self.save,reload)

    def remember(self):
        self._nudge_group = None
        self.history.append(self._snapshot())
        self.history = self.history[-40:]
        self.future.clear()

    def _snapshot(self):
        # Parsed PCB geometry is read-only here; copy visibility wrappers and
        # editable model data without duplicating thousands of primitives.
        layers=[copy.copy(ref) for ref in self.document.layers]
        return copy.deepcopy(self.document,{id(self.document.layers):layers})

    def changed(self, redraw='all'):
        self.dirty = True
        self.refresh(redraw)

    def refresh(self, redraw='all'):
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
        list_anchor = self.object_list.index('anchor')
        list_scroll = self.object_list.yview()[0]
        self.object_list.delete(0, 'end')
        for i, obj in enumerate(d.elements):
            name = f'{obj.text or "Agujero"} Ø{obj.size:g}' if obj.kind == 'hole' else obj.text
            if obj.source_ref:
                name += ' · PCB'
            self.object_list.insert('end', f'{i+1} · {name} · {obj.x:.1f}, {obj.y:.1f}')
        self.selection.intersection_update(range(len(d.elements)))
        if self.selected not in self.selection:
            self._selected = min(self.selection) if self.selection else None
        for index in sorted(self.selection):
            self.object_list.selection_set(index)
        if self.selected is not None:
            self.object_list.activate(self.selected)
        if d.elements:
            self.object_list.selection_anchor(min(list_anchor, len(d.elements)-1))
            self.object_list.yview_moveto(list_scroll)
        count = len(self.selection)
        texts = sum(d.elements[i].kind == 'text' for i in self.selection)
        self.selection_count.set(f'{count} seleccionados · {texts} textos' if count else 'Sin selección')
        self.selection_info.set(
            f'{count} seleccionados · {texts} textos. Propiedades: objeto activo {self.selected+1}.' if count > 1
            else '1 objeto seleccionado' if count else 'Sin selección · selecciona textos para cambiar mayúsculas o minúsculas.')
        b = d.reference_bounds()
        self.pcb_info.config(text=(f'PCB: {b[2]-b[0]:.2f} × {b[3]-b[1]:.2f} mm\n'
                                  'Posición compartida por todas las capas.' if b else 'Carga Gerber sueltos o un ZIP.'))
        self.warning.config(text='\n'.join(d.problems()[:3]))
        name = Path(self.project_path).name if self.project_path else 'Sin guardar'
        self.project_location.set(('Proyecto de frontal: '+str(self.project_path)) if self.project_path else 'Proyecto de frontal sin guardar · Guardar proyecto conserva agujeros, textos y referencias.')
        self.title(('● ' if self.dirty else '') + f'Sputtering Design Tools · {name} · Frontal Eurorack 3U')
        if redraw == 'all':
            self.draw()
        elif redraw == 'objects' or self._drawn_objects != {i:id(obj) for i,obj in enumerate(d.elements)}:
            self._draw_objects()
        else:
            self._draw_selection()

    def load_pcb(self):
        paths = filedialog.askopenfilenames(parent=self, title='Abrir PCB .brd o cargar Gerber / ZIP',
                                           filetypes=[('PCB / referencias / ZIP', '*.brd *.gbr *.ger *.art *.gto *.gbo *.gko *.gm1 *.gtl *.gbl *.gts *.gbs *.pho *.drl *.rou *.xln *.exc *.zip *.txt'), ('Todos', '*.*')])
        if paths:
            self.load_paths(paths)

    def footprint_holes(self):
        if not self.commit_inline():
            return
        from footprint_dialog import FootprintDialog
        if self.footprint_dialog is not None and self.footprint_dialog.winfo_exists():
            self.footprint_dialog.lift()
        else:
            self.footprint_dialog = FootprintDialog(self)

    def import_refdes(self):
        if not self.commit_inline():
            return
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

    def new_panel(self):
        if not self.confirm_discard():return
        if self.footprint_dialog is not None and self.footprint_dialog.winfo_exists():self.footprint_dialog.close()
        self.document=PanelDocument();self.project_path=None;self.selected=None;self.drag=None
        self.input_project_directory=None
        self.history.clear();self.future.clear();self.dirty=False;self.mode.set('select');self.text.set('TEXTO')
        self.refresh();self.fit()
        self.status.set('Nuevo módulo: elige su .brd para buscar fabricación y preparar la carpeta del proyecto.')

    def load_paths(self, paths):
        if len(paths)==1 and Path(paths[0]).suffix.lower()=='.brd':
            from pcb_project import prepare_project
            self.status.set('Preparando proyecto: leyendo PCB y buscando fabricación…')
            self.update_idletasks()
            try:
                prepared=prepare_project(paths[0],self.document,self.project_path)
                self.adopt_pcb_project(prepared)
            except (OSError,ValueError) as error:
                messagebox.showerror('Proyecto PCB',str(error),parent=self)
            return
        refs, errors = load_references(paths)
        if refs:
            from module_project import cad_project_root
            self.input_project_directory=cad_project_root(paths[0])
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

    def adopt_pcb_project(self, prepared):
        self.remember()
        self.document=prepared['document']
        self.project_path=prepared['project_path']
        self.selected=None;self.dirty=False
        self.refresh();self.fit()
        self.status.set('Proyecto preparado en '+str(Path(self.project_path).parent)+'. PCB, fabricación y componentes guardados localmente.')

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
        self.cancel_inline()
        self.selected = None
        self.drag = None
        self.marquee = None
        if self.mode.get() == 'text':
            self.size.set('3')
            if self.text.get() in {p[2] for p in HOLE_PRESETS.values()}:
                self.text.set('TEXTO')
        elif self.mode.get() == 'hole':
            self._apply_hole_preset()
        self.status.set('Selecciona o arrastra un objeto.' if self.mode.get() == 'select' else
                        'Clic vacío: colocar. Sobre un objeto: arrastrar para mover.')
        self._draw_selection()

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
                          self._hole_type() if self.mode.get() == 'hole' else '',
                          **(self._text_style() if self.mode.get()=='text' else {}))
            if obj.kind=='text':element_mask(obj)
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
                          size=number(self.size.get(), 0.1, 200), text=self.text.get(),
                          **(self._text_style() if old.kind=='text' else {}))
            if new.kind=='text':element_mask(new)
            if new.source_ref:
                new.board_x, new.board_y = new.x-self.document.pcb_dx, new.y-self.document.pcb_dy
            self.remember()
            self.document.elements[self.selected] = new
            self.changed()
        except ValueError as error:
            messagebox.showerror('Propiedades', str(error), parent=self)

    def select_list(self, event=None):
        selection = set(self.object_list.curselection())
        active = self.object_list.index('active') if selection else None
        if selection == self.selection and (active == self.selected or active not in selection):
            return
        self.selection = selection
        self._selected = active if active in selection else min(selection) if selection else None
        self._selection_fields()
        self._nudge_group=None
        self.refresh(False)

    def select(self, index, extend=False, toggle=False):
        if not extend:
            self.selected = index
        elif index is not None:
            if toggle and index in self.selection:
                self.selection.remove(index)
            else:
                self.selection.add(index)
            self._selected = index if index in self.selection else min(self.selection) if self.selection else None
        self._selection_fields()
        self._nudge_group=None
        self.refresh(False)
        if not extend and index is not None:
            self.object_list.selection_anchor(index)

    def _selection_fields(self):
        if self.selected is not None:
            obj = self.document.elements[self.selected]
            self.x.set(f'{obj.x:.3f}')
            self.y.set(f'{obj.y:.3f}')
            self.size.set(f'{obj.size:g}')
            self.text.set(obj.text)
            self.font_choice.set(FONTS[obj.font][0])
            self.text_angle.set(f'{obj.angle:g}');self.text_width.set(f'{obj.width_scale*100:g}')
            self.text_tracking.set(f'{obj.tracking:g}');self.text_lines.set(f'{obj.line_spacing:g}')
            self.text_gain.set(f'{obj.ink_gain:g}')
            self.text_align.set({'left':'Izquierda','center':'Centrado','right':'Derecha'}[obj.align])
            if obj.kind == 'hole':
                kind = 'rack' if obj.is_rack_mount else obj.hole_type or 'custom'
                self.hole_preset.set(HOLE_PRESETS[kind][0])

    def select_all(self, event=None):
        if self.inline_editor is not None or self._editing():
            return
        self.selection = set(range(len(self.document.elements)))
        self._selected = min(self.selection) if self.selection else None
        self._selection_fields()
        self.refresh(False)
        self.status.set(f'{len(self.selection)} objetos seleccionados. Arrastra para moverlos juntos; Ctrl + clic añade o quita.')
        return 'break'

    def select_pcb_labels(self):
        self.selection={i for i,e in enumerate(self.document.elements) if e.kind=='text' and e.source_ref}
        self._selected=min(self.selection) if self.selection else None
        self._selection_fields();self.refresh(False);self.canvas.focus_set()
        self.status.set('Etiquetas de componentes seleccionadas; el título y los agujeros se conservan.')

    def _move_targets(self):
        return sorted(i for i in self.selection if not self.move_text_only.get() or self.document.elements[i].kind=='text')

    def _apply_positions(self, positions, record=True):
        positions={i:(number(x),number(y)) for i,(x,y) in positions.items()}
        positions={i:point for i,point in positions.items() if point!=(self.document.elements[i].x,self.document.elements[i].y)}
        if not positions:return False
        if record:self.remember()
        scale=self.transform()[0]
        for index,(x,y) in positions.items():
            obj=self.document.elements[index]
            self.canvas.move(f'obj_{index}',(x-obj.x)*scale,-(y-obj.y)*scale)
            obj.x,obj.y=x,y
            if obj.source_ref:obj.board_x,obj.board_y=x-self.document.pcb_dx,y-self.document.pcb_dy
        self.dirty=True
        self._selection_fields();self.refresh(False)
        return True

    def move_selection(self, dx, dy, record=True):
        targets=self._move_targets()
        if not targets:
            self.status.set('Selecciona textos para moverlos. Desmarca Solo textos si quieres mover también agujeros.')
            return False
        dx,dy=number(dx),number(dy)
        moved=self._apply_positions({i:(self.document.elements[i].x+dx,self.document.elements[i].y+dy) for i in targets},record)
        if moved:self.status.set(f'{len(targets)} objetos movidos: ΔX {dx:g} mm · ΔY {dy:g} mm. Deshacer recupera la posición anterior.')
        return moved

    def nudge(self, dx, dy, event=None):
        if self.inline_editor is not None or (event is not None and self._editing()):return
        try:
            step=number(self.move_step.get(),.001,100)
            state=getattr(event,'state',0)
            if state & 0x1:step*=10
            if state & (0x8|0x20000):step/=10
            signature=(tuple(self._move_targets()),dx,dy,state & (0x1|0x8|0x20000))
            repeated=event is not None and self._nudge_group==signature
            if self.move_selection(dx*step,dy*step,record=not repeated):
                self._nudge_group=signature if event is not None else None
                self.canvas.focus_set()
        except ValueError as error:
            self.status.set('Paso de movimiento: '+str(error))
        return 'break'

    def align_selection(self, axis):
        ids=self._move_targets()
        if len(ids)<2:
            self.status.set('Selecciona al menos dos textos para alinearlos.');return
        active=self.selected if self.selected in ids else ids[0]
        anchor=self.document.elements[active]
        positions={i:(anchor.x if axis=='x' else self.document.elements[i].x,
                      anchor.y if axis=='y' else self.document.elements[i].y) for i in ids}
        if self._apply_positions(positions):
            reference='el objeto activo' if self.selected in ids else 'el primer texto seleccionado'
            self.status.set(f'{len(ids)} objetos alineados en {axis.upper()} con {reference}. Deshacer recupera la distribución anterior.')
        self.canvas.focus_set()

    def move_dialog(self):
        targets=self._move_targets()
        if not targets:
            self.status.set('Selecciona primero los textos que quieres desplazar.');return
        win=tk.Toplevel(self);win.title('Mover selección en milímetros');win.transient(self)
        frame=ttk.Frame(win,padding=14);frame.pack(fill='both',expand=True)
        texts=sum(self.document.elements[i].kind=='text' for i in targets)
        ttk.Label(frame,text=f'Se desplazan {texts} textos y {len(targets)-texts} agujeros.\nSe conservan las distancias entre ellos.').pack(anchor='w')
        dx,dy=tk.StringVar(value='0'),tk.StringVar(value='0')
        for label,var in [('ΔX (mm) · derecha + / izquierda −',dx),('ΔY (mm) · arriba + / abajo −',dy)]:
            row=ttk.Frame(frame);row.pack(fill='x',pady=5)
            ttk.Label(row,text=label).pack(side='left')
            ttk.Entry(row,textvariable=var,width=9).pack(side='right',padx=(12,0))
        def apply():
            try:
                self.move_selection(number(dx.get()),number(dy.get()))
                win.destroy();self.canvas.focus_set()
            except ValueError as error:messagebox.showerror('Desplazamiento',str(error),parent=win)
        ttk.Button(frame,text='Mover selección',command=apply,style='Primary.Panel.TButton').pack(fill='x',pady=(8,4))
        ttk.Button(frame,text='Cancelar',command=win.destroy).pack(fill='x')
        apply_theme(win,self._descendants)
        win.bind('<Return>',lambda e:(apply(),'break')[1]);win.bind('<Escape>',lambda e:win.destroy())
        win.grab_set()

    def delete(self):
        if self.selection:
            self.remember()
            self.document.elements = [e for i, e in enumerate(self.document.elements) if i not in self.selection]
            self.selected = None
            self.changed()

    def undo(self):
        if self.history:
            self.future.append(self._snapshot())
            self.document = self.history.pop()
            self.selected = None
            self.changed()

    def redo(self):
        if self.future:
            self.history.append(self._snapshot())
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

    def edit_text_at(self, event):
        index = self.object_at(event.x, event.y)
        if index is None or self.document.elements[index].kind != 'text':
            self.press(event)
            return 'break'
        self.cancel_inline()
        self.drag = None
        self.marquee = None
        self.select(index)
        frame = ttk.Frame(self.canvas, padding=8, style='Panel.TFrame')
        ttk.Label(frame, text='Editar texto · Enter: aplicar · Mayús+Enter: nueva línea',
                  style='Panel.TLabel').pack(anchor='w')
        editor = tk.Text(frame, height=3, width=36, wrap='word', undo=True,
                         bg='#191c2b', fg='#eef1f8', insertbackground='white', font=('Segoe UI', 12))
        editor.pack(fill='both', expand=True, pady=5)
        editor.insert('1.0', self.document.elements[index].text)
        actions = ttk.Frame(frame, style='Panel.TFrame')
        actions.pack(fill='x')
        ttk.Button(actions, text='Aplicar texto', command=self.commit_inline,
                   style='Primary.Panel.TButton').pack(side='left')
        ttk.Button(actions, text='Cancelar · Esc', command=self.cancel_inline,
                   style='Panel.TButton').pack(side='right')
        self.inline_editor = dict(index=index, frame=frame, text=editor)
        self._place_inline_editor()
        # Local grab keeps a pending edit from leaking into another operation.
        frame.grab_set()
        editor.focus_set()
        editor.tag_add('sel', '1.0', 'end-1c')
        editor.bind('<Return>', lambda e: (self.commit_inline(), 'break')[1])
        editor.bind('<Control-Return>', lambda e: (self.commit_inline(), 'break')[1])
        editor.bind('<Shift-Return>', lambda e: None)
        editor.bind('<Escape>', lambda e: (self.cancel_inline(), 'break')[1])
        self.status.set('Editando sobre el panel. Enter aplica; Mayús+Enter añade línea; Esc cancela.')
        return 'break'

    def _place_inline_editor(self):
        editing = self.inline_editor
        obj = self.document.elements[editing['index']]
        x, y = self.to_canvas(obj.x, obj.y)
        width = min(430, max(260, self.canvas.winfo_width()-16))
        editing['frame'].update_idletasks()
        height = editing['frame'].winfo_reqheight()
        x = max(8, min(x-width/2, self.canvas.winfo_width()-width-8))
        y = max(8, min(y+12, self.canvas.winfo_height()-height-8))
        self.canvas.delete('inline_editor')
        self.canvas.create_window(x, y, window=editing['frame'], width=width,
                                  anchor='nw', tags=('inline_editor',))

    def cancel_inline(self):
        if self.inline_editor is None:
            return
        editing, self.inline_editor = self.inline_editor, None
        editing['frame'].grab_release()
        editing['frame'].destroy()
        self.canvas.delete('inline_editor')
        self.canvas.focus_set()

    def commit_inline(self):
        if self.inline_editor is None:
            return True
        editing = self.inline_editor
        index = editing['index']
        old = self.document.elements[index]
        try:
            updated = replace(old, text=editing['text'].get('1.0', 'end-1c'))
            element_mask(updated)
        except ValueError as error:
            messagebox.showerror('Texto del frontal', str(error), parent=self)
            editing['frame'].grab_set()
            editing['text'].focus_set()
            return False
        self.cancel_inline()
        if updated != old:
            self.remember()
            self.document.elements[index] = updated
            self.dirty = True
        self.select(index)
        self.status.set('Texto actualizado. Deshacer recupera el contenido anterior.')
        return True

    def press(self, event):
        if self.inline_editor is not None:
            return
        self.canvas.focus_set()
        self.drag = None
        self.marquee = None
        self._drag_recorded = False
        self._nudge_group=None
        self.canvas.dtag('all','moving_selection')
        x, y = self.from_canvas(event.x, event.y)
        mode = self.mode.get()
        if mode == 'pcb' and self.document.layers:
            self.drag = ('pcb', x, y, self.document.pcb_dx, self.document.pcb_dy)
            return
        # Existing objects take priority over every placement tool.
        index = self.object_at(event.x, event.y)
        modifiers = getattr(event, 'state', 0)
        control, shift = bool(modifiers & 0x4), bool(modifiers & 0x1)
        if index is not None:
            self.select(index, extend=control or shift or index in self.selection, toggle=control)
            if index not in self.selection:
                return
            obj = self.document.elements[index]
            self.drag = (index, x, y, obj.x, obj.y)
            self._drag_origins = {i: (self.document.elements[i].x, self.document.elements[i].y) for i in self.selection}
            for i in self.selection:self.canvas.addtag_withtag('moving_selection',f'obj_{i}')
            return
        if mode == 'select' or control or shift:
            base = set(self.selection) if control or shift else set()
            self.marquee = (event.x, event.y, base)
            if not base:
                self.select(None)
            return
        if mode in {'hole', 'text'}:
            if 0 <= x <= self.document.width and 0 <= y <= HEIGHT_MM:
                try:
                    added = self.add_at(*self.snapped(x, y))
                    if added is not None:
                        obj = self.document.elements[added]
                        self.drag = (added, x, y, obj.x, obj.y)
                        self._drag_origins = {added: (obj.x, obj.y)}
                        self.canvas.addtag_withtag('moving_selection',f'obj_{added}')
                        # Placing and dragging in one gesture is one undo action.
                        self._drag_recorded = True
                except ValueError as error:
                    messagebox.showerror('Rejilla', str(error), parent=self)
            return
        self.select(None)

    def motion(self, event):
        if self.marquee is not None:
            sx, sy, _ = self.marquee
            self.canvas.delete('selection_box')
            self.canvas.create_rectangle(sx, sy, event.x, event.y, outline='#3f72bd',
                                         dash=(4, 3), width=2, tags=('selection_box',))
            return
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
                dx, dy = nx-ox, ny-oy
                self.canvas.move('moving_selection',(nx-obj.x)*scale,-(ny-obj.y)*scale)
                for index, (start_x, start_y) in self._drag_origins.items():
                    member = self.document.elements[index]
                    target_x, target_y = start_x+dx, start_y+dy
                    member.x, member.y = target_x, target_y
                    if member.source_ref:
                        member.board_x, member.board_y = target_x-self.document.pcb_dx, target_y-self.document.pcb_dy
                self.x.set(f'{nx:.3f}')
                self.y.set(f'{ny:.3f}')
            self.dirty = True

    def release(self, event):
        if self.marquee is not None:
            sx, sy, base = self.marquee
            self.marquee = None
            self.canvas.delete('selection_box')
            if math.hypot(event.x-sx, event.y-sy) >= 3:
                left, right = sorted((sx, event.x))
                top, bottom = sorted((sy, event.y))
                for i in range(len(self.document.elements)):
                    box = self.canvas.bbox(f'obj_{i}')
                    if box and box[2] >= left and box[0] <= right and box[3] >= top and box[1] <= bottom:
                        base.add(i)
            self.selection = base
            self._selected = min(base) if base else None
            self._selection_fields()
            self.refresh(False)
            self.status.set(f'{len(base)} objetos seleccionados. Arrastra uno para mover el grupo; Ctrl + clic añade o quita.')
            return
        if self.drag:
            moving_pcb=self.drag[0]=='pcb'
            self.drag = None
            self._drag_origins = {}
            self.canvas.dtag('all','moving_selection')
            self.refresh('all' if moving_pcb else False)

    def draw(self):
        if not hasattr(self, 'canvas'):
            return
        c, d = self.canvas, self.document
        key=(c.winfo_width(),c.winfo_height(),self.zoom,tuple(self.pan),d.hp,d.width,d.reference_index,
             d.pcb_dx,d.pcb_dy,self.show_pcb.get(),
             tuple((id(r.layer),r.visible,r.name,r.coord_format) for r in d.layers))
        if key==self._background_key and c.find_withtag('panel_background'):
            self._draw_objects()
            return
        self._background_key=key
        c.delete('all')
        self._text_images.clear()
        scale = self.transform()[0]
        x0, y0 = self.to_canvas(0, HEIGHT_MM)
        x1, y1 = self.to_canvas(d.width, 0)
        c.create_rectangle(x0+5, y0+5, x1+5, y1+5, fill='#0c131a', outline='')
        c.create_rectangle(x0, y0, x1, y1, fill='#000000', outline='#ffffff',tags=('panel_background',))
        for x in range(0, math.ceil(d.width), 5):
            px, _ = self.to_canvas(x, 0)
            c.create_line(px, y0, px, y1, fill='#181818')
        for y in range(0, 129, 5):
            _, py = self.to_canvas(0, y)
            c.create_line(x0, py, x1, py, fill='#181818')
        if self.show_pcb.get():
            self._reference_image=ImageTk.PhotoImage(self._reference_raster(),master=self)
            c.create_image(0,0,image=self._reference_image,anchor='nw',tags=('pcb_reference',))
            bounds = d.reference_bounds()
            if bounds:
                c.create_rectangle(*self.to_canvas(bounds[0]+d.pcb_dx, bounds[3]+d.pcb_dy),
                                   *self.to_canvas(bounds[2]+d.pcb_dx, bounds[1]+d.pcb_dy),
                                   outline='#427c8f', dash=(5, 3), width=1)
        else:self._reference_image=None
        c.create_text((x0+x1)/2, y0-18, text=f'{d.hp} HP  ·  {d.width:.2f} mm', fill='#d5e1e9', font=('Segoe UI', 11))
        c.create_text(x1+22, (y0+y1)/2, text='128,5 mm · 3U', angle=90, fill='#d5e1e9')
        c.create_text(x0, y1+17, text='0,0 mm', anchor='w', fill='#a4bbc9')
        self._draw_objects()

    def _reference_raster(self):
        """Flatten only the read-only PCB view; editable objects stay on Canvas."""
        width,height=max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height())
        aa=2 if width*height<=2_000_000 else 1
        image=Image.new('RGBA',(width*aa,height*aa),(0,0,0,0))
        if width<2 or height<2:return image.resize((width,height))
        paint=ImageDraw.Draw(image)
        scale=self.transform()[0]*aa
        d=self.document
        def xy(x,y):
            px,py=self.to_canvas(x+d.pcb_dx,y+d.pcb_dy)
            return px*aa,py*aa
        def stroke(a,b,color,width):
            width=max(aa,round(width));r=width/2
            paint.line((a,b),fill=color,width=width)
            for x,y in (a,b):paint.ellipse((x-r,y-r,x+r,y+r),fill=color)
        colors=['#879c9c','#5b8595','#9c9675','#799775']
        for layer_index,ref in enumerate(d.layers):
            if not ref.visible:continue
            drill=ref.coord_format is not None
            for p in ref.layer.drawables:
                color='#ce602b' if drill else '#000000' if p.get('polarity')=='clear' else colors[layer_index%len(colors)]
                if p['type']=='line':
                    stroke(xy(p['x1'],p['y1']),xy(p['x2'],p['y2']),color,p['width']*scale)
                elif p['type']=='region' and len(p['path'])>2:
                    paint.polygon([xy(*point) for point in p['path']],fill=color)
                elif p['type']=='flash':
                    x,y,sx,sy=p['x'],p['y'],p['sx']/2,p['sy']/2
                    box=(*xy(x-sx,y+sy),*xy(x+sx,y-sy))
                    if p['shape']=='R':paint.rectangle(box,fill=color)
                    elif p['shape']=='O':
                        a,b=(xy(x-sx+sy,y),xy(x+sx-sy,y)) if sx>=sy else (xy(x,y-sy+sx),xy(x,y+sy-sx))
                        stroke(a,b,color,2*min(sx,sy)*scale)
                    elif drill:
                        paint.ellipse(box,outline=color,width=aa)
                        px,py=xy(x,y)
                        paint.line((px-3*aa,py,px+3*aa,py),fill=color,width=aa)
                        paint.line((px,py-3*aa,px,py+3*aa),fill=color,width=aa)
                    else:paint.ellipse(box,fill=color)
        return image.resize((width,height),Image.Resampling.LANCZOS) if aa>1 else image

    def _draw_objects(self):
        c,d=self.canvas,self.document
        c.delete('editable');c.delete('selection')
        self._text_images.clear()
        scale=self.transform()[0]
        for i, obj in enumerate(d.elements):
            x, y = self.to_canvas(obj.x, obj.y)
            color = '#ffffff'
            tag = f'obj_{i}'
            if obj.kind == 'hole':
                radius = obj.size*scale/2
                c.create_oval(x-radius, y-radius, x+radius, y+radius,
                              fill='#17212b', outline=color, width=2, tags=(tag,'editable'))
                c.create_line(x-4, y, x+4, y, fill='#9db4c3', tags=(tag,'editable'))
                c.create_line(x, y-4, x, y+4, fill='#9db4c3', tags=(tag,'editable'))
            else:
                try:
                    mask=element_mask(obj)
                    image=Image.new('RGBA',mask.size,color);image.putalpha(mask)
                    image=image.resize((max(1,round(mask.width*PIXEL_MM*scale)),max(1,round(mask.height*PIXEL_MM*scale))),Image.Resampling.LANCZOS)
                    photo=ImageTk.PhotoImage(image,master=self);self._text_images.append(photo)
                    item=c.create_image(x,y,image=photo,tags=(tag,'editable'))
                except ValueError as error:
                    item=c.create_text(x,y,text=str(error),fill='#c34623',tags=(tag,'editable'))
        self._drawn_objects={i:id(obj) for i,obj in enumerate(d.elements)}
        self._draw_selection()
        if self.inline_editor is not None:
            self._place_inline_editor()

    def _draw_selection(self):
        self.canvas.delete('selection')
        for i in sorted(self.selection):
            box=self.canvas.bbox(f'obj_{i}')
            if box:
                self.canvas.create_rectangle(*box,outline='#c34623',dash=(3,2),
                    width=2 if i==self.selected else 1,tags=(f'obj_{i}','selection'))

    def confirm_discard(self):
        if not self.commit_inline():
            return False
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel('Guardar proyecto', 'Hay cambios sin guardar. ¿Quieres guardarlos?', parent=self)
        if answer is None:
            return False
        return self.save() if answer else True

    def save(self, save_as=False):
        if not self.commit_inline():
            return False
        path = self.project_path if not save_as else None
        if not path:
            folder=(Path(self.project_path).parent if self.project_path else
                    self.input_project_directory/'Sputtering'/'frontal' if self.input_project_directory else Path.home()/'Documents')
            if self.project_path or self.input_project_directory:folder.mkdir(parents=True,exist_ok=True)
            path = filedialog.asksaveasfilename(parent=self, title='Guardar proyecto de frontal',
                                               initialdir=str(folder),initialfile=Path(self.project_path).name if self.project_path else 'frontal.panel.json',
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
        path = filedialog.askopenfilename(parent=self, title='Abrir proyecto de frontal', filetypes=[('Proyecto frontal / módulo', '*.panel.json *.module.json')])
        if path:
            try:
                from module_migration import resolve_redirect
                path=str(resolve_redirect(path))
                from module_project import INDEX,stage_path
                if Path(path).name==INDEX:path=str(stage_path(Path(path).parent,'panel'))
                from pcb_project import load_project
                document = load_project(path)
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
        if not self.commit_inline():
            return
        issues = self.document.problems()
        if issues and not messagebox.askyesno('Revisar dimensiones', '\n'.join(issues[:6]) + '\n\n¿Exportar de todas formas?', parent=self):
            return
        from pcb_project import export_folder
        destination=export_folder(self.project_path,'frontal')
        path = filedialog.asksaveasfilename(parent=self, title='Exportar frontal SVG a escala 1:1',
                                           initialdir=str(destination) if destination else None,
                                           defaultextension='.svg', filetypes=[('SVG', '*.svg')])
        if path:
            reserved=False;registered=False
            try:
                from module_project import find_root,reserve_output,record_output
                if find_root(self.project_path):
                    if not self.save():return
                    path,reserved=reserve_output(self.project_path,path)
                atomic_write(path, self.document.svg())
                if reserved:
                    record_output(self.project_path,path,details=dict(type='editable_svg'));registered=True
                self.status.set('SVG exportado a escala 1:1. Incluye frontal, agujeros y textos; la PCB es solo referencia.')
            except (OSError,ValueError) as error:
                if reserved and not registered:Path(path).unlink(missing_ok=True)
                messagebox.showerror('Exportación SVG', str(error), parent=self)

    def _font_key(self):
        return next((k for k,v in FONTS.items() if v[0]==self.font_choice.get()),'sans')

    def _text_style(self):
        return dict(font=self._font_key(),angle=number(self.text_angle.get()),
                    width_scale=number(self.text_width.get(),25,400)/100,
                    tracking=number(self.text_tracking.get(),0,3),line_spacing=number(self.text_lines.get(),.6,3),
                    ink_gain=number(self.text_gain.get(),0,.3),
                    align={'Izquierda':'left','Centrado':'center','Derecha':'right'}[self.text_align.get()])

    def style_all_texts(self):
        self._style_texts({i for i, e in enumerate(self.document.elements) if e.kind == 'text'})

    def style_selected_texts(self):
        self._style_texts(self.selection)

    def _style_texts(self, indices):
        try:
            style=self._text_style();size=number(self.size.get(),.1,200)
            targets={i for i in indices if self.document.elements[i].kind=='text'}
            if not targets:
                self.status.set('Selecciona uno o varios textos para aplicar su estilo.');return
            updated=[replace(e,**style,size=size) if i in targets else e for i,e in enumerate(self.document.elements)]
            for i in targets:element_mask(updated[i])
            if updated==self.document.elements:return
            self.remember();self.document.elements=updated;self.changed()
            self.status.set(f'Estilo aplicado a {len(targets)} textos. Se conservan contenido, posiciones y vínculos. Deshacer recupera el estilo anterior.')
        except (ValueError,KeyError) as error:messagebox.showerror('Estilo de texto',str(error),parent=self)

    def change_case(self, uppercase=True):
        targets = {i for i in self.selection if self.document.elements[i].kind == 'text'}
        if not targets:
            self.status.set('Selecciona uno o varios textos del panel para cambiar mayúsculas o minúsculas.')
            return
        try:
            updated = list(self.document.elements)
            for i in targets:
                old = updated[i]
                updated[i] = replace(old, text=old.text.upper() if uppercase else old.text.lower())
                element_mask(updated[i])
            if updated == self.document.elements:
                return
            self.remember()
            self.document.elements = updated
            self._selection_fields()
            self.changed()
            self.status.set(f'{len(targets)} textos convertidos a ' + ('MAYÚSCULAS.' if uppercase else 'minúsculas.') + ' Deshacer recupera el contenido anterior.')
        except ValueError as error:
            messagebox.showerror('Cambiar texto', str(error), parent=self)

    def duplicate_selected(self):
        if not self.selection:return
        # A duplicate is independent; only the original keeps its automatic link.
        copies=[replace(self.document.elements[i],x=self.document.elements[i].x+2,y=self.document.elements[i].y-2,
                        source_ref='',source_footprint='',board_x=None,board_y=None) for i in sorted(self.selection)]
        start=len(self.document.elements)
        self.remember();self.document.elements.extend(copies);self.dirty=True
        self.selection=set(range(start,len(self.document.elements)));self._selected=start
        self._selection_fields();self.refresh()

    def export_gerber(self):
        if not self.commit_inline():
            return
        from panel_gerber import export_panel
        from pcb_project import export_folder
        win=tk.Toplevel(self);win.title('Exportar frontal para PCB');win.transient(self)
        frame=ttk.Frame(win,padding=16);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Frontal FR4 de 2 capas · serigrafía superior · agujeros sin metalizar\n'
                  'Incluye contorno, taladros, máscaras cerradas y geometría de los textos.\n'
                  'Las capas de la PCB de referencia no se exportan.',wraplength=490).pack(anchor='w')
        copper=tk.BooleanVar(value=True)
        ttk.Checkbutton(frame,text='Relleno de cobre bajo la máscara, separado de bordes y agujeros',variable=copper).pack(anchor='w',pady=10)
        ttk.Label(frame,text='Para el acabado blanco sobre negro: elegir máscara negra y serigrafía blanca al pedir.\n'
                  'Se crea un ZIP numerado, una vista SVG y un informe de comprobación.',wraplength=490).pack(anchor='w')
        def save_package():
            # A manufacturing ZIP is a snapshot; retain the editable state that
            # produced it before creating the next numbered package.
            if not self.save():return
            try:
                folder=export_folder(self.project_path,'frontal')
                if not folder:return
                name=Path(self.project_path).name.removesuffix('.panel.json') if self.project_path else 'frontal'
                path=export_panel(self.document,folder,name,copper.get(),project=self.project_path)
                self.status.set(f'Frontal exportado: {path}. Revisa la vista SVG y el visor CAM antes de pedir.')
                win.destroy()
                self.last_export_zip=path
                from export_result import show_export_result
                show_export_result(self,'Gerber del frontal creado',path,'Proyecto guardado. Revisa agujeros, textos y medidas en el visor de fabricación.')
            except (ValueError,OSError) as error:messagebox.showerror('Exportación Gerber',str(error),parent=win)
        ttk.Button(frame,text='Guardar proyecto y generar ZIP',command=save_package,
                   style='Primary.Panel.TButton').pack(pady=12)
        ttk.Button(frame,text='Cancelar',command=win.destroy).pack(pady=(0, 6))
        apply_theme(win, self._descendants)
        win.grab_set()

    def close(self):
        if self.confirm_discard():
            self.destroy()


class PanelEditor(PanelWorkspace, tk.Tk):
    """Explicit standalone panel mode; the main launcher opens the original UI."""


class PanelWindow(PanelWorkspace, tk.Toplevel):
    """Additional workspace that leaves the original Gerber editor alive."""


if __name__ == '__main__':
    PanelEditor(sys.argv[1:]).mainloop()
