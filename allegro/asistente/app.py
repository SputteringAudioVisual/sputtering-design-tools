"""External PCB workflow assistant; Python standard library only."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import uuid
import zipfile

from saved_board import verify_snapshot
from package_report import annotate_package, latest_export, remember_export
from transport import Mailbox, append_history, skill_string
from workflow import VERSION, STEPS, ExportPolicy, Profile, Workflow, project_history
from traceability import (association_status, available_projects, bind_board, compare_releases, digest,
                          fail_release, load_binding, local, now, releases, reserve_release, seal_release)

HERE = Path(__file__).resolve().parent
CORE = Path("C:/SPB_Data/pcbenv/pcb_tools")
CADENCE = Path("C:/Cadence/SPB_17.2/tools/bin")
BLUE, INK, MUTED = "#245dd9", "#182b46", "#53647a"
BG, WHITE, LINE = "#f2f5f9", "#ffffff", "#dce3ed"


class Assistant(tk.Tk):
    def __init__(self, demo=False, board=None):
        super().__init__()
        self.title("PCB · Asistente de fabricación (beta)")
        self.dpi_scale = max(1, self.winfo_fpixels("1i") / 96)
        width = min(int(1180 * self.dpi_scale), int(self.winfo_screenwidth() * .92))
        height = min(int(880 * self.dpi_scale), int(self.winfo_screenheight() * .90))
        self.geometry(f"{width}x{height}")
        self.minsize(min(int(1020 * self.dpi_scale), width), min(int(740 * self.dpi_scale), height))
        self.configure(bg=BG)
        self.demo = demo
        self.flow = None
        self.mailbox = None
        self.step = 0
        self.task = False
        self.ticket = "-"
        self.finalizing = False
        self.events = queue.Queue()
        self.logged_pending = False
        self.poll_error = None
        self.action_buttons = []
        self.export_record = None
        self.project_binding = None
        self.release_reservation = None
        self.identity_var = tk.StringVar(value="Placa sin identidad/revisión declarada; los ZIP antiguos se conservan.")
        self.check_text_var = tk.BooleanVar(value=True)
        self.excluded_var = tk.StringVar(value="")
        self.technical_var = tk.BooleanVar(value=False)
        self.notice_var = tk.StringVar(value="Selecciona una placa para empezar.")
        self.board_var = tk.StringVar(value="Selecciona la placa con la que vas a trabajar")
        self.connection_var = tk.StringVar(value="Sin conectar")
        self.summary_var = tk.StringVar(value="Las comprobaciones aparecerán aquí al conectar Allegro.")
        self.power_var = tk.StringVar(value="+12V; -12V; 0; GND; VCC; VEE; VDD")
        self.signal_var = tk.StringVar(value="0.40")
        self.width_var = tk.StringVar(value="0.80")
        self.placement_var = tk.BooleanVar()
        self.export_path_var = tk.StringVar(value="")
        self.last_zip = None
        self.cam_var = tk.BooleanVar()
        self._style()
        self._layout()
        self.show_step(0)
        self.protocol("WM_DELETE_WINDOW", self.close)
        if demo:
            self._demo()
        elif board:
            self.select_board(board)
        self.after(700, self.poll)

    def _style(self):
        self.option_add("*Font", "{Segoe UI} 10")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=WHITE)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Card.TLabel", background=WHITE, foreground=INK)
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("Sub.TLabel", foreground=MUTED)
        style.configure("TButton", padding=(14, 9), font=("Segoe UI", 10))
        style.configure("Primary.TButton", background=BLUE, foreground=WHITE)
        style.map("Primary.TButton", background=[("active", "#1647b0"), ("disabled", "#b6c1d4")])
        style.configure("TCheckbutton", background=WHITE, foreground=INK, padding=6)
        style.configure("Treeview", rowheight=int(27 * self.dpi_scale))

    def _layout(self):
        top = tk.Frame(self, bg=INK, padx=24, pady=18)
        top.pack(fill="x")
        tk.Label(top, text="SPUTTERING / PCB", fg="white", bg=INK,
                 font=("Segoe UI", 17, "bold")).pack(side="left")
        tk.Label(top, text=f"ASISTENTE {VERSION}", fg="#bdd0ea", bg=INK).pack(side="right")
        bar = ttk.Frame(self, padding=(24, 14))
        bar.pack(fill="x")
        ttk.Label(bar, textvariable=self.board_var, wraplength=780).pack(side="left", fill="x", expand=True)
        ttk.Label(bar, textvariable=self.connection_var, foreground=BLUE).pack(side="right", padx=(14, 0))
        identity_bar = ttk.Frame(self, padding=(24, 0, 24, 8))
        identity_bar.pack(fill="x")
        ttk.Label(identity_bar, textvariable=self.identity_var, wraplength=780).pack(side="left", fill="x", expand=True)
        ttk.Button(identity_bar, text="Placa y revisión…", command=self.edit_identity).pack(side="right", padx=(8, 0))
        ttk.Button(identity_bar, text="Liberaciones…", command=self.show_releases).pack(side="right")
        body = ttk.Frame(self, padding=(18, 0, 18, 8))
        body.pack(fill="both", expand=True)
        self.nav = tk.Frame(body, bg=BG, width=int(225 * self.dpi_scale))
        self.nav.pack(side="left", fill="y", padx=(0, 18))
        self.nav.pack_propagate(False)
        self.nav_buttons = []
        for i, label in enumerate(STEPS):
            button = tk.Button(self.nav, text=label, anchor="w", relief="flat", bd=0, padx=12, pady=14,
                               command=lambda index=i: self.show_step(index), cursor="hand2")
            button.pack(fill="x", pady=3)
            self.nav_buttons.append(button)
        tk.Label(self.nav, text="Tú decides cuándo aplicar\ncambios. Las utilidades\nhabituales siguen disponibles.",
                 justify="left", bg=BG, fg=MUTED, pady=24).pack(anchor="w")
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        self.heading = ttk.Label(right, style="Title.TLabel")
        self.heading.pack(anchor="w", pady=(5, 10))
        self.card = ttk.Frame(right, style="Card.TFrame", padding=20)
        self.card.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.card, bg=WHITE, highlightthickness=0, width=1, height=1)
        scroll = ttk.Scrollbar(self.card, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = ttk.Frame(self.canvas, style="Card.TFrame")
        self.canvas_item = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.resize_content)
        ttk.Label(right, textvariable=self.summary_var, style="Sub.TLabel", wraplength=830).pack(fill="x", pady=(12, 6))
        logs = ttk.Frame(self, padding=(24, 0, 24, 16))
        logs.pack(fill="x")
        head = ttk.Frame(logs)
        head.pack(fill="x", pady=(0, 5))
        ttk.Label(head, text="Resumen de revisión", font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(head, text="Abrir carpeta de resultados", command=self.open_results).pack(side="right")
        ttk.Label(logs, textvariable=self.notice_var, wraplength=1050, foreground=BLUE).pack(anchor="w", pady=(0, 6))
        table = ttk.Frame(logs)
        table.pack(fill="x")
        self.results = ttk.Treeview(table, columns=("status", "check", "detail"), show="headings", height=5)
        for key, label, width in (("status", "Estado", 110), ("check", "Comprobación", 255), ("detail", "Detalle / qué hacer", 600)):
            self.results.heading(key, text=label)
            self.results.column(key, width=int(width * self.dpi_scale), stretch=key == "detail")
        self.results.tag_configure("accepted", foreground="#526b63")
        self.results.tag_configure("warning", foreground="#9b5700")
        self.results.tag_configure("pending", foreground="#53647a")
        table_scroll = ttk.Scrollbar(table, orient="vertical", command=self.results.yview)
        self.results.configure(yscrollcommand=table_scroll.set)
        self.results.pack(side="left", fill="x", expand=True)
        table_scroll.pack(side="right", fill="y")
        actions = ttk.Frame(logs)
        actions.pack(fill="x", pady=5)
        self.accept_button = ttk.Button(actions, text="Aceptar aviso seleccionado…", command=self.accept_selected)
        self.accept_button.pack(side="left")
        ttk.Button(actions, text="Retirar aceptación", command=self.revoke_selected).pack(side="left", padx=7)
        ttk.Checkbutton(actions, text="Ver detalle técnico", variable=self.technical_var, command=self.toggle_technical).pack(side="right")
        self.results.bind("<<TreeviewSelect>>", lambda event: self.refresh_accept_button())
        export_bar = ttk.Frame(logs)
        export_bar.pack(fill="x", pady=(2, 5))
        ttk.Label(export_bar, text="Último ZIP:").pack(side="left", padx=(0, 8))
        ttk.Entry(export_bar, textvariable=self.export_path_var, state="readonly").pack(side="left", fill="x", expand=True)
        self.export_folder_button = ttk.Button(export_bar, text="Abrir carpeta exportada", command=self.open_export_folder, state="disabled")
        self.export_folder_button.pack(side="left", padx=(8, 0))
        self.copy_export_button = ttk.Button(export_bar, text="Copiar ruta", command=self.copy_export_path, state="disabled")
        self.copy_export_button.pack(side="left", padx=(8, 0))
        self.log_frame = tk.Frame(logs)
        self.log = tk.Text(self.log_frame, height=5, wrap="word", bg="#122138", fg="#e4edf9", bd=0,
                           padx=14, pady=10, font=("Consolas", 10), state="disabled")
        scrollbar = ttk.Scrollbar(self.log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def text(self, content, bold=False):
        label = ttk.Label(self.content, text=content, style="Card.TLabel", wraplength=max(180, self.canvas.winfo_width() - 12),
                          font=("Segoe UI", 11, "bold" if bold else "normal"), justify="left")
        label.pack(anchor="w", fill="x", pady=(0, 13))
        return label

    def button(self, label, command, primary=False, native=False):
        button = ttk.Button(self.content, text=label, command=command,
                            style="Primary.TButton" if primary else "TButton")
        button.pack(anchor="w", pady=(0, 9))
        if native:
            self.action_buttons.append(button)
        return button

    def show_step(self, index):
        self.step = index
        for child in self.content.winfo_children():
            child.destroy()
        self.action_buttons = []
        self.canvas.yview_moveto(0)
        self.heading.configure(text=STEPS[index].split(" · ", 1)[1])
        for i, button in enumerate(self.nav_buttons):
            button.configure(bg=BLUE if i == index else BG, fg=WHITE if i == index else INK)
        if index == 0:
            self.text("Abre una placa guardada. Puedes iniciar Allegro desde aquí o conectar la placa que ya tengas abierta.")
            self.button("Seleccionar archivo .brd", self.choose_board, primary=True)
            self.button("Abrir Allegro y conectar", self.launch)
            self.button("Conectar con Allegro ya abierto", self.attach)
            self.text("La conexión no cambia el diseño. Antes de ejecutar una operación, termina la herramienta activa en Allegro con Done o Esc.")
            if self.demo:
                self.text("VISTA DE DEMOSTRACIÓN · Los botones no ejecutan operaciones en Allegro.", bold=True)
        elif index == 1:
            self.text("Revisa primero la colocación", bold=True)
            self.text("Comprueba la correspondencia entre símbolo y footprint, pin 1, polaridades y orientación de conectores. Coloca el desacoplo cerca de los pines que alimenta y piensa en el camino de retorno de cada señal.")
            self.text("Para una PSU: identifica entrada, retorno, salida positiva y salida negativa; comprueba corriente, anchuras y zonas de disipación. Una salida negativa no equivale a masa.")
            self.button("Inspeccionar placa y mostrar auditorías", lambda: self.run("inspect"), primary=True, native=True)
            ttk.Checkbutton(self.content, text="He revisado colocación, polaridades y conectores",
                            variable=self.placement_var, command=self.confirmations).pack(anchor="w", pady=8)
            self.text("El asistente cuenta componentes colocados; la revisión eléctrica y mecánica la haces tú.")
        elif index == 2:
            self.text("Decide qué redes son de alimentación", bold=True)
            self.text("Separa los nombres con punto y coma. Usa los nombres reales que aparecen en los resultados. Los valores siguientes son una propuesta: ajústalos a la corriente y al fabricante.")
            ttk.Entry(self.content, textvariable=self.power_var, width=75).pack(fill="x", pady=(0, 12))
            grid = ttk.Frame(self.content, style="Card.TFrame")
            grid.pack(anchor="w", pady=(0, 14))
            for col, label, variable in ((0, "Señal (mm)", self.signal_var), (2, "Alimentación (mm)", self.width_var)):
                ttk.Label(grid, text=label, style="Card.TLabel").grid(row=0, column=col, padx=(0, 8))
                ttk.Entry(grid, textvariable=variable, width=9).grid(row=0, column=col + 1, padx=(0, 22))
            self.button("Aplicar reglas de anchos y vías", lambda: self.run("widths"), primary=True, native=True)
            self.button("Abrir pines y cubrir vías en soldermask", lambda: self.run("mask"), native=True)
            self.text("Se conservan las reglas especiales existentes. Las pistas ya dibujadas no cambian de ancho con esta operación. Se crea una copia de seguridad antes de modificar la placa.")
        elif index == 3:
            self.text("Traza las pistas en Allegro", bold=True)
            self.text("Usa el router manual o el autorouter de tu instalación después de revisar las reglas. Reserva el retorno de masa y los bucles de alimentación; revisa islas de cobre y conexiones pendientes.")
            self.text("Este asistente todavía no lanza ni controla el autorouter. Continúa aquí cuando hayas terminado de rutear y actualizado los planos de cobre.")
            self.button("Consultar el estado tras rutear", lambda: self.run("inspect"), primary=True, native=True)
            self.text("El asistente comprueba DRC y conexiones sin rutear por separado después de actualizar los rellenos.", bold=True)
        elif index == 4:
            self.text("Revisa lo que se va a fabricar", bold=True)
            self.text_options()
            self.button("Actualizar rellenos y ejecutar DRC completo", lambda: self.run("review"), primary=True, native=True)
            self.button("Auditar textos, máscara, reglas y fabricación", lambda: self.run("inspect"), native=True)
            self.button("Recuperar referencias que falten", lambda: self.run("references"), native=True)
            self.button("Comprobar referencias en una copia guardada", lambda: self.run("snapshot"), native=True)
            self.button("Guardar la placa original (con copia previa)", lambda: self.run("save"), native=True)
            self.text("La limpieza que elimina textos queda fuera de esta beta mientras resolvemos el fallo de referencias al guardar. Las referencias recuperadas se crean en el origen del componente: revisa su posición.")
        else:
            self.text("Prepara una comprobación final reciente", bold=True)
            self.text_options()
            self.button("Revisar DRC y comprobar copia guardada", self.prepare_export, primary=True, native=True)
            ttk.Checkbutton(self.content, text="He revisado colocación, polaridades y conectores",
                            variable=self.placement_var, command=self.confirmations).pack(anchor="w", pady=3)
            ttk.Checkbutton(self.content, text="Revisaré Gerber y taladros en un visor CAM antes de fabricar",
                            variable=self.cam_var, command=self.confirmations).pack(anchor="w", pady=3)
            self.button("Crear ZIP de fabricación con versión", self.export, primary=True, native=True)
            self.text("Las conexiones sin rutear se cuentan automáticamente por red, también las que quedan hacia planos de cobre. Si editas la placa, repite la comprobación final. Colocación, polaridades y revisión CAM siguen siendo revisiones visuales.")
            self.text("El ZIP, los informes y las copias se guardan dentro del proyecto. Si hay avisos de exportación, aparecen en los resultados y deben revisarse.")
        self.refresh_buttons()

    def text_options(self):
        ttk.Checkbutton(self.content, text="Revisar referencias de serigrafía (opcional)",
                        variable=self.check_text_var, command=self.update_policy).pack(anchor="w", pady=(0, 4))
        self.text("Sin referencia a propósito: indica nombres concretos separados por ; (por ejemplo J1; J2). No se modifica ningún texto.")
        ttk.Entry(self.content, textvariable=self.excluded_var).pack(fill="x", pady=(0, 6))
        self.button("Guardar opciones de serigrafía", self.update_policy)

    def update_policy(self):
        if not self.flow:
            return
        try:
            policy = ExportPolicy(self.check_text_var.get(), [ref.strip() for ref in self.excluded_var.get().replace(",", ";").split(";") if ref.strip()]).validate()
            if policy != self.flow.policy:
                self.flow.policy = policy
                self.flow.waivers.clear()
                folder = project_history(self.flow.board)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "opciones_exportacion.json").write_text(json.dumps(vars(policy), ensure_ascii=False, indent=2), encoding="utf-8")
                append_history(folder, {"time": time.time(), "action": "text_policy", **vars(policy)})
            self.refresh_findings()
        except (OSError, ValueError, UnicodeError) as exc:
            messagebox.showerror("Opciones de serigrafía", str(exc))
            raise ValueError(str(exc)) from exc

    def toggle_technical(self):
        if self.technical_var.get():
            self.log_frame.pack(fill="both")
        else:
            self.log_frame.pack_forget()

    def refresh_accept_button(self):
        selection = self.results.selection()
        finding = None
        if self.flow and selection:
            finding = next((item for item in self.flow.findings() if selection[0] == "issue:" + item.code), None)
        busy = self.task or (self.mailbox and self.mailbox.pending)
        self.accept_button.configure(state="normal" if finding and finding.waivable and not busy else "disabled")

    def accept_selected(self):
        selected = self.results.selection()
        if not self.flow or not selected:
            return
        finding = next((item for item in self.flow.findings() if selected[0] == "issue:" + item.code), None)
        if not finding or not finding.waivable:
            return
        reason = simpledialog.askstring("Aceptar aviso", f"{finding.title}\n{finding.detail}\n\n¿Por qué lo aceptas para esta exportación?", parent=self)
        if reason is None:
            return
        try:
            self.flow.accept_finding(finding.code, reason)
            append_history(project_history(self.flow.board), {"time": time.time(), "action": "accept_warning", "code": finding.code, **self.flow.waivers[finding.code]})
            self.refresh_findings()
        except ValueError as exc:
            messagebox.showerror("Aceptar aviso", str(exc))

    def revoke_selected(self):
        selected = self.results.selection()
        if self.flow and selected:
            code = selected[0].removeprefix("issue:")
            if self.flow.waivers.pop(code, None):
                append_history(project_history(self.flow.board), {"time": time.time(), "action": "revoke_warning", "code": code})
            self.refresh_findings()

    def refresh_findings(self):
        selected = self.results.selection()
        self.results.delete(*self.results.get_children())
        if not self.flow or not self.flow.state:
            self.notice_var.set("Conecta Allegro y pulsa una comprobación para ver el resumen.")
            self.refresh_accept_button()
            return
        items = self.flow.findings()
        remaining = [item for item in items if not self.flow.is_accepted(item)]
        self.notice_var.set(f"{len(remaining)} pendientes. Selecciona un aviso para aceptarlo con un motivo." if remaining else "Listo para exportar con las opciones y aceptaciones indicadas.")
        for item in items:
            accepted = self.flow.is_accepted(item)
            status = "Aceptado" if accepted else ("Revisar" if item.waivable else "Pendiente")
            detail = item.detail + (" · " + self.flow.waivers[item.code]["reason"] if accepted else "")
            self.results.insert("", "end", iid="issue:" + item.code, values=(status, item.title, detail), tags=("accepted" if accepted else "warning" if item.waivable else "pending",))
        if self.flow.state.get("drc") == "0":
            self.results.insert("", "end", iid="ok:drc", values=("Correcto", "DRC", "0 errores registrados"))
        if self.flow.state.get("unrouted") == "0":
            self.results.insert("", "end", iid="ok:connections", values=("Correcto", "Conexiones sin rutear", "0 pendientes, comprobadas automáticamente en Allegro"))
        if all(self.flow.state.get(key) == "0" for key in ("mask_pins", "mask_vias", "mask_extras", "mask_conflicts")):
            self.results.insert("", "end", iid="ok:mask", values=("Correcto", "Máscara de soldadura", "Pines y vías conformes; sin aberturas adicionales"))
        if not self.flow.policy.check_texts or self.flow.policy.excluded_refs:
            self.results.insert("", "end", iid="ok:policy", values=("Omitido", "Referencias de serigrafía", "Comprobación desactivada por decisión del usuario" if not self.flow.policy.check_texts else "Ausencia intencionada: " + ", ".join(self.flow.policy.excluded_refs)))
        if self.flow.persisted.get("checked"):
            self.results.insert("", "end", iid="ok:copy", values=("Comprobada", "Copia guardada", f"{self.flow.persisted.get('components', '?')} componentes leídos desde disco"))
        if selected and self.results.exists(selected[0]):
            self.results.selection_set(selected[0])
        self.refresh_accept_button()

    def resize_content(self, event):
        self.canvas.itemconfigure(self.canvas_item, width=event.width)
        for child in self.content.winfo_children():
            if isinstance(child, ttk.Label):
                child.configure(wraplength=max(180, event.width - 12))

    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def choose_board(self):
        path = filedialog.askopenfilename(title="Seleccionar placa guardada", filetypes=[("Allegro PCB", "*.brd")])
        if path:
            self.select_board(path)

    def select_board(self, path):
        if self.task or (self.mailbox and self.mailbox.pending):
            messagebox.showinfo("Operación pendiente", "Espera a que termine la operación antes de cambiar de placa.")
            return
        path = Path(path).resolve()
        if not path.is_file() or path.suffix.lower() != ".brd":
            messagebox.showerror("Placa no válida", "Selecciona un archivo .brd guardado.")
            return
        self.flow = Workflow(str(path))
        self.check_text_var.set(True)
        self.excluded_var.set("")
        self.power_var.set("; ".join(self.flow.profile.power_nets))
        self.signal_var.set(str(self.flow.profile.signal_mm))
        self.width_var.set(str(self.flow.profile.power_mm))
        self.mailbox = None
        self.ticket = "-"
        self.board_var.set(str(path))
        self.placement_var.set(False)
        self.cam_var.set(False)
        self.set_export_path(latest_export(path))
        self.refresh_identity()
        profile_path = project_history(path) / "perfil.json"
        try:
            profile = Profile(**json.loads(profile_path.read_text(encoding="utf-8"))).validate()
            self.flow.profile = profile
            self.power_var.set("; ".join(profile.power_nets))
            self.signal_var.set(str(profile.signal_mm))
            self.width_var.set(str(profile.power_mm))
        except FileNotFoundError:
            pass
        except (ValueError, TypeError, OSError) as exc:
            self.write(f"No se ha cargado el perfil anterior: {exc}")
        try:
            policy_path = project_history(path) / "opciones_exportacion.json"
            self.flow.policy = ExportPolicy(**json.loads(policy_path.read_text(encoding="utf-8"))).validate()
            self.check_text_var.set(self.flow.policy.check_texts)
            self.excluded_var.set("; ".join(self.flow.policy.excluded_refs))
        except FileNotFoundError:
            pass
        except (ValueError, TypeError, OSError) as exc:
            self.write(f"No se han cargado las opciones anteriores: {exc}")
        self.write("Placa seleccionada. Conecta Allegro para ver su estado actual.")
        self.refresh_findings()

    def new_session(self):
        if not self.flow:
            raise ValueError("Selecciona primero una placa.")
        if self.task or (self.mailbox and self.mailbox.pending):
            raise ValueError("Hay una operación pendiente. No abras otra sesión hasta resolverla.")
        bridge = HERE / "bridge" / "pcb_assistant_bridge.il"
        str(bridge).encode("ascii")
        self.mailbox = Mailbox(HERE / "sessions" / uuid.uuid4().hex, self.flow.board)
        self.mailbox.bootstrap(bridge, CORE)
        return self.mailbox.root / "connect.scr"

    def attach(self):
        if self.demo:
            return self.demo_message()
        try:
            self.new_session()
            command = "skill load(" + skill_string(self.mailbox.root / "connect.il") + ")"
            self.clipboard_clear()
            self.clipboard_append(command)
            self.write("Pega una vez este comando en la consola de Allegro (ya está copiado):\n" + command)
            messagebox.showinfo("Conectar la placa abierta", "He copiado el comando de conexión. Pégalo en la consola de Allegro y pulsa Intro. Después vuelve a esta ventana.")
        except (ValueError, OSError, UnicodeError) as exc:
            messagebox.showerror("Conexión", str(exc) + "\nUsa la instalación en C:/SPB_Data/pcbenv/pcb_assistant.")

    def launch(self):
        if self.demo:
            return self.demo_message()
        try:
            active = subprocess.run(["tasklist", "/FI", "IMAGENAME eq allegro.exe", "/FO", "CSV", "/NH"],
                                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=8)
            if b'allegro.exe' in active.stdout.lower():
                raise ValueError("Allegro ya está abierto. Usa «Conectar con Allegro ya abierto» para trabajar con esa sesión.")
            script = self.new_session()
            subprocess.Popen([str(CADENCE / "allegro.exe"), "-s", str(script), self.flow.board],
                             cwd=Path(self.flow.board).parent)
            self.write("Allegro se está abriendo. La primera carga puede tardar; el asistente esperará la conexión.")
        except (ValueError, OSError, UnicodeError, subprocess.SubprocessError) as exc:
            messagebox.showerror("Abrir Allegro", str(exc))

    def read_profile(self):
        profile = Profile([name.strip() for name in self.power_var.get().split(";") if name.strip()],
                          float(self.signal_var.get().replace(",", ".")), float(self.width_var.get().replace(",", "."))).validate()
        if profile != self.flow.profile:
            self.flow.invalidate()
            self.cam_var.set(False)
            self.ticket = "-"
        self.flow.profile = profile
        return profile

    def run(self, action):
        if self.demo:
            return self.demo_message()
        if action == "references" and self.flow and (not self.flow.policy.check_texts or self.flow.policy.excluded_refs):
            messagebox.showinfo("Referencias omitidas", "Tus opciones conservan referencias ausentes. La recuperación general las volvería a crear; usa la edición manual para recuperar solo las que quieras. No se ha modificado ningún texto.")
            return
        try:
            if self.task or not self.mailbox or not self.flow:
                raise ValueError("Conecta Allegro y espera a que termine la operación actual.")
            profile = self.read_profile()
            self.mailbox.submit(action, profile, self.ticket, self.flow.policy, self.flow.waiver_tokens() if action == "export" else [])
            self.logged_pending = False
            self.write(f"Enviado a Allegro: {action}. Esperando el resultado; no se repetirá el comando.")
            self.refresh_buttons()
            return True
        except (ValueError, OSError, UnicodeError) as exc:
            self.finalizing = False
            messagebox.showerror("No se ha ejecutado la operación", str(exc))
            return False

    def confirmations(self):
        if self.flow:
            self.flow.placement_confirmed = self.placement_var.get()
            self.flow.cam_confirmed = self.cam_var.get()
            self.refresh_findings()

    def prepare_export(self):
        self.finalizing = True
        self.cam_var.set(False)
        self.run("review")

    def export(self):
        if self.demo:
            return self.demo_message()
        if not self.flow:
            return
        try:
            self.read_profile()
            self.update_policy()
            self.confirmations()
            blockers = self.flow.export_blockers()
            if blockers:
                self.write("Antes de exportar:\n• " + "\n• ".join(blockers))
                return
            self.refresh_identity()
            if not self.project_binding:
                self.notice_var.set("Declara la identidad y revisión PCB antes de crear una liberación nueva.")
                self.edit_identity()
                return
            self.export_record = self.flow.export_record()
            self.export_record.update(profile=vars(self.flow.profile), saved_board_sha256_at_submit=digest(self.flow.board),
                                      saved_board_observed_utc=now())
            self.release_reservation = reserve_release(self.flow.board, self.project_binding)
            if not self.run("export"):
                fail_release(self.release_reservation, "La operación no llegó a enviarse.")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Perfil", str(exc))

    def refresh_buttons(self):
        ready = self.demo or (self.mailbox and self.mailbox.connection()[0] and not self.mailbox.pending and not self.task)
        for button in self.action_buttons:
            button.configure(state="normal" if ready else "disabled")
        self.refresh_accept_button()

    def poll(self):
        try:
            if self.mailbox:
                connected, label = self.mailbox.connection()
                if self.mailbox.pending:
                    label = "Operación en curso · esperando Allegro"
                self.connection_var.set(label)
                received = self.mailbox.poll()
                if received:
                    self.receive(*received)
                elif self.mailbox.pending and time.monotonic() - self.mailbox.started > 120 and not self.logged_pending:
                    self.write("Allegro sigue sin responder. Comprueba si tiene un diálogo abierto o pide terminar la herramienta activa. No reenvíes la operación; el asistente mantiene la espera.")
                    self.logged_pending = True
            while True:
                try:
                    kind, payload = self.events.get_nowait()
                except queue.Empty:
                    break
                self.task = False
                if kind == "verified":
                    if payload["components"] != int(self.flow.state.get("placed", "-1")):
                        payload["ok"] = False
                        payload["component_mismatch"] = True
                        self.write("El número de componentes de la copia no coincide con Allegro. Se bloquea la exportación.")
                    self.flow.persisted = payload
                    append_history(project_history(self.flow.board), {"time": time.time(), "action": "persisted_refs", **payload})
                    if payload["ok"]:
                        self.write(f"Copia guardada comprobada: {payload['components']} componentes con una referencia de silkscreen cada uno. El recuento de conexiones pendientes está en la tabla; revisa colocación y CAM.")
                    else:
                        self.write("La copia guardada requiere revisión. Referencias ausentes: " + ", ".join(payload["missing"]) +
                                   ". Duplicadas: " + ", ".join(payload["duplicates"]))
                else:
                    self.flow.persisted = {}
                    self.write("No se ha podido comprobar la copia guardada: " + str(payload))
                self.finalizing = False
                self.refresh_findings()
            self.refresh_buttons()
        except (ValueError, OSError) as exc:
            if self.poll_error != str(exc):
                self.write("Revisar conexión o resultado: " + str(exc))
                self.poll_error = str(exc)
            # Do not discard a pending mutating request or retry it.
        self.after(900, self.poll)

    def receive(self, action, result):
        self.flow.accept(action, result)
        append_history(project_history(self.flow.board), {"time": time.time(), **result, "action": "export_generated" if action == "export" else action})
        self.write(result.get("log", "") + f"\nResultado de {action}: {result['status']}.")
        if result["status"] != "ok":
            self.flow.invalidate()
            self.finalizing = False
            if action == "export":
                fail_release(self.release_reservation, result.get("log", "Error de generación"))
            self.notice_var.set("La operación no terminó. Consulta «Ver detalle técnico» para ver el error.")
            self.refresh_findings()
            return
        self.summary_var.set(f"Colocados: {result.get('placed', '?')} · Sin colocar: {result.get('unplaced', '?')} · "
                             f"Sin rutear: {result.get('unrouted', '?')} · "
                             f"DRC registrados: {result.get('drc', '?')} · Rellenos pendientes: {result.get('shapes', '?')} · "
                             f"Referencias ausentes: {result.get('missing', '?')}")
        self.cam_var.set(False)
        self.flow.cam_confirmed = False
        if action == "widths":
            folder = project_history(self.flow.board)
            (folder / "perfil.json").write_text(json.dumps(vars(self.flow.profile), ensure_ascii=False, indent=2), encoding="utf-8")
        nets = result.get("nets", [])
        if action == "inspect":
            self.write("Redes de la placa: " + "; ".join(nets) + "\nCompara esta lista con las redes de alimentación del paso 3.")
        if action == "snapshot":
            self.ticket = result["id"]
            self.task = True
            snapshot = result.get("snapshot")
            def worker():
                try:
                    proof = verify_snapshot(snapshot, CADENCE / "extracta.exe", HERE / "scratch")
                    self.events.put(("verified", proof))
                except Exception as exc:
                    self.events.put(("error", str(exc)))
            threading.Thread(target=worker, daemon=True).start()
        elif action == "review" and self.finalizing:
            self.run("snapshot")
        elif action == "export":
            try:
                entry = seal_release(result["zip"], self.export_record, self.release_reservation, result["source_snapshot"])
                remember_export(self.flow.board, result["zip"])
                self.set_export_path(result["zip"])
                append_history(project_history(self.flow.board), {"time": time.time(), "action": "export", "status": "ok", "zip": result["zip"],
                                                                 "fabrication_release_id": entry["fabrication_release_id"], "release_label": entry["release_label"]})
                self.notice_var.set(f"{entry['release_label']} sellada · PCB {entry['pcb_revision']}. Informes y procedencia incluidos en el ZIP.")
                self.refresh_identity()
            except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
                fail_release(self.release_reservation, str(exc))
                self.notice_var.set("Generación sin sellar. Consulta el detalle; no se ha registrado como liberación final.")
                self.write("No se selló la liberación: " + str(exc))
                self.flow.state["status"] = "error"
                return
            self.write("Paquete generado: " + result.get("zip", "(ver informe)") +
                       ("\nHay avisos: revisa logs e informe del ZIP." if result.get("warnings") != "0" else "\nAbre el ZIP en tu visor CAM antes de fabricar."))
            if messagebox.askyesno("Liberación lista",
                f"La liberación {entry['release_label']} de la PCB {entry['pcb_revision']} ya está sellada.\n\n"
                "¿Quieres abrir ahora este BRD y este ZIP exacto en el Editor PCB y serigrafías?",
                parent=self):
                try:
                    from editor_handoff import launch_editor
                    launch_editor(self.flow.board, result['zip'])
                except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
                    messagebox.showerror("No se pudo abrir el editor",
                        str(exc)+"\n\nPuedes abrir «Editor PCB y serigrafías» desde «Apps de Luis» y elegir el mismo archivo .brd.",parent=self)
        if action != "export":
            self.refresh_findings()

    def refresh_identity(self):
        if not self.flow:
            return
        try:
            self.project_binding = load_binding(self.flow.board)
            if self.project_binding:
                binding = self.project_binding
                self.identity_var.set(f"{binding['project_name']} · PCB {binding['pcb_revision']} · " + association_status(self.flow.board, binding))
            else:
                self.identity_var.set("Sin identidad/revisión PCB declarada · ZIP anteriores: históricos sin asociación nueva.")
        except (OSError, ValueError, KeyError) as exc:
            self.project_binding = None
            self.identity_var.set("Revisar identidad: " + str(exc))

    def edit_identity(self):
        if not self.flow or self.demo:
            return
        if self.task or (self.mailbox and self.mailbox.pending):
            messagebox.showinfo("Operación pendiente", "Espera a que termine antes de cambiar la revisión.")
            return
        self.refresh_identity()
        dialog = tk.Toplevel(self)
        dialog.title("Identidad y revisión de esta placa")
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Una placa física mantiene su identidad aunque cambie el nombre del archivo.", wraplength=640).pack(anchor="w", pady=8)
        projects = available_projects(self.flow.board)
        labels = ["Nueva identidad de placa"] + [f"{item['project_name']} ({item['project_id'][:8]})" for item in projects]
        selected = tk.StringVar(value=labels[0])
        name = tk.StringVar(value=self.project_binding["project_name"] if self.project_binding else Path(self.flow.board).stem)
        revision = tk.StringVar(value=self.project_binding["pcb_revision"] if self.project_binding else "")
        note = tk.StringVar()
        if self.project_binding:
            for index, item in enumerate(projects, 1):
                if item["project_id"] == self.project_binding["project_id"]:
                    selected.set(labels[index])
        ttk.Combobox(frame, textvariable=selected, values=labels, state="readonly", width=70).pack(fill="x", pady=5)
        for label, variable in (("Nombre de la placa", name), ("Revisión PCB (MAYOR.MENOR, por ejemplo 1.0)", revision), ("Motivo de la declaración o cambio", note)):
            ttk.Label(frame, text=label).pack(anchor="w", pady=(8, 2))
            ttk.Entry(frame, textvariable=variable).pack(fill="x")
        ttk.Label(frame, text="Cobre, circuito, taladros, contorno o colocación: mayor (1.0 → 2.0). Solo serigrafía/documentación: menor (1.0 → 1.1). Reexportar no cambia la revisión. No se atribuyen datos a ZIP antiguos.", wraplength=640).pack(anchor="w", pady=14)
        def save():
            try:
                index = labels.index(selected.get())
                identifier = projects[index - 1]["project_id"] if index else None
                self.project_binding = bind_board(self.flow.board, name.get(), revision.get().strip(), identifier, note.get())
                self.refresh_identity()
                self.set_export_path(latest_export(self.flow.board))
                dialog.destroy()
            except (OSError, ValueError, KeyError) as exc:
                messagebox.showerror("Identidad", str(exc), parent=dialog)
        ttk.Button(frame, text="Guardar vinculación", command=save).pack(anchor="e")

    def show_releases(self):
        if not self.flow or self.demo:
            return
        self.refresh_identity()
        if not self.project_binding:
            return self.edit_identity()
        history = releases(self.project_binding)
        dialog = tk.Toplevel(self)
        dialog.title("Liberaciones y recuperación")
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Cada liberación conserva su ZIP y copia BRD. Selecciona dos para comparar; recuperar crea otro archivo y conserva el original.", wraplength=850).pack(anchor="w", pady=8)
        tree = ttk.Treeview(frame, columns=("release", "rev", "date", "status"), show="headings", height=10, selectmode="extended")
        for column, label, width in (("release", "Liberación", 95), ("rev", "PCB", 80), ("date", "UTC", 250), ("status", "Estado", 320)):
            tree.heading(column, text=label)
            tree.column(column, width=int(width * self.dpi_scale))
        tree.pack(fill="both", expand=True)
        indexed = {entry["fabrication_release_id"]: entry for entry in history}
        status_labels = {"pending_cam_review": "Pendiente de revisión CAM", "pending_cam_review_with_warnings": "Pendiente CAM · con avisos"}
        for entry in history:
            display_date = entry["created_utc"][:19].replace("T", " ") + " UTC"
            tree.insert("", "end", iid=entry["fabrication_release_id"], values=(entry["release_label"], entry["pcb_revision"], display_date, status_labels.get(entry["release_status"], entry["release_status"])))
        def chosen():
            return [indexed[key] for key in tree.selection()]
        def folder():
            items = chosen()
            if items:
                os.startfile(local(self.project_binding["root"], items[0]["archive_project_path"]).parent)
        def compare():
            try:
                items = chosen()
                if len(items) != 2:
                    raise ValueError("Selecciona dos liberaciones para comparar.")
                result = compare_releases(self.project_binding, *items)
                messagebox.showinfo("Comparación de liberaciones", f"{result['first']} → {result['second']}\nPCB: {' → '.join(result['pcb_revisions'])}\n\nArchivos cambiados:\n" + "\n".join(result["changed"]) + "\n\nAñadidos:\n" + "\n".join(result["added"]) + "\n\nRetirados:\n" + "\n".join(result["removed"]), parent=dialog)
            except (OSError, ValueError, KeyError) as exc:
                messagebox.showerror("Comparación", str(exc), parent=dialog)
        def recover():
            import shutil
            try:
                items = chosen()
                if len(items) != 1:
                    raise ValueError("Selecciona una liberación.")
                entry = items[0]
                source = local(self.project_binding["root"], entry["source_board"]["project_relative_path"])
                if digest(source) != entry["source_board"]["sha256"]:
                    raise ValueError("La copia de origen no coincide con su hash.")
                target = filedialog.asksaveasfilename(parent=dialog, title="Recuperar como otro BRD", initialdir=Path(self.flow.board).parent,
                                                     initialfile=Path(self.flow.board).stem + "_recuperada_" + entry["release_label"] + ".brd", defaultextension=".brd")
                if not target:
                    return
                target = Path(target).resolve()
                if target.parent != Path(self.flow.board).resolve().parent or target.suffix.lower() != ".brd":
                    raise ValueError("Guarda la copia .brd en la misma carpeta de Allegro.")
                with source.open("rb") as original, target.open("xb") as output:
                    shutil.copyfileobj(original, output)
                bind_board(target, entry["project_name"], entry["pcb_revision"], entry["project_id"], "Recuperada de " + entry["release_label"])
                messagebox.showinfo("Copia recuperada", "Se ha creado otro archivo, sin cambiar la placa abierta:\n" + str(target), parent=dialog)
            except (OSError, ValueError, KeyError) as exc:
                messagebox.showerror("Recuperación", str(exc), parent=dialog)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=10)
        for label, callback in (("Abrir carpeta", folder), ("Comparar seleccionadas", compare), ("Recuperar copia BRD…", recover)):
            ttk.Button(buttons, text=label, command=callback).pack(side="left", padx=4)

    def set_export_path(self, path):
        self.last_zip = Path(path) if path else None
        self.export_path_var.set(str(self.last_zip) if self.last_zip else "Todavía no hay un ZIP exportado de esta placa")
        for button in (self.export_folder_button, self.copy_export_button):
            button.configure(state="normal" if self.last_zip and self.last_zip.is_file() else "disabled")

    def open_export_folder(self):
        if self.last_zip and self.last_zip.is_file():
            os.startfile(self.last_zip.parent)

    def copy_export_path(self):
        if self.last_zip:
            self.clipboard_clear()
            self.clipboard_append(str(self.last_zip))

    def open_results(self):
        if self.flow and not self.demo:
            path = project_history(self.flow.board)
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(path)

    def demo_message(self):
        self.write("Demostración: esta ventana muestra el flujo de trabajo. No hay operaciones conectadas a Allegro.")

    def _demo(self):
        self.board_var.set("Ejemplo · Fuente de alimentación / PlugInPSU.brd")
        self.connection_var.set("Demostración · sin conexión")
        self.summary_var.set("Ejemplo: 15 colocados · 0 sin colocar · 0 DRC · 0 conexiones sin rutear")
        self.power_var.set("DCIN; +VIN; -VIN; 0; +12V; VEE")
        self.write("Vista de demostración. Recorre los seis pasos para conocer el asistente.\nLas utilidades existentes siguen funcionando de forma independiente.")

    def close(self):
        if self.task or (self.mailbox and self.mailbox.pending):
            if not messagebox.askyesno("Operación pendiente", "Allegro puede seguir trabajando aunque cierres esta ventana. El comando no se cancela. ¿Cerrar el asistente?"):
                return
        self.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--board")
    args = parser.parse_args()
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    app = Assistant(demo=args.demo, board=args.board)
    app.mainloop()


if __name__ == "__main__":
    main()
