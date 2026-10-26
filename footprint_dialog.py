"""Reviewable footprint-driven placement, added to the existing panel workflow."""
import copy
import math
import json
from collections import Counter
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from footprint_holes import DEFAULT_RULES, read_pcb, proposals, validate_rules
from panel_model import HOLE_PRESETS, HEIGHT_MM, atomic_write
from panel_fonts import FONTS, text_mask, PIXEL_MM
from PIL import Image, ImageTk

ANCHOR_LABELS = {'mechanical_pair': 'Centro entre 2 anclajes mecánicos',
                 'padstack': 'Centro del padstack indicado', 'pin': 'Centro del pin indicado',
                 'origin': 'Origen del footprint'}


class FootprintDialog(tk.Toplevel):
    def __init__(self, owner, mode='holes'):
        super().__init__(owner)
        self.owner = owner
        self.mode = mode
        self.title('Importar textos desde .brd' if mode == 'texts' else 'Agujeros desde footprints de la PCB')
        self.geometry('1100x720')
        self.minsize(950,620)
        self.configure(bg='#252535')
        self.transient(owner)
        self.data = copy.deepcopy(owner.document.component_data)
        self.rules = copy.deepcopy(DEFAULT_RULES)
        self.rules.update(copy.deepcopy(owner.document.footprint_rules))
        self.items, self.checked = {}, set()
        self.closed, self.busy, self.poll_id = False, False, None
        self.status = tk.StringVar(value='Carga una PCB .brd guardada o una referencia de componentes JSON.')
        self.footprint, self.kind = tk.StringVar(), tk.StringVar()
        self.diameter, self.anchor, self.value, self.side = [tk.StringVar() for _ in range(4)]
        self.text_size = tk.StringVar(value='2.5')
        self.text_gap = tk.StringVar(value='1.0')
        self.text_position = tk.StringVar(value='Encima')
        self.text_font = tk.StringVar(value=FONTS['sans'][0])
        self.preview_images=[]
        top=ttk.Frame(self,padding=10);top.pack(fill='x')
        self.read_button=ttk.Button(top,text='Leer PCB / referencia…',command=self.choose_source)
        self.read_button.pack(side='left')
        ttk.Label(top,textvariable=self.status,wraplength=810).pack(side='left',padx=10)
        ttk.Label(self,text=('Importa el refdes de los componentes con agujero como texto editable. Las etiquetas existentes se conservan.' if mode == 'texts' else
                  'Revisa los centros y diámetros. Doble clic o Espacio marca/desmarca. Los círculos violetas son una previsualización.'),
                  wraplength=1050).pack(anchor='w',padx=12,pady=5)
        if mode == 'texts':
            options=ttk.Frame(self,padding=(10,5));options.pack(fill='x')
            for label,var in [('Altura de texto (mm)',self.text_size),('Separación del borde del agujero (mm)',self.text_gap)]:
                ttk.Label(options,text=label).pack(side='left',padx=4)
                ttk.Entry(options,textvariable=var,width=7).pack(side='left',padx=4)
            ttk.Combobox(options,textvariable=self.text_position,state='readonly',values=['Encima','Debajo'],width=9).pack(side='left',padx=4)
            ttk.Button(options,text='Actualizar previsualización',command=self.refresh).pack(side='left',padx=4)
            fontrow=ttk.Frame(self,padding=(10,0));fontrow.pack(fill='x')
            ttk.Label(fontrow,text='Tipografía:').pack(side='left',padx=4)
            ttk.Combobox(fontrow,textvariable=self.text_font,state='readonly',width=30,
                         values=[v[0] for v in FONTS.values()]).pack(side='left',padx=4)
        frame=ttk.Frame(self,padding=(10,0));frame.pack(fill='both',expand=True)
        columns=('use','ref','footprint','kind','x','y','diameter','action')
        self.table=ttk.Treeview(frame,columns=columns,show='headings',height=14,selectmode='browse')
        for key,label,width in zip(columns,['Usar','Componente','Footprint','Tipo','X panel','Y panel','Ø mm','Acción'],
                                   [45,85,180,115,80,80,65,230]):
            self.table.heading(key,text=label);self.table.column(key,width=width,minwidth=40)
        if mode == 'texts':self.table.heading('diameter',text='Altura mm')
        scroll=ttk.Scrollbar(frame,orient='vertical',command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.table.pack(fill='both',expand=True)
        self.table.bind('<Double-Button-1>',self.toggle)
        self.table.bind('<space>',self.toggle)
        self.table.bind('<<TreeviewSelect>>',self.select_row)
        rule=ttk.LabelFrame(self,text='Regla de tu biblioteca · se guarda con el proyecto',padding=8)
        rule.pack(fill='x',padx=10,pady=8)
        self.rule_combo=ttk.Combobox(rule,textvariable=self.footprint,state='readonly',width=22)
        self.rule_combo.grid(row=0,column=0,sticky='ew',padx=3)
        self.rule_combo.bind('<<ComboboxSelected>>',self.load_rule)
        self.kind_combo=ttk.Combobox(rule,textvariable=self.kind,state='readonly',width=18,
            values=[HOLE_PRESETS[k][2] for k in ('potentiometer','jack','spdt','custom')])
        self.kind_combo.grid(row=0,column=1,padx=3)
        ttk.Label(rule,text='Ø mm').grid(row=0,column=2)
        ttk.Entry(rule,textvariable=self.diameter,width=7).grid(row=0,column=3,padx=3)
        ttk.Combobox(rule,textvariable=self.side,state='readonly',values=['TOP','BOTTOM'],width=9).grid(row=0,column=4,padx=3)
        ttk.Combobox(rule,textvariable=self.anchor,state='readonly',values=list(ANCHOR_LABELS.values()),width=35).grid(row=1,column=0,columnspan=2,sticky='ew',padx=3,pady=5)
        ttk.Label(rule,text='Pin / padstack').grid(row=1,column=2,columnspan=2)
        ttk.Entry(rule,textvariable=self.value,width=22).grid(row=1,column=4,padx=3)
        ttk.Button(rule,text='Guardar regla y recalcular',command=self.save_rule).grid(row=1,column=5,padx=5)
        ttk.Label(rule,text='El centro se obtiene de los pines reales, con su giro y cara ya aplicados. Los diámetros de las plantillas son editables.',
                  wraplength=1000).grid(row=2,column=0,columnspan=6,sticky='w')
        ttk.Button(rule,text='Importar biblioteca de reglas…',command=self.import_rules).grid(row=3,column=0,columnspan=2,sticky='w',pady=5)
        ttk.Button(rule,text='Exportar biblioteca de reglas…',command=self.export_rules).grid(row=3,column=4,columnspan=2,sticky='e',pady=5)
        if mode == 'texts':rule.pack_forget()
        bottom=ttk.Frame(self,padding=10);bottom.pack(fill='x')
        ttk.Button(bottom,text='Marcar todos válidos',command=lambda:self.mark_all(True)).pack(side='left',padx=3)
        ttk.Button(bottom,text='Desmarcar todos',command=lambda:self.mark_all(False)).pack(side='left',padx=3)
        ttk.Button(bottom,text='Cancelar',command=self.close).pack(side='right',padx=3)
        self.apply_button=ttk.Button(bottom,text='Aplicar seleccionados',command=self.apply,state='disabled')
        self.apply_button.pack(side='right',padx=3)
        for widget in owner._descendants(self):
            if isinstance(widget,ttk.Widget):
                try:widget.configure(style='Panel.'+widget.winfo_class())
                except tk.TclError:pass
        style=ttk.Style(self)
        style.configure('Panel.Treeview',background='#1a1a2e',fieldbackground='#1a1a2e',foreground='#e0e0ed',rowheight=24)
        style.map('Panel.Treeview',background=[('selected','#334c88')],foreground=[('selected','white')])
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh()
        self.grab_set()

    def choose_source(self):
        path=filedialog.askopenfilename(parent=self,title='Leer posiciones y footprints de una PCB guardada',
            filetypes=[('PCB Allegro / referencia de componentes','*.brd *.json'),('Todos','*.*')])
        if path:self.start_read(path)

    def start_read(self,path):
        if self.busy:return
        self.busy=True
        self.read_button.configure(state='disabled');self.apply_button.configure(state='disabled')
        self.status.set('Leyendo la PCB sin modificarla…')
        self.results=queue.Queue()
        def work():
            try:self.results.put((True,read_pcb(path)))
            except Exception as error:self.results.put((False,str(error)))
        threading.Thread(target=work,daemon=True).start()
        self.poll_id=self.after(100,self.poll)

    def poll(self):
        if self.closed:return
        try:ok,value=self.results.get_nowait()
        except queue.Empty:
            self.poll_id=self.after(100,self.poll);return
        self.poll_id=None;self.busy=False;self.read_button.configure(state='normal')
        if ok:self.data=value;self.refresh()
        else:
            self.status.set('No se ha cambiado el proyecto.')
            messagebox.showerror('Referencia de PCB',value,parent=self)
            self.refresh()

    def refresh(self):
        self.owner.canvas.delete('footprint_preview')
        self.table.delete(*self.table.get_children());self.items.clear();self.checked.clear()
        if self.data is None:return
        names=sorted({c['footprint'] for c in self.data['components']})
        self.rule_combo.configure(values=names)
        if self.footprint.get() not in names:
            self.footprint.set(next((n for n in names if n in self.rules),names[0] if names else ''))
        self.load_rule()
        try:
            drills=[(p['x'],p['y']) for r in self.owner.document.layers if r.coord_format for p in r.layer.drawables]
            candidates,skipped=proposals(self.data,self.rules,self.owner.document.reference_bounds(),drills)
            labels = {}
            if self.mode == 'texts':
                labels = {e.source_ref:e for e in self.owner.document.refdes_labels(self.data,self.rules,**self.text_options())[0]}
        except ValueError as error:
            self.status.set(str(error));self.apply_button.configure(state='disabled');return
        d=self.owner.document
        owned={e.source_ref for e in d.elements if e.kind=='hole' and e.source_ref}
        for item in candidates:
            x,y=item['x_mm']+d.pcb_dx,item['y_mm']+d.pcb_dy;r=item['diameter_mm']/2
            outside=not(r<=x<=d.width-r and r<=y<=HEIGHT_MM-r)
            if self.mode == 'texts':
                self.add_text_row(item,labels[item['refdes']])
                continue
            manual=any(e.kind=='hole' and not e.source_ref and math.hypot(e.x-x,e.y-y)<.05 for e in d.elements)
            overlap=any(e.kind=='hole' and not e.source_ref and math.hypot(e.x-x,e.y-y)<(e.size+item['diameter_mm'])/2
                        for e in d.elements)
            action=('Fuera del frontal' if outside else 'Manual existente: conservar' if manual and item['refdes'] not in owned
                    else 'Solapa agujero manual: revisar' if overlap
                    else 'Actualizar' if item['refdes'] in owned else 'Añadir')
            valid=not outside and not overlap
            ref=item['refdes'];self.items[ref]=(item,valid,action)
            if valid:self.checked.add(ref)
            self.table.insert('','end',iid=ref,values=('✓' if valid else '',ref,item['footprint'],
                HOLE_PRESETS[item['hole_type']][2],f'{x:.3f}',f'{y:.3f}',f"{item['diameter_mm']:g}",action))
        counts=Counter(c['hole_type'] for c in candidates)
        self.status.set(f"{self.data.get('board_name','PCB')}: {len(candidates)} centros · "
            f"{counts['potentiometer']} potenciómetros, {counts['jack']} jacks, {counts['spdt']} SPDT. "
            f"{len(self.data.get('unplaced',[]))} componentes sin colocar; {len(skipped)} omitidos por anclaje/cara. "
            f"{len(self.checked)} seleccionados válidos. "
            + (' '.join(ref+': '+reason for ref,reason in skipped[:2])))
        self.update_checks()

    def text_options(self):
        from panel_model import number
        return dict(size=number(self.text_size.get(),.5,20),gap=number(self.text_gap.get(),0,50),
                    position='above' if self.text_position.get()=='Encima' else 'below',
                    font=next(k for k,v in FONTS.items() if v[0]==self.text_font.get()))

    def add_text_row(self,item,label):
        d=self.owner.document
        half_width=len(label.text)*label.size*.4
        outside=not(half_width<=label.x<=d.width-half_width and label.size/2<=label.y<=HEIGHT_MM-label.size/2)
        exists=any(e.kind=='text' and (e.source_ref==label.source_ref or
                   (not e.source_ref and e.text.strip().casefold()==label.text.casefold())) for e in d.elements)
        valid=not outside and not exists
        ref=item['refdes']
        self.items[ref]=(dict(item,label=label),valid,'Texto existente: conservar' if exists else 'Fuera del frontal' if outside else 'Añadir texto')
        if valid:self.checked.add(ref)
        self.table.insert('','end',iid=ref,values=('✓' if valid else '',ref,item['footprint'],'Etiqueta refdes',
            f'{label.x:.3f}',f'{label.y:.3f}',f'{label.size:g}',self.items[ref][2]))

    def load_rule(self,event=None):
        rule=self.rules.get(self.footprint.get(),dict(hole_type='custom',diameter_mm=6.5,anchor='origin',value='',side='TOP'))
        self.kind.set(HOLE_PRESETS[rule['hole_type']][2]);self.diameter.set(f"{rule['diameter_mm']:g}")
        self.anchor.set(ANCHOR_LABELS[rule['anchor']]);self.value.set(rule['value']);self.side.set(rule['side'])

    def save_rule(self):
        if not self.footprint.get():return
        try:
            kind=next(k for k,p in HOLE_PRESETS.items() if p[2]==self.kind.get())
            anchor=next(k for k,v in ANCHOR_LABELS.items() if v==self.anchor.get())
            rule=dict(hole_type=kind,diameter_mm=self.diameter.get(),anchor=anchor,value=self.value.get(),side=self.side.get())
            self.rules.update(validate_rules({self.footprint.get():rule}));self.refresh()
        except (ValueError,StopIteration) as error:
            messagebox.showerror('Regla del footprint',str(error),parent=self)

    def import_rules(self):
        path=filedialog.askopenfilename(parent=self,title='Importar biblioteca de agujeros',filetypes=[('Biblioteca JSON','*.json')])
        if not path:return
        try:
            if Path(path).stat().st_size>2_000_000:raise ValueError('Biblioteca demasiado grande.')
            data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if data.get('schema')!='sputtering.footprint-hole-rules.v1':raise ValueError('Formato de biblioteca desconocido.')
            self.rules.update(validate_rules(data['rules']));self.refresh()
        except (OSError,ValueError,KeyError,TypeError) as error:
            messagebox.showerror('Biblioteca de agujeros',str(error),parent=self)

    def export_rules(self):
        path=filedialog.asksaveasfilename(parent=self,title='Guardar biblioteca reutilizable de agujeros',
            initialfile='biblioteca_agujeros.json',defaultextension='.json',filetypes=[('Biblioteca JSON','*.json')])
        if path:
            try:atomic_write(path,json.dumps(dict(schema='sputtering.footprint-hole-rules.v1',rules=validate_rules(self.rules)),ensure_ascii=False,indent=2))
            except (OSError,ValueError) as error:messagebox.showerror('Biblioteca de agujeros',str(error),parent=self)

    def select_row(self,event=None):
        selection=self.table.selection()
        if selection:
            self.footprint.set(self.items[selection[0]][0]['footprint']);self.load_rule()

    def toggle(self,event=None):
        if event is not None and hasattr(event,'y') and event.type == tk.EventType.ButtonPress:
            ref=self.table.identify_row(event.y)
        else:ref=next(iter(self.table.selection()),'')
        if ref in self.items and self.items[ref][1]:
            if ref in self.checked:self.checked.remove(ref)
            else:self.checked.add(ref)
            self.update_checks()
        return 'break'

    def mark_all(self,checked):
        self.checked={ref for ref,(_,valid,_) in self.items.items() if valid} if checked else set()
        self.update_checks()

    def update_checks(self):
        for ref in self.items:self.table.set(ref,'use','✓' if ref in self.checked else '')
        self.apply_button.configure(state='normal' if self.checked and not self.busy else 'disabled')
        self.owner.canvas.delete('footprint_preview')
        self.preview_images.clear()
        d=self.owner.document;scale=self.owner.transform()[0]
        for ref in self.checked:
            p=self.items[ref][0]
            if self.mode == 'texts':
                label=p['label'];x,y=self.owner.to_canvas(label.x,label.y)
                mask=text_mask(label.text,label.size,label.font)
                image=Image.new('RGBA',mask.size,'#b050e0');image.putalpha(mask)
                image=image.resize((max(1,round(mask.width*PIXEL_MM*scale)),max(1,round(mask.height*PIXEL_MM*scale))),Image.Resampling.LANCZOS)
                photo=ImageTk.PhotoImage(image,master=self);self.preview_images.append(photo)
                self.owner.canvas.create_image(x,y,image=photo,tags='footprint_preview')
                continue
            x,y=self.owner.to_canvas(p['x_mm']+d.pcb_dx,p['y_mm']+d.pcb_dy)
            r=p['diameter_mm']*scale/2
            self.owner.canvas.create_oval(x-r,y-r,x+r,y+r,outline='#b050e0',width=2,dash=(4,3),tags='footprint_preview')

    def apply(self):
        if self.busy or not self.checked:return
        try:
            candidate=copy.deepcopy(self.owner.document)
            if self.mode == 'texts':
                count,collisions,_=candidate.apply_refdes_labels(self.data,self.rules,self.checked,**self.text_options())
            else:
                count,collisions,_=candidate.apply_footprint_holes(self.data,self.rules,self.checked)
            self.owner.remember();self.owner.document=candidate;self.owner.selected=None;self.owner.changed()
            self.owner.status.set(f'{count} '+('etiquetas refdes importadas. ' if self.mode == 'texts' else 'agujeros desde footprints añadidos/actualizados. ')
                                  + f'{len(collisions)} coincidencias existentes conservadas. Guarda el proyecto para conservar la referencia.')
            self.close()
        except ValueError as error:messagebox.showerror('Agujeros desde PCB',str(error),parent=self)

    def close(self):
        self.closed=True
        if self.poll_id:self.after_cancel(self.poll_id)
        self.owner.canvas.delete('footprint_preview')
        self.grab_release();self.destroy()
