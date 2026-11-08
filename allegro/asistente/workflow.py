"""Rules for the external assistant. No dependency on Allegro or the GUI."""
from dataclasses import dataclass, field
from pathlib import Path
import math

VERSION = "0.1.0-beta"
STEPS = (
    "1 · Abrir y conectar", "2 · Colocar componentes", "3 · Preparar reglas",
    "4 · Rutear", "5 · Revisar la placa", "6 · Exportar fabricación",
)
ACTIONS = frozenset({"inspect", "widths", "mask", "references", "review", "snapshot", "save", "export"})
MUTATING = frozenset({"widths", "mask", "references", "review", "save", "export"})


def board_key(path):
    return str(path).replace("\\", "/").rstrip("/").casefold()


@dataclass
class Profile:
    power_nets: list[str] = field(default_factory=lambda: ["+12V", "-12V", "0", "GND", "VCC", "VEE", "VDD"])
    signal_mm: float = 0.4
    power_mm: float = 0.8

    def validate(self):
        for value in (self.signal_mm, self.power_mm):
            if not math.isfinite(value) or not 0.1 <= value <= 10:
                raise ValueError("Los anchos deben estar entre 0,1 y 10 mm.")
        if len(self.power_nets) > 128:
            raise ValueError("Hay demasiadas redes de alimentación.")
        for net in self.power_nets:
            if not net or len(net) > 128 or any(c in net for c in "|\t\r\n"):
                raise ValueError("Nombre de red no válido.")
            net.encode("cp1252", errors="strict")
        return self


@dataclass
class Workflow:
    board: str
    profile: Profile = field(default_factory=Profile)
    placement_confirmed: bool = False
    connections_confirmed: bool = False
    cam_confirmed: bool = False
    state: dict = field(default_factory=dict)
    persisted: dict = field(default_factory=dict)
    reviewed: bool = False

    def invalidate(self):
        self.connections_confirmed = False
        self.cam_confirmed = False
        self.persisted = {}
        self.reviewed = False

    def accept(self, action, result):
        if board_key(result.get("board", "")) != board_key(self.board):
            raise ValueError("Allegro tiene abierta otra placa. No se acepta este resultado.")
        if action in MUTATING:
            self.invalidate()
        self.state = result
        if action == "review" and result.get("status") == "ok" and result.get("fresh_drc") == "0":
            self.reviewed = True

    def export_blockers(self):
        reasons = []
        if not self.reviewed:
            reasons.append("Ejecutar una revisión completa reciente de rellenos y DRC.")
        if self.state.get("status") != "ok":
            reasons.append("Falta una revisión terminada correctamente.")
        for key, label in (("unplaced", "componentes sin colocar"), ("drc", "errores DRC"),
                           ("shapes", "rellenos pendientes"), ("mask_pins", "pines sin máscara correcta"),
                           ("mask_vias", "vías con abertura"), ("mask_extras", "aberturas adicionales de máscara"),
                           ("mask_conflicts", "vías expuestas por otras aberturas"), ("missing", "referencias ausentes")):
            if self.state.get(key) != "0":
                reasons.append(f"Revisar {label} ({self.state.get(key, 'sin comprobar')}).")
        if not self.placement_confirmed:
            reasons.append("Confirmar colocación, polaridades y conectores.")
        if not self.connections_confirmed:
            reasons.append("Confirmar en Allegro que quedan cero conexiones sin rutear.")
        if not self.persisted.get("ok"):
            reasons.append("Comprobar las referencias de una copia guardada.")
        if not self.cam_confirmed:
            reasons.append("Confirmar que se revisará el ZIP en un visor CAM antes de fabricarlo.")
        return reasons


def project_history(board):
    path = Path(board)
    return path.parent / "Asistente" / path.stem
