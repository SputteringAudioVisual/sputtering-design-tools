"""Additive integration: the original silkscreen UI is the main application."""
import copy
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

from gerber_silkscreen_editor import GerberEditor
from panel_model import PanelDocument, Reference, load_references


class DesignToolsApp(GerberEditor):
    def __init__(self, paths=(), project=None):
        if project:
            from module_migration import resolve_redirect
            project=resolve_redirect(project)
        if project:
            from module_project import INDEX,stage_path,find_root
            if Path(project).name==INDEX:
                candidate=stage_path(Path(project).parent,'pcb_silkscreen')
                project=candidate if candidate.exists() else stage_path(Path(project).parent,'panel')
            elif str(project).endswith('.panel.json') and find_root(project):
                candidate=stage_path(find_root(project),'pcb_silkscreen')
                if candidate.exists():project=candidate
        self.drill_references = []
        self.panel_window = None
        self.panel_seed = None
        self.silk_project = None
        self.panel_project = None if project and str(project).lower().endswith('.silk.json') else project
        self.fabrication_source = None
        self.input_project_directory = None
        self.zoom = 1.0
        super().__init__()
        self.geometry('1200x750')
        # Original toolbar, conversion editor, controls and callbacks stay intact.
        menu = tk.Menu(self, bg='#252535', fg='white', activebackground='#3a3a5c')
        files=tk.Menu(menu,tearoff=False)
        files.add_command(label='Abrir proyecto…',command=self.choose_open_project,accelerator='Ctrl+O')
        files.add_command(label='Abrir Gerbers / ZIP…',command=self.choose_package)
        files.add_command(label='Guardar proyecto',command=self.save_current_project,accelerator='Ctrl+S')
        files.add_command(label='Guardar proyecto como…',command=lambda:self.save_current_project(True))
        menu.add_cascade(label='Archivo',menu=files)
        references = tk.Menu(menu, tearoff=False, bg='#252535', fg='white')
        references.add_command(label='Abrir PCB .brd y preparar proyecto…',command=self.choose_pcb_project)
        references.add_command(label='Guardar proyecto y sesión de imagen',command=self.save_current_project)
        references.add_command(label='Añadir PCB + drills (Gerber / Excellon / ZIP)…', command=self.choose_references)
        references.add_command(label='Añadir solo drills…', command=self.choose_drills)
        references.add_command(label='Importar textos de referencia en el frontal…',command=self.import_panel_texts)
        menu.add_cascade(label='PCB y referencias', menu=references)
        menu.add_command(label='Frontal Eurorack 3U…', command=self.open_panel)
        module=tk.Menu(menu,tearoff=False)
        module.add_command(label='Serigrafía de la PCB',command=lambda:self.open_module_stage('pcb_silkscreen'))
        module.add_command(label='Frontal del módulo',command=self.open_panel)
        module.add_command(label='Imagen del frontal',command=lambda:self.open_module_stage('panel_artwork'))
        module.add_command(label='Abrir carpeta del módulo',command=self.open_module_folder)
        module.add_command(label='Versiones y recuperación…',command=self.show_module_versions)
        module.add_command(label='Liberaciones y comparación…',command=self.show_release_history)
        menu.add_cascade(label='Módulo',menu=module)
        from loading_guide import show_guide
        help_menu=tk.Menu(menu,tearoff=False)
        help_menu.add_command(label='Guía rápida de carga…',command=lambda:show_guide(self))
        menu.add_cascade(label='Ayuda',menu=help_menu)
        self.config(menu=menu)
        row=tk.Frame(self,bg='#252535',padx=6,pady=4)
        row.pack(fill='x',before=self.winfo_children()[0])
        for label,command in [('Abrir proyecto…',self.choose_open_project),('Abrir Gerbers / ZIP…',self.choose_package),
                              ('Guardar proyecto',self.save_current_project),('Guardar como…',lambda:self.save_current_project(True))]:
            tk.Button(row,text=label,command=command,bg='#3a3a5c',fg='white',relief='flat',padx=10,pady=4,
                      font=('Segoe UI',10)).pack(side='left',padx=3)
        self.board_size=tk.StringVar(value='Sin contorno cargado')
        tk.Label(row,textvariable=self.board_size,bg='#252535',fg='#ffcc44',font=('Segoe UI',10,'bold')).pack(side='right',padx=8)
        self.project_location=tk.StringVar(value='Proyecto sin guardar')
        self.project_path_label=tk.Label(self,textvariable=self.project_location,bg='#252535',fg='#aaccdd',anchor='w',padx=10,font=('Segoe UI',9))
        self.project_path_label.pack(fill='x',after=row)
        self.fabrication_info=tk.StringVar(value='Sin liberación Gerber asociada')
        tk.Label(self,textvariable=self.fabrication_info,bg='#252535',fg='#ffcc66',anchor='w',padx=10,
                 font=('Segoe UI',9)).pack(fill='x',after=self.project_path_label)
        self.bind('<Control-s>',lambda e:self._save_shortcut())
        self.bind('<Control-Shift-S>',lambda e:self.save_current_project(True))
        self.bind('<Control-o>',lambda e:self._open_shortcut())
        if project and str(project).lower().endswith('.silk.json'):
            self.open_project_file(project)
        elif project:
            from pcb_project import load_project
            self.panel_seed = load_project(project)
            self.add_references(self.panel_seed.layers)
            from pcb_project import fabrication_source, export_folder
            self.fabrication_source=fabrication_source(project)
            self.fabrication_destination=export_folder(project,'serigrafia')
            self.restore_project_session()
        if paths:
            self.load_paths(paths)
        self.protocol('WM_DELETE_WINDOW',self.close_project)
        self.update_project_caption()

    def _save_shortcut(self):
        self.save_current_project();return 'break'

    def _open_shortcut(self):
        self.choose_open_project();return 'break'

    def choose_open_project(self):
        path=filedialog.askopenfilename(parent=self,title='Abrir proyecto o PCB',filetypes=[
            ('Proyecto / PCB / Gerbers','*.module.json *.silk.json *.panel.json *.brd *.zip'),
            ('PCB Allegro','*.brd'),('Proyecto guardado','*.module.json *.silk.json *.panel.json'),('Gerbers','*.zip')])
        if path:
            try:self.load_paths([path])
            except (OSError,ValueError,KeyError) as error:messagebox.showerror('Abrir proyecto',str(error),parent=self)

    def choose_package(self):
        paths=filedialog.askopenfilenames(parent=self,title='Abrir Gerbers o paquete de fabricación',
            filetypes=[('Gerbers / ZIP','*.zip *.gto *.gbo *.gko *.gtl *.gbl *.gts *.gbs *.art *.gbr *.ger *.drl *.rou')])
        if paths:self.load_paths(paths,replace=True)

    def _before_replace(self):
        if not self._commit_conversion_editor():return False
        if self.panel_window is not None and self.panel_window.winfo_exists():
            messagebox.showinfo('Frontal abierto','Cierra primero la ventana del frontal para cambiar de proyecto.',parent=self)
            return False
        if self.overlay_image is not None and not(self.silk_project or self.panel_project):
            answer=messagebox.askyesnocancel('Guardar edición','La imagen aún no está guardada en un proyecto. ¿Quieres guardarla antes de cambiar?',parent=self)
            if answer is None:return False
            if answer and not self.save_current_project():return False
        else:
            try:self.save_project_session()
            except (OSError,ValueError) as error:
                messagebox.showerror('Guardar proyecto',str(error),parent=self);return False
        return True

    def _reset_image_session(self):
        editor=getattr(self,'_conv_editor',None)
        if editor is not None and editor.winfo_exists():editor.destroy()
        self._cancel_main_preview()
        self.overlay_image=None;self.overlay_svg_path=None;self.overlay_image_path=''
        self.logo_targets=[];self._export_preferences={}
        self._conv_algo='threshold';self._conv_contrast=1.;self._conv_invert=False;self._conv_pxsize=.15
        self._conv_tuning={};self.overlay_threshold.set(128)
        self.zoom=1.;self.pan_x=0.;self.pan_y=0.;self.align_ref_var.set('pcb')
        self._overlay_cache_key=None;self._logo_raster_cache={}
        self._board_contours_key=None

    def open_project_file(self,path):
        from module_migration import resolve_redirect
        path=resolve_redirect(path)
        from module_project import INDEX,stage_path
        if path.name==INDEX:
            candidate=stage_path(path.parent,'pcb_silkscreen')
            path=candidate if candidate.exists() else stage_path(path.parent,'panel')
        elif path.name.endswith('.panel.json'):
            from module_project import find_root
            root=find_root(path)
            if root:
                candidate=stage_path(root,'pcb_silkscreen')
                if candidate.exists():path=candidate
        if str(path).lower().endswith('.silk.json'):
            from silkscreen_project import load
            refs,state,views,source,view=load(path)
            seed=None
        else:
            from pcb_project import load_project,fabrication_source,export_folder
            seed=load_project(path);refs=seed.layers;source=fabrication_source(path)
            state=None;views={};view={}
        if not self._before_replace():return False
        self._reset_image_session();self.clear_layers()
        self.silk_project=path if seed is None else None
        self.panel_project=path if seed is not None else None
        self.panel_seed=seed
        self.fabrication_source=source
        from pcb_project import export_folder
        self.fabrication_destination=export_folder(path,'serigrafia')
        self.add_references(refs,redraw=False)
        for entry in self.gerber_layers:
            values=views.get(entry['name'],{})
            entry['color']=values.get('color',entry['color']);entry['var_bbox'].set(values.get('bbox',False))
        self.restore_project_session(state,path.parent,redraw=False)
        self.align_ref_var.set(view.get('alignment','pcb'))
        for key in ('zoom','pan_x','pan_y'):
            if key in view:setattr(self,key,view[key])
        self._rebuild_layers_panel();self._redraw();self.update_project_caption()
        return True

    def save_current_project(self,save_as=False):
        if not self._commit_conversion_editor():return False
        previous=self.silk_project
        try:
            if save_as or not(self.silk_project or self.panel_project):
                import re
                stem=(self.silk_project.name.removesuffix('.silk.json') if self.silk_project else
                      Path(self.fabrication_source).stem if self.fabrication_source else 'serigrafia')
                stem=re.sub(r'^[0-9a-f]{16}_','',stem)
                stem=re.sub(r'_gerbers_v\d+$','',stem)
                if not stem.endswith('_arte'):stem+='_arte'
                from module_project import find_root,cad_project_root
                module=find_root(self.silk_project or self.panel_project or self.fabrication_source)
                folder=(Path(self.silk_project).parent if self.silk_project else module/'serigrafia_pcb' if module else
                        cad_project_root(self.fabrication_source)/'Sputtering'/stem if self.fabrication_source else
                        self.input_project_directory/'Sputtering'/stem if self.input_project_directory else Path.home()/'Documents')
                if self.fabrication_source or self.input_project_directory or module:folder.mkdir(parents=True,exist_ok=True)
                path=filedialog.asksaveasfilename(parent=self,title='Guardar proyecto de serigrafía',
                    initialdir=str(folder),initialfile=stem+'.silk.json',defaultextension='.silk.json',filetypes=[('Proyecto de serigrafía','*.silk.json')])
                if not path:return False
                self.silk_project=Path(path)
            self.save_project_session()
            if self.silk_project:
                self.panel_project=None;self.panel_seed=None
                from pcb_project import export_folder
                self.fabrication_destination=export_folder(self.silk_project,'serigrafia')
            self.update_project_caption()
            self.info_var.set('Proyecto guardado: '+str(self.silk_project or self.panel_project))
            return True
        except (OSError,ValueError) as error:
            self.silk_project=previous
            messagebox.showerror('Guardar proyecto',str(error),parent=self);return False

    def update_project_caption(self):
        if not hasattr(self,'board_size'):return
        from panel_model import geometry_bounds
        entry=self._find_outline_layer()
        if entry and entry['layer'].drawables:
            b=geometry_bounds(entry['layer'],outline=True)
            front='FRONT PANEL' in ''.join(entry['layer'].raw_lines[:10]).upper()
            self.board_size.set(f'{"Frontal" if front else "Contorno PCB"}: {b[2]-b[0]:.2f} × {b[3]-b[1]:.2f} mm')
        else:self.board_size.set('Sin contorno cargado')
        name=self.silk_project or self.panel_project or self.fabrication_source
        self.title('Sputtering Design Tools · Serigrafías'+(' · '+Path(name).name if name else ''))
        project=self.silk_project or self.panel_project
        self.project_location.set(('Proyecto de serigrafía: ' if self.silk_project else 'Sesión de imagen de la PCB: ')+str(project)
                                  if project else 'Proyecto sin guardar · Guardar proyecto conserva capas, imagen y ajustes.')
        from module_project import find_root,read,stage_for,STAGES
        root=find_root(project)
        if root:
            data=read(root);stage=stage_for(project,data);entry=data['stages'][stage]
            self.project_location.set(f"{data['name']} · {STAGES[stage]} · Guardado {entry['revision']:04d} · {project}")
        if hasattr(self,'fabrication_info'):
            source=self.fabrication_source
            if source:
                from release_contract import association,caption
                from pcb_project import project_info
                try:
                    stat=Path(source).stat();key=(str(source),stat.st_size,stat.st_mtime_ns)
                    if getattr(self,'_association_key',None)!=key:
                        self._association_value=association(source);self._association_key=key
                    meta=project_info(project) if project else None
                    check=meta.get('fabrication_check') if meta else None
                    note={'identity_and_source_hash':' · identidad y BRD verificados; añade reglas de footprint para proponer agujeros',
                          'explicit_outline_only':' · paquete histórico; se alineó por contorno, revisa taladros y serigrafía'}
                    self.fabrication_info.set('Origen: '+caption(self._association_value,root,self.input_project_directory)+note.get(check,''))
                except (OSError,ValueError) as error:self.fabrication_info.set('Liberación no válida: '+str(error))
            else:self.fabrication_info.set('Sin liberación Gerber asociada')

    def choose_pcb_project(self):
        path=filedialog.askopenfilename(parent=self,title='Abrir PCB y preparar proyecto local',filetypes=[('PCB Allegro','*.brd')])
        if path:self.load_paths([path])

    def close_project(self):
        if self._commit_conversion_editor():
            try:
                if self.overlay_image is not None and not(self.silk_project or self.panel_project):
                    if not self.save_current_project():return
                else:self.save_project_session()
            except (OSError,ValueError) as error:
                messagebox.showerror('Guardar proyecto',str(error),parent=self);return
            if self.panel_window is not None and self.panel_window.winfo_exists() and not self.panel_window.confirm_discard():return
            self.destroy()

    def save_project_session(self):
        from image_tuning import validate_tuning
        from pcb_project import project_info,local_path
        from panel_model import atomic_write
        import io
        import hashlib
        if not self.silk_project and not self.panel_project:return False
        from module_project import find_root,stage_path
        module=find_root(self.silk_project or self.panel_project)
        if module and not self.silk_project:
            self.silk_project=stage_path(module,'pcb_silkscreen')
        root=Path(self.silk_project or self.panel_project).parent
        root.mkdir(parents=True,exist_ok=True);(root/'assets').mkdir(exist_ok=True)
        preferences={}
        for key,value in getattr(self,'_export_preferences',{}).items():
            if isinstance(key,tuple) and len(key)==4:
                key=self._export_preference_key(dict(tag=key[1],ext=key[2],is_new=key[3]))
            preferences[key]=value
        self._export_preferences=preferences
        state={'schema':'sputtering.image-session.v1','enabled':self.overlay_image is not None,
               'targets':self.logo_targets,'preferences':preferences}
        if self.overlay_image is not None:
            buffer=io.BytesIO();self.overlay_image.save(buffer,format='PNG');raw=buffer.getvalue()
            image='assets/'+hashlib.sha256(raw).hexdigest()[:16]+'.png'
            path=local_path(root,image)
            if not path.exists():path.write_bytes(raw)
            state.update(image=image,x_mm=self.overlay_x_mm,y_mm=self.overlay_y_mm,
                width_mm=self.overlay_w_mm,height_mm=self.overlay_h_mm,angle_deg=self.overlay_angle_deg,
                threshold=self.overlay_threshold.get(),algorithm=getattr(self,'_conv_algo','threshold'),
                contrast=getattr(self,'_conv_contrast',1.),invert=getattr(self,'_conv_invert',False),
                tuning=validate_tuning(getattr(self,'_conv_tuning',None)),
                pixel_mm=getattr(self,'_conv_pxsize',.15),dot_mm=float(self.entry_dot.get()),
                targets=self.logo_targets,preferences=preferences)
            vector=getattr(self,'overlay_svg_path',None)
            if vector:
                raw=Path(vector).read_bytes();name='assets/'+hashlib.sha256(raw).hexdigest()[:16]+'.svg'
                target=local_path(root,name)
                if not target.exists():target.write_bytes(raw)
                state['svg']=name
        if self.silk_project:
            from silkscreen_project import save
            refs=[Reference(e['name'],''.join(e['layer'].raw_lines),visible=e['var_visible'].get()) for e in self.gerber_layers]
            refs += [Reference(r.name,r.content,visible=r.variable.get(),coord_format=r.coord_format) for r in self.drill_references]
            views={e['name']:dict(color=e['color'],bbox=e['var_bbox'].get()) for e in self.gerber_layers}
            self.fabrication_source=save(self.silk_project,refs,state,views,self.fabrication_source,
                 dict(zoom=self.zoom,pan_x=self.pan_x,pan_y=self.pan_y,alignment=self.align_ref_var.get()))
            from pcb_project import export_folder
            self.fabrication_destination=export_folder(self.silk_project,'serigrafia')
        else:atomic_write(self._image_session_path(),json.dumps(state,ensure_ascii=False,indent=2))
        self.update_project_caption()
        return True

    def _image_session_path(self):
        from pcb_project import project_info
        path=Path(self.panel_project)
        # Standalone panel files can share a folder: keep their image sessions
        # separate instead of borrowing another module's image_session.json.
        name='image_session.json' if project_info(path) else path.name.removesuffix('.panel.json')+'.image_session.json'
        return path.parent/name

    def restore_project_session(self,state=None,root=None,redraw=True):
        from image_tuning import validate_tuning
        from pcb_project import project_info,local_path
        from panel_model import number
        from PIL import Image
        if state is None:
            if not self.panel_project:return
            from module_project import find_root,stage_path
            module=find_root(self.panel_project)
            saved=stage_path(module,'pcb_silkscreen') if module else None
            if saved and saved.exists():
                from silkscreen_project import load
                state=load(saved)[1];root=saved.parent;self.silk_project=saved
            else:
                root=Path(self.panel_project).parent;path=self._image_session_path()
                if not path.exists():return
                state=json.loads(path.read_text(encoding='utf-8'))
        from silkscreen_project import read_session
        if state.get('enabled') and '_image' not in state:state=read_session(root,state)
        self.overlay_image=None;self.overlay_svg_path=None
        if state.get('schema')!='sputtering.image-session.v1':raise ValueError('Sesión de imagen desconocida.')
        self.logo_targets=state.get('targets',[]);self._export_preferences=state.get('preferences',{})
        if not state['enabled']:
            if redraw:self._redraw()
            return
        values={k:number(state[k]) for k in ('x_mm','y_mm','width_mm','height_mm','angle_deg')}
        if values['width_mm']<=0 or values['height_mm']<=0:raise ValueError('Tamaño de imagen inválido.')
        if state['algorithm'] not in {'threshold','floyd','floyd_fast','atkinson','bayer2','bayer4','bayer8','clustered4','stucki','jarvis'}:raise ValueError('Conversión desconocida.')
        threshold=number(state['threshold'],0,255);contrast=number(state['contrast'],.3,3)
        pixel=number(state['pixel_mm'],.15,100);dot=number(state['dot_mm'],.15,100)
        self.overlay_image=state['_image']
        self.overlay_image_path=state['_image_path']
        self.overlay_svg_path=state['_svg_path']
        for key,value in values.items():
            attribute={'width_mm':'w_mm','height_mm':'h_mm'}.get(key,key)
            setattr(self,'overlay_'+attribute,value)
        self.overlay_threshold.set(int(threshold));self._conv_algo=state['algorithm'];self._conv_contrast=contrast
        self._conv_invert=bool(state['invert']);self._conv_pxsize=pixel
        self._conv_tuning=validate_tuning(state.get('tuning'))
        self.logo_targets=state.get('targets',[]);self._export_preferences=state.get('preferences',{})
        self.entry_dot.delete(0,'end');self.entry_dot.insert(0,str(dot))
        self._sync_controls_to_state();self._overlay_cache_key=None
        if redraw:self._redraw()

    def choose_references(self):
        paths = filedialog.askopenfilenames(parent=self, title='Añadir PCB, serigrafía y drills',
                                           filetypes=[('PCB / referencias', '*.brd *.art *.gbr *.ger *.gto *.gbo *.gko *.drl *.rou *.xln *.exc *.zip *.txt'), ('Todos', '*.*')])
        if paths:
            self.load_paths(paths)

    def choose_drills(self):
        paths = filedialog.askopenfilenames(parent=self, title='Añadir drills Excellon (nc_param.txt se detecta al lado)',
                                           filetypes=[('Excellon / parámetros', '*.drl *.xln *.exc *.txt'), ('Todos', '*.*')])
        if paths:
            self.load_paths(paths)

    def load_paths(self, paths,replace=False,fabrication=None,offer_panel=False):
        if len(paths)==1 and Path(paths[0]).suffix.lower()=='.zip':
            from module_project import adopt_package
            try:
                project=adopt_package(paths[0])
                if project:return self.open_project_file(project)
            except (OSError,ValueError) as error:
                messagebox.showerror('Abrir paquete del módulo',str(error),parent=self);return False
        if len(paths)==1 and str(paths[0]).lower().endswith(('.silk.json','.panel.json','.module.json')):
            return self.open_project_file(paths[0])
        if len(paths)==1 and Path(paths[0]).suffix.lower()=='.brd':
            from pcb_project import prepare_project,fabrication_source,export_folder
            if self.panel_window is not None and self.panel_window.winfo_exists():
                messagebox.showinfo('Proyecto abierto','Carga la PCB desde el frontal abierto para conservar su edición.',parent=self);return
            self.info_var.set('Preparando proyecto y localizando fabricación…');self.update_idletasks()
            try:
                if not self._commit_conversion_editor():return
                self.save_project_session()
                from pcb_project import load_project,project_info,local_path
                current=self.panel_project
                seed=load_project(current) if current else self.panel_seed
                info=project_info(current)
                if info:
                    incoming=Path(paths[0]).resolve()
                    sources={Path(info['source_board']).resolve(),local_path(Path(current).parent,info['pcb'])}
                    if incoming not in sources:
                        if not self._before_replace():return
                        current=None;seed=None
                prepared=prepare_project(paths[0],seed,current,fabrication=fabrication)
                self._reset_image_session();self.silk_project=None
                self.clear_layers()
                self.panel_seed=prepared['document'];self.panel_project=prepared['project_path']
                self.fabrication_source=fabrication_source(self.panel_project)
                self.fabrication_destination=export_folder(self.panel_project,'serigrafia')
                self.add_references(self.panel_seed.layers)
                self.restore_project_session()
                self.save_project_session()
                self.info_var.set('Proyecto local: '+str(Path(self.panel_project).parent))
            except (OSError,ValueError) as error:
                if fabrication is None and messagebox.askyesno('Seleccionar ZIP de fabricación',
                    str(error)+'\n\n¿Quieres seleccionar el ZIP que acabas de generar en Allegro?',parent=self):
                    selected=filedialog.askopenfilename(parent=self,title='Elegir liberación de fabricación',
                        initialdir=str(Path(paths[0]).parent),filetypes=[('ZIP de fabricación','*.zip'),('Todos los archivos','*.*')])
                    if selected:
                        return self.load_paths([paths[0]],fabrication=selected,offer_panel=offer_panel)
                messagebox.showerror('Proyecto PCB',str(error),parent=self)
                return False
            if offer_panel and messagebox.askyesno('Proyecto listo',
                'La serigrafía está abierta y vinculada a su liberación Allegro. ¿Quieres abrir ahora el frontal del módulo en otra ventana?',parent=self):
                self.open_panel()
            return True
        refs, errors = load_references(paths)
        package=len(paths)==1 and Path(paths[0]).suffix.lower()=='.zip'
        if errors and (replace or package):
            messagebox.showerror('Carga de referencias','\n'.join(errors[:8]),parent=self);return False
        if (replace or package) and not refs:
            messagebox.showerror('Carga de referencias','No se han encontrado capas Gerber o taladros en estos archivos.',parent=self)
            return False
        if replace or package:
            if not self._before_replace():return False
            self._reset_image_session();self.clear_layers()
            self.panel_seed=None;self.panel_project=None;self.silk_project=None
        self.add_references(refs)
        if refs and not self.input_project_directory:
            from module_project import cad_project_root
            self.input_project_directory=cad_project_root(paths[0])
        if not errors and package:
            self.fabrication_source = Path(paths[0])
        self.update_project_caption()
        if errors:
            messagebox.showwarning('Carga de referencias', '\n'.join(errors[:8]), parent=self)

    def add_references(self, references,redraw=True):
        for ref in references:
            if ref.coord_format is not None:
                ref = copy.deepcopy(ref)
                ref.variable = tk.BooleanVar(self, value=ref.visible)
                self.drill_references.append(ref)
            else:
                self.gerber_layers.append({'layer': ref.layer, 'name': ref.name,
                    'color': self._default_layer_color(ref.name, ref.layer),
                    'var_visible': tk.BooleanVar(self, value=ref.visible),
                    'var_bbox': tk.BooleanVar(self, value=False)})
        if self.gerber_layers:
            self.gerber_layer = self.gerber_layers[0]['layer']
        self._rebuild_layers_panel()
        if redraw:self.fit_view()
        count = sum(len(r.layer.drawables) for r in self.drill_references)
        self.info_var.set(f'{len(self.gerber_layers)} capas · {count} drills de referencia')
        self.update_project_caption()

    def _rebuild_layers_panel(self):
        super()._rebuild_layers_panel()
        self.update_project_caption()
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
                if hit['shape']=='O':
                    rx,ry=hit['sx']/2,hit['sy']/2
                    if rx>=ry:
                        ends=(*self._mm_to_canvas(hit['x']-rx+ry,hit['y']),*self._mm_to_canvas(hit['x']+rx-ry,hit['y']))
                    else:
                        ends=(*self._mm_to_canvas(hit['x'],hit['y']-ry+rx),*self._mm_to_canvas(hit['x'],hit['y']+ry-rx))
                    self.canvas.create_line(*ends,fill='#ff9955',width=max(1,min(hit['sx'],hit['sy'])*scale),capstyle='round',tags='drill_reference')
                    continue
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
        self.input_project_directory=None
        self.fabrication_source = None
        self.fabrication_destination = None
        self.drill_references.clear()
        super().clear_layers()

    def open_panel(self):
        if self.panel_window is not None and self.panel_window.winfo_exists():
            self.panel_window.deiconify()
            self.panel_window.lift()
            return
        from panel_editor import PanelWindow
        try:
            from module_project import module_panel
            panel=module_panel(self.silk_project or self.panel_project or self.fabrication_source)
            if panel and panel.exists():
                self.panel_window=PanelWindow(master=self,project=panel)
                return
            document = copy.deepcopy(self.panel_seed) if self.panel_seed else PanelDocument()
            references = [Reference(e['name'], ''.join(e['layer'].raw_lines), visible=e['var_visible'].get())
                          for e in self.gerber_layers]
            for ref in self.drill_references:
                references.append(Reference(ref.name, ref.content, visible=ref.variable.get(), coord_format=ref.coord_format))
            document.layers = references
            document.choose_outline()
            if self.panel_seed is None:document.center_pcb()
            self.panel_window = PanelWindow(master=self, document=document, project=self.panel_project)
            self.info_var.set('Frontal abierto aparte · tu edición de serigrafía sigue aquí')
        except ValueError as error:
            messagebox.showerror('Referencia del frontal', str(error), parent=self)

    def import_panel_texts(self):
        """Reuse the front-panel text importer and its modal window lifecycle."""
        self.open_panel()
        if self.panel_window is not None and self.panel_window.winfo_exists():
            self.panel_window.import_refdes()

    def open_module_folder(self):
        from module_project import find_root
        root=find_root(self.silk_project or self.panel_project or self.fabrication_source)
        if root:
            import os
            os.startfile(str(root))
        else:messagebox.showinfo('Módulo','Carga primero una PCB o un proyecto de módulo.',parent=self)

    def show_module_versions(self):
        from module_versions import show_versions
        def before():
            if self.panel_window is not None and self.panel_window.winfo_exists():
                messagebox.showinfo('Frontal abierto','Guarda y cierra el frontal antes de recuperar una revisión.',parent=self);return False
            return self.save_current_project()
        def reload(path):
            self._reset_image_session();self.silk_project=None;self.panel_project=None
            self.open_project_file(path)
            if str(path).endswith('.panel.json'):self.open_panel()
        show_versions(self,self.silk_project or self.panel_project,before,reload)

    def show_release_history(self):
        from module_versions import show_releases
        def before():
            if self.panel_window is not None and self.panel_window.winfo_exists():
                messagebox.showinfo('Frontal abierto','Guarda y cierra el frontal antes de recuperar una edición.',parent=self);return False
            return self.save_current_project()
        def reload(path):
            self._reset_image_session();self.silk_project=None;self.panel_project=None
            self.open_project_file(path)
        show_releases(self,self.silk_project or self.panel_project or self.fabrication_source,before,reload)

    def open_module_stage(self,stage):
        from module_project import find_root,stage_path,continue_panel_artwork
        root=find_root(self.silk_project or self.panel_project or self.fabrication_source)
        if root is None:
            messagebox.showinfo('Módulo','Carga primero una PCB o un proyecto de módulo.',parent=self);return
        if not self.save_current_project():return
        path=stage_path(root,stage)
        try:
            if stage=='panel_artwork' and not path.exists():
                from panel_editor import PanelWindow
                self.open_panel();self.panel_window.edit_artwork();return
            if stage=='pcb_silkscreen' and not path.exists():path=stage_path(root,'panel')
            self.open_project_file(path)
        except (OSError,ValueError) as error:messagebox.showerror('Abrir etapa del módulo',str(error),parent=self)
