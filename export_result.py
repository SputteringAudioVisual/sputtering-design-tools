"""A selectable output path, with the same completion flow in both apps."""
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox


def show_export_result(parent,title,path,details=''):
    path=Path(path).resolve()
    win=tk.Toplevel(parent);win.title(title);win.transient(parent)
    win.configure(bg='#252535');win.minsize(620,190)
    tk.Label(win,text=title,bg='#252535',fg='white',font=('Segoe UI',12,'bold')).pack(anchor='w',padx=16,pady=(14,8))
    value=tk.StringVar(master=win,value=str(path))
    field=tk.Entry(win,textvariable=value,state='readonly',readonlybackground='#1a1a2e',fg='white',
                   font=('Segoe UI',10),width=90)
    field.pack(fill='x',padx=16,pady=6)
    tk.Label(win,text=details,bg='#252535',fg='#ccccdd',justify='left',wraplength=780).pack(anchor='w',padx=16,pady=8)
    row=tk.Frame(win,bg='#252535');row.pack(fill='x',padx=12,pady=(4,14))
    def copy():
        win.clipboard_clear();win.clipboard_append(str(path));status.set('Ruta copiada')
    def folder():
        try:os.startfile(str(path.parent))
        except OSError as error:messagebox.showerror('Abrir carpeta',str(error),parent=win)
    for text,command in [('Copiar ruta',copy),('Abrir carpeta',folder),('Cerrar',win.destroy)]:
        tk.Button(row,text=text,command=command,bg='#3a3a5c',fg='white',relief='flat',padx=14,pady=7).pack(side='left',padx=4)
    status=tk.StringVar(master=win)
    tk.Label(row,textvariable=status,bg='#252535',fg='#aaddbb').pack(side='left',padx=8)
    field.focus_set();field.selection_range(0,'end');win.grab_set()
    return win
