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
from tkinter import filedialog, messagebox, ttk
import uuid

from saved_board import verify_snapshot
from transport import Mailbox, append_history, skill_string
from workflow import VERSION, STEPS, Profile, Workflow, project_history

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
        self.board_var = tk.StringVar(value="Selecciona la placa con la que vas a trabajar")
        self.connection_var = tk.StringVar(value="Sin conectar")
        self.summary_var = tk.StringVar(value="Las comprobaciones aparecerán aquí al conectar Allegro.")
        self.power_var = tk.StringVar(value="+12V; -12V; 0; GND; VCC; VEE; VDD")
        self.signal_var = tk.StringVar(value="0.40")
        self.width_var = tk.StringVar(value="0.80")
        self.placement_var = tk.BooleanVar()
        self.connections_var = tk.BooleanVar()
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
        ttk.Label(head, text="Resultados y próximos pasos", font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(head, text="Abrir carpeta de resultados", command=self.open_results).pack(side="right")
        frame = tk.Frame(logs)
        frame.pack(fill="both")
        self.log = tk.Text(frame, height=9, wrap="word", bg="#122138", fg="#e4edf9", bd=0,
                           padx=14, pady=10, font=("Consolas", 10), state="disabled")
        scrollbar = ttk.Scrollbar(frame, command=self.log.yview)
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
            self.text("Cero DRC no significa cero conexiones pendientes. Comprueba ambos indicadores en Allegro.", bold=True)
        elif index == 4:
            self.text("Revisa lo que se va a fabricar", bold=True)
            self.button("Actualizar rellenos y ejecutar DRC completo", lambda: self.run("review"), primary=True, native=True)
            self.button("Auditar textos, máscara, reglas y fabricación", lambda: self.run("inspect"), native=True)
            self.button("Recuperar referencias que falten", lambda: self.run("references"), native=True)
            self.button("Comprobar referencias en una copia guardada", lambda: self.run("snapshot"), native=True)
            self.button("Guardar la placa original (con copia previa)", lambda: self.run("save"), native=True)
            self.text("La limpieza que elimina textos queda fuera de esta beta mientras resolvemos el fallo de referencias al guardar. Las referencias recuperadas se crean en el origen del componente: revisa su posición.")
        else:
            self.text("Prepara una comprobación final reciente", bold=True)
            self.button("Revisar DRC y comprobar copia guardada", self.prepare_export, primary=True, native=True)
            ttk.Checkbutton(self.content, text="En Allegro figuran cero conexiones sin rutear",
                            variable=self.connections_var, command=self.confirmations).pack(anchor="w", pady=3)
            ttk.Checkbutton(self.content, text="Revisaré Gerber y taladros en un visor CAM antes de fabricar",
                            variable=self.cam_var, command=self.confirmations).pack(anchor="w", pady=3)
            self.button("Crear ZIP de fabricación con versión", self.export, primary=True, native=True)
            self.text("No edites la placa entre la comprobación final y la exportación. Si haces algún cambio, vuelve a comprobarla. La continuidad eléctrica exige tu confirmación; esta beta no la certifica automáticamente.")
            self.text("El ZIP, los informes y las copias se guardan dentro del proyecto. Si hay avisos de exportación, aparecen en los resultados y deben revisarse.")
        self.refresh_buttons()

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
        self.power_var.set("; ".join(self.flow.profile.power_nets))
        self.signal_var.set(str(self.flow.profile.signal_mm))
        self.width_var.set(str(self.flow.profile.power_mm))
        self.mailbox = None
        self.ticket = "-"
        self.board_var.set(str(path))
        self.placement_var.set(False)
        self.connections_var.set(False)
        self.cam_var.set(False)
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
        self.write("Placa seleccionada. Conecta Allegro para ver su estado actual.")

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
            self.connections_var.set(False)
            self.cam_var.set(False)
            self.ticket = "-"
        self.flow.profile = profile
        return profile

    def run(self, action):
        if self.demo:
            return self.demo_message()
        try:
            if self.task or not self.mailbox or not self.flow:
                raise ValueError("Conecta Allegro y espera a que termine la operación actual.")
            profile = self.read_profile()
            self.mailbox.submit(action, profile, self.ticket)
            self.logged_pending = False
            self.write(f"Enviado a Allegro: {action}. Esperando el resultado; no se repetirá el comando.")
            self.refresh_buttons()
        except (ValueError, OSError, UnicodeError) as exc:
            self.finalizing = False
            messagebox.showerror("No se ha ejecutado la operación", str(exc))

    def confirmations(self):
        if self.flow:
            self.flow.placement_confirmed = self.placement_var.get()
            self.flow.connections_confirmed = self.connections_var.get()
            self.flow.cam_confirmed = self.cam_var.get()

    def prepare_export(self):
        self.finalizing = True
        self.connections_var.set(False)
        self.cam_var.set(False)
        self.run("review")

    def export(self):
        if self.demo:
            return self.demo_message()
        if not self.flow:
            return
        try:
            self.read_profile()
            self.confirmations()
            blockers = self.flow.export_blockers()
            if blockers:
                self.write("Antes de exportar:\n• " + "\n• ".join(blockers))
                return
            self.run("export")
        except ValueError as exc:
            messagebox.showerror("Perfil", str(exc))

    def refresh_buttons(self):
        ready = self.demo or (self.mailbox and self.mailbox.connection()[0] and not self.mailbox.pending and not self.task)
        for button in self.action_buttons:
            button.configure(state="normal" if ready else "disabled")

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
                        self.write("El número de componentes de la copia no coincide con Allegro. Se bloquea la exportación.")
                    self.flow.persisted = payload
                    append_history(project_history(self.flow.board), {"time": time.time(), "action": "persisted_refs", **payload})
                    if payload["ok"]:
                        self.write(f"Copia guardada comprobada: {payload['components']} componentes con una referencia de silkscreen cada uno. Confirma ahora las conexiones sin rutear y la revisión CAM.")
                    else:
                        self.write("La copia guardada requiere revisión. Referencias ausentes: " + ", ".join(payload["missing"]) +
                                   ". Duplicadas: " + ", ".join(payload["duplicates"]))
                else:
                    self.flow.persisted = {}
                    self.write("No se ha podido comprobar la copia guardada: " + str(payload))
                self.finalizing = False
            self.refresh_buttons()
        except (ValueError, OSError) as exc:
            if self.poll_error != str(exc):
                self.write("Revisar conexión o resultado: " + str(exc))
                self.poll_error = str(exc)
            # Do not discard a pending mutating request or retry it.
        self.after(900, self.poll)

    def receive(self, action, result):
        self.flow.accept(action, result)
        append_history(project_history(self.flow.board), {"time": time.time(), **result})
        self.write(result.get("log", "") + f"\nResultado de {action}: {result['status']}.")
        if result["status"] != "ok":
            self.flow.invalidate()
            self.finalizing = False
            return
        self.summary_var.set(f"Colocados: {result.get('placed', '?')} · Sin colocar: {result.get('unplaced', '?')} · "
                             f"DRC registrados: {result.get('drc', '?')} · Rellenos pendientes: {result.get('shapes', '?')} · "
                             f"Referencias ausentes: {result.get('missing', '?')}")
        self.connections_var.set(False)
        self.cam_var.set(False)
        self.flow.connections_confirmed = False
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
            self.write("Paquete generado: " + result.get("zip", "(ver informe)") +
                       ("\nHay avisos: revisa logs e informe del ZIP." if result.get("warnings") != "0" else "\nAbre el ZIP en tu visor CAM antes de fabricar."))

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
        self.summary_var.set("Ejemplo: 15 colocados · 0 sin colocar · 0 DRC · conexiones por comprobar")
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
