"""Inspect or recover a saved revision without losing the current one."""
import os
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from module_project import find_root,read,revisions,restore_revision,verify,STAGES


def show_versions(parent,project,before_restore,reload):
    root=find_root(project)
    if root is None:
        messagebox.showinfo('Versiones','Abre primero un módulo preparado desde una PCB.',parent=parent);return
    win=tk.Toplevel(parent);win.title('Versiones del módulo · '+read(root)['name']);win.geometry('800x450');win.transient(parent)
    frame=ttk.Frame(win,padding=12);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Cada guardado con cambios conserva una revisión. Recuperar una anterior crea otra revisión; no borra el historial.',wraplength=740).pack(anchor='w',pady=(0,10))
    table=ttk.Treeview(frame,columns=('stage','version','date'),show='headings',selectmode='browse')
    for key,label,width in [('stage','Etapa',240),('version','Guardado',90),('date','Guardada (UTC)',320)]:
        table.heading(key,text=label);table.column(key,width=width)
    scroll=ttk.Scrollbar(frame,command=table.yview);table.config(yscrollcommand=scroll.set)
    scroll.pack(side='right',fill='y');table.pack(fill='both',expand=True)
    records=revisions(root)
    for i,r in enumerate(records):table.insert('','end',iid=str(i),values=(STAGES[r['stage']],f"{r['revision']:04d}",r['created_utc'][:19]))
    buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=(10,0))
    def restore():
        selection=table.selection()
        if not selection:return
        if not before_restore():return
        try:
            path=restore_revision(root,records[int(selection[0])]['checkpoint'])
            reload(path);win.destroy()
        except (ValueError,OSError) as error:messagebox.showerror('Recuperar revisión',str(error),parent=win)
    def check():
        try:
            result=verify(root);messagebox.showinfo('Proyecto comprobado',f"Referencias y archivos correctos. {result['artifacts']} archivos registrados.",parent=win)
        except (ValueError,OSError) as error:messagebox.showerror('Comprobar proyecto',str(error),parent=win)
    ttk.Button(buttons,text='Recuperar revisión seleccionada',command=restore).pack(side='left',padx=3)
    ttk.Button(buttons,text='Comprobar proyecto',command=check).pack(side='left',padx=3)
    ttk.Button(buttons,text='Abrir carpeta',command=lambda:os.startfile(str(root))).pack(side='left',padx=3)
    ttk.Button(buttons,text='Cerrar',command=win.destroy).pack(side='right')
    return win


def show_releases(parent,project,before_restore,reload):
    from module_project import local
    from release_contract import association,compare_packages,freshness
    root=find_root(project)
    if root is None:
        messagebox.showinfo('Liberaciones','Guarda el proyecto en un módulo para conservar el historial de liberaciones.',parent=parent);return
    data=read(root);records=[];seen=set()
    for item in reversed(data.get('artifacts',[])+data.get('fabrication_sources',[])):
        if not item['path'].lower().endswith('.zip'):continue
        path=local(root,item['path'])
        try:
            value=association(path);key=value['archive_sha256']
        except (OSError,ValueError) as error:
            value=dict(legacy=True,error=str(error));key=item['path']
        if key in seen:continue
        seen.add(key);records.append(dict(item,path_object=path,association=value))
    win=tk.Toplevel(parent);win.title('Liberaciones Gerber · '+data['name']);win.geometry('1080x520');win.transient(parent)
    frame=ttk.Frame(win,padding=12);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Placa y revisión PCB pertenecen al origen. Cada edición E es otro paquete. Selecciona dos para comparar archivos.',wraplength=980).pack(anchor='w',pady=(0,10))
    table=ttk.Treeview(frame,columns=('name','revision','release','state'),show='headings',selectmode='extended')
    for key,label,width in [('name','Placa / archivo histórico',300),('revision','PCB',65),('release','F / E',75),('state','Asociación',530)]:
        table.heading(key,text=label);table.column(key,width=width)
    scroll=ttk.Scrollbar(frame,command=table.yview);table.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right',fill='y');table.pack(fill='both',expand=True)
    for i,r in enumerate(records):
        value=r['association']
        table.insert('','end',iid=str(i),values=(value.get('project_name') or r['path_object'].name,
            value.get('pcb_revision') or '—',value.get('release_label') or 'Histórico',
            'Paquete no válido: '+value['error'] if value.get('error') else freshness(value,root)))
    def selected():return [records[int(i)] for i in table.selection()]
    def display(title,text):
        view=tk.Toplevel(win);view.title(title);view.geometry('900x520')
        area=tk.Text(view,wrap='word',font=('Consolas',10));area.pack(fill='both',expand=True)
        area.insert('1.0',text);area.configure(state='disabled')
        ttk.Button(view,text='Cerrar',command=view.destroy).pack(pady=6)
    def details():
        rows=selected()
        if rows:display('Identidad y procedencia',str(rows[0]['path_object'])+'\n\n'+json.dumps(rows[0]['association'],ensure_ascii=False,indent=2))
    def compare():
        rows=selected()
        if len(rows)!=2:
            messagebox.showinfo('Comparar','Selecciona dos paquetes usando Ctrl + clic.',parent=win);return
        try:
            result=compare_packages(rows[0]['path_object'],rows[1]['path_object'])
            display('Comparación de archivos',str(rows[0]['path_object'])+'\n→ '+str(rows[1]['path_object'])+'\n\n'+
                f"Sin cambios: {result['unchanged']}\n\n"+'\n\n'.join(label+':\n'+('\n'.join(result[key]) or 'Ninguno') for key,label in [('added','Añadidos'),('removed','Eliminados'),('changed','Modificados')]))
        except (OSError,ValueError) as error:messagebox.showerror('Comparación',str(error),parent=win)
    def recover():
        rows=selected()
        if len(rows)!=1:return
        checkpoint=(rows[0].get('lineage') or {}).get('checkpoint')
        if not checkpoint:
            messagebox.showinfo('Edición no disponible','Este ZIP no tiene un guardado editable asociado. Se conserva el paquete original.',parent=win);return
        if not before_restore():return
        try:reload(restore_revision(root,checkpoint));win.destroy()
        except (OSError,ValueError) as error:messagebox.showerror('Recuperar edición',str(error),parent=win)
    row=ttk.Frame(frame);row.pack(fill='x',pady=(10,0))
    for text,command in [('Ver identidad y hashes',details),('Comparar seleccionados',compare),('Recuperar edición guardada',recover),('Cerrar',win.destroy)]:
        ttk.Button(row,text=text,command=command).pack(side='left',padx=4)
    return win
