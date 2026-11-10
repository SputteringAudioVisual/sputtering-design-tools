"""Readable, scoped ttk controls without changing the original editor's theme."""
import tkinter as tk
from tkinter import ttk

BACKGROUND = '#252535'
TEXT = '#eef1f8'
MUTED = '#bbc4dc'


def configure_styles(window):
    style = ttk.Style(window)
    classes = ('TFrame', 'TLabelframe', 'TLabel', 'TButton', 'TRadiobutton',
               'TCheckbutton', 'TEntry', 'TCombobox', 'TPanedwindow',
               'Vertical.TScrollbar', 'Horizontal.TScrollbar', 'Treeview', 'Treeview.Heading')
    # Native Windows buttons ignore background settings. Import portable elements
    # into Panel.* only, rather than changing the theme of the legacy workspace.
    original = style.theme_use()
    try:
        style.theme_use('clam')
        layouts = {name: style.layout(name) for name in classes}
    finally:
        style.theme_use(original)
    elements = set(style.element_names())

    def scoped(layout):
        result = []
        for name, options in layout:
            target = 'Panel.' + name
            if target not in elements:
                style.element_create(target, 'from', 'clam', name)
                elements.add(target)
            options = dict(options)
            if 'children' in options:
                options['children'] = scoped(options['children'])
            result.append((target, options))
        return result

    for name in classes:
        target = 'Panel.' + name
        style.layout(target, scoped(layouts[name]))
        style.configure(target, background=BACKGROUND, foreground=TEXT,
                        font=('Segoe UI', 10), fieldbackground='#191c2b',
                        insertcolor=TEXT, bordercolor='#69738f',
                        lightcolor=BACKGROUND, darkcolor=BACKGROUND,
                        arrowcolor=TEXT, selectbackground='#355ca3', selectforeground='white')
        style.map(target, foreground=[('disabled', '#929bb2')],
                  background=[('disabled', '#292d3e'), ('active', '#3d4662')],
                  fieldbackground=[('disabled', '#292d3e'), ('readonly', '#191c2b')],
                  bordercolor=[('focus', '#f4cd73')])
    style.configure('Panel.TButton', background='#3b425e', padding=(10, 7),
                    font=('Segoe UI', 10, 'bold'), focusthickness=2, focuscolor='#f4cd73')
    style.map('Panel.TButton', background=[('disabled', '#292d3e'),
              ('pressed', '#282f49'), ('active', '#505c7d')])
    for name, color, hover, pressed in (
            ('Primary.Panel.TButton', '#294c9b', '#355fb5', '#203b79'),
            ('Danger.Panel.TButton', '#633d50', '#805069', '#4c2d3f')):
        style.configure(name, background=color, foreground='white')
        style.map(name, background=[('disabled', '#292d3e'), ('pressed', pressed), ('active', hover)],
                  foreground=[('disabled', '#929bb2'), ('!disabled', 'white')])
    style.configure('Panel.TLabelframe.Label', background=BACKGROUND, foreground='#d5ddff',
                    font=('Segoe UI', 10, 'bold'))
    style.configure('Hint.Panel.TLabel', foreground=MUTED)
    style.configure('Warning.Panel.TLabel', foreground='#ffd08a')
    for name in ('Panel.TCheckbutton', 'Panel.TRadiobutton'):
        style.configure(name, padding=(2, 4), indicatorbackground='#191c2b',
                        indicatorforeground='white', indicatormargin=(0, 2, 6, 2))
        style.map(name, indicatorbackground=[('disabled', '#292d3e'), ('selected', '#355ca3')])
    style.configure('Panel.Treeview', rowheight=28)
    style.map('Panel.Treeview', background=[('selected', '#355ca3')],
              foreground=[('selected', 'white')])
    style.configure('Panel.Treeview.Heading', padding=(5, 7), font=('Segoe UI', 10, 'bold'))
    return style


def apply_theme(window, descendants):
    """Style new dialogs too; preserve explicit primary/danger/hint roles."""
    window.configure(bg=BACKGROUND)
    for widget in descendants(window):
        if isinstance(widget, ttk.Widget):
            name = widget.winfo_class()
            if 'Panel.' in str(widget.cget('style')):
                continue
            if name == 'TScrollbar':
                name = str(widget.cget('orient')).title() + '.TScrollbar'
            try:
                widget.configure(style='Panel.' + name)
            except tk.TclError:
                pass
        elif isinstance(widget, tk.Listbox):
            widget.configure(bg='#191c2b', fg=TEXT, font=('Segoe UI', 10),
                             selectbackground='#355ca3', selectforeground='white', highlightthickness=0)
        elif isinstance(widget, tk.Text):
            widget.configure(bg='#191c2b', fg=TEXT, font=('Segoe UI', 10),
                             insertbackground=TEXT, highlightthickness=0)
