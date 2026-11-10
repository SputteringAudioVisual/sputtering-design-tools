"""The same short guide in the app and inside newly prepared modules."""
from pathlib import Path
import tkinter as tk

GUIDE=Path(__file__).with_name('GUIA_CARGA_PROYECTO.txt')


def copy_guide(root):
    path=Path(root)/GUIDE.name
    if not path.exists():
        from panel_model import atomic_write
        atomic_write(path,GUIDE.read_text(encoding='utf-8'))
    return path


def show_guide(parent):
    win=tk.Toplevel(parent);win.title('Guía rápida · Cargar proyecto');win.geometry('780x650')
    win.minsize(600,400);win.transient(parent);win.configure(bg='#252535')
    frame=tk.Frame(win,bg='#252535');frame.pack(fill='both',expand=True,padx=12,pady=12)
    scroll=tk.Scrollbar(frame);scroll.pack(side='right',fill='y')
    text=tk.Text(frame,wrap='word',font=('Consolas',10),bg='#1a1a2e',fg='#eeeef6',
                 padx=14,pady=12,relief='flat',yscrollcommand=scroll.set)
    text.pack(fill='both',expand=True);scroll.config(command=text.yview)
    text.insert('1.0',GUIDE.read_text(encoding='utf-8'));text.config(state='disabled')
    tk.Button(win,text='Cerrar',command=win.destroy,bg='#3a3a5c',fg='white',relief='flat',padx=20,pady=6).pack(pady=(0,12))
    return win
