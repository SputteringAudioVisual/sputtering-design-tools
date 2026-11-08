"""Rules for the external assistant. No dependency on Allegro or the GUI."""
from dataclasses import dataclass, field
from pathlib import Path
import math
import hashlib
import json
import time

VERSION = "0.2.0-beta"
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
class ExportPolicy:
    check_texts: bool = True
    excluded_refs: list[str] = field(default_factory=list)

    def validate(self):
        if type(self.check_texts) is not bool or len(self.excluded_refs) > 500:
            raise ValueError("Opciones de serigrafía no válidas.")
        for ref in self.excluded_refs:
            if not isinstance(ref, str) or not ref.strip() or len(ref) > 128 or any(c in ref for c in "|;\t\r\n"):
                raise ValueError("Indica referencias concretas separadas por punto y coma.")
            ref.encode("cp1252", errors="strict")
        self.excluded_refs = sorted(set(ref.strip().upper() for ref in self.excluded_refs))
        return self


@dataclass(frozen=True)
class Finding:
    code: str
    title: str
    detail: str
    waivable: bool = False
    value: str = ""

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(vars(self), sort_keys=True).encode("utf-8")).hexdigest()


@dataclass
class Workflow:
    board: str
    profile: Profile = field(default_factory=Profile)
    placement_confirmed: bool = False
    cam_confirmed: bool = False
    state: dict = field(default_factory=dict)
    persisted: dict = field(default_factory=dict)
    reviewed: bool = False
    policy: ExportPolicy = field(default_factory=ExportPolicy)
    waivers: dict = field(default_factory=dict)

    def invalidate(self):
        self.cam_confirmed = False
        self.persisted = {}
        self.reviewed = False
        self.waivers.clear()

    def accept(self, action, result):
        if board_key(result.get("board", "")) != board_key(self.board):
            raise ValueError("Allegro tiene abierta otra placa. No se acepta este resultado.")
        if action in MUTATING:
            self.invalidate()
        self.state = result
        if action == "review" and result.get("status") == "ok" and str(result.get("fresh_drc", "")).isdigit():
            self.reviewed = True

    def relevant_refs(self, names):
        excluded = set(self.policy.excluded_refs)
        return sorted(ref for ref in names if ref.upper() not in excluded)

    def findings(self):
        findings = []
        def add(code, title, detail, waivable=False, value=""):
            findings.append(Finding(code, title, detail, waivable, value))
        if not self.reviewed:
            add("review", "Falta la comprobación final", "Pulsa «Revisar DRC y comprobar copia guardada».")
        if self.state.get("status") != "ok":
            add("operation", "Revisión sin terminar", "Conecta la placa y espera el resultado de Allegro.")
        for key, label in (("unplaced", "Componentes sin colocar"), ("drc", "DRC detectados"),
                           ("unrouted", "Conexiones sin rutear"), ("unplaced_pins", "Pines sin colocar"),
                           ("shapes", "Rellenos pendientes de actualizar"), ("mask_pins", "Pines con máscara pendiente"),
                           ("mask_vias", "vías con abertura"), ("mask_extras", "aberturas adicionales de máscara"),
                           ("mask_conflicts", "vías expuestas por otras aberturas")):
            value = str(self.state.get(key, ""))
            if value != "0":
                known = value.isdigit()
                detail = f"Cantidad: {value}." if known else "Todavía sin comprobar. Recarga la conexión y repite la revisión."
                if key == "unrouted" and known and self.state.get("unrouted_nets"):
                    detail += " Redes: " + "; ".join(self.state["unrouted_nets"])
                add(key, label[0].upper() + label[1:], detail,
                    known and key != "shapes", value)
        if self.policy.check_texts:
            missing = self.relevant_refs(self.persisted.get("missing", self.state.get("missing_refs", [])))
            duplicates = self.relevant_refs(self.persisted.get("duplicates", []))
            if missing:
                add("missing", "Referencias de serigrafía ausentes", ", ".join(missing), True, str(len(missing)))
            elif "missing_refs" not in self.state and self.state.get("missing", "0") != "0" and not self.persisted:
                add("missing", "Referencias de serigrafía por comprobar", "Comprueba la copia para ver los nombres concretos.")
            if duplicates:
                add("duplicates", "Referencias de serigrafía duplicadas", ", ".join(duplicates), True, str(len(duplicates)))
            if not self.persisted.get("checked", self.persisted.get("ok", False)):
                add("persisted", "Falta comprobar la copia guardada", "Comprobar las referencias de una copia guardada antes de decidir qué omitir.")
        if self.persisted.get("component_mismatch"):
            add("copy_mismatch", "La copia no coincide con Allegro", "Repite la comprobación final con la placa correcta.")
        if not self.placement_confirmed:
            add("placement", "Confirmar colocación", "Marca «He revisado colocación, polaridades y conectores» en esta pantalla.")
        if not self.cam_confirmed:
            add("cam", "Confirmar revisión CAM", "Marca que revisarás Gerber y taladros antes de fabricar.")
        return findings

    def is_accepted(self, finding):
        waiver = self.waivers.get(finding.code, {})
        return waiver.get("fingerprint") == finding.fingerprint and bool(waiver.get("reason"))

    def accept_finding(self, code, reason):
        finding = next((item for item in self.findings() if item.code == code), None)
        if not finding or not finding.waivable:
            raise ValueError("Esta comprobación necesita completarse; no es un aviso aceptable.")
        reason = reason.strip()
        if not reason:
            raise ValueError("Escribe el motivo por el que aceptas este aviso.")
        self.waivers[code] = dict(fingerprint=finding.fingerprint, reason=reason, title=finding.title,
                                 detail=finding.detail, value=finding.value, time=time.time())

    def export_blockers(self):
        return [f"{item.title}: {item.detail}" for item in self.findings() if not self.is_accepted(item)]

    def waiver_tokens(self):
        native_codes = {"unplaced", "unrouted", "unplaced_pins", "drc", "mask_pins", "mask_vias", "mask_extras", "mask_conflicts", "missing"}
        return [f"{item.code}:{item.value}" for item in self.findings()
                if item.code in native_codes and self.is_accepted(item)]

    def export_record(self):
        return dict(assistant_version=VERSION, board=self.board, time=time.time(), policy=vars(self.policy),
                    accepted=[dict(code=item.code, **self.waivers[item.code]) for item in self.findings() if self.is_accepted(item)],
                    snapshot=self.persisted.copy(), checks={k: v for k, v in self.state.items() if k != "log"})


def project_history(board):
    path = Path(board)
    return path.parent / "Asistente" / path.stem
