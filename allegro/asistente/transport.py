"""Local, board-bound mailbox. Requests are data, never executable SKILL."""
from pathlib import Path
import json
import os
import time
import uuid

from workflow import ACTIONS, Profile, board_key


def skill_string(value):
    value = str(value).replace("\\", "/")
    if any(c in value for c in "\r\n\t"):
        raise ValueError("Ruta no válida.")
    return '"' + value.replace('"', '\\"') + '"'


def parse_fields(path):
    result = {}
    for line in Path(path).read_text(encoding="cp1252").splitlines():
        key, sep, value = line.partition("\t")
        if sep:
            if key in result and key != "net":
                raise ValueError("Respuesta incompleta o duplicada.")
            if key == "net":
                result.setdefault("nets", []).append(value)
            else:
                result[key] = value
    return result


class Mailbox:
    def __init__(self, root, board, token=None):
        self.root = Path(root)
        self.board = str(Path(board).resolve()).replace("\\", "/")
        self.token = token or uuid.uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        self.pending = None
        self.started = None

    def bootstrap(self, bridge, core):
        script = self.root / "connect.scr"
        text = (f"skill load({skill_string(bridge)})\n"
                f"skill pcbwaStart({skill_string(self.root)} {skill_string(self.token)} {skill_string(core)})\n")
        script.write_text(text, encoding="cp1252")
        (self.root / "connect.il").write_text(text.replace("skill ", ""), encoding="cp1252")
        return script

    def connection(self, max_age=6):
        path = self.root / "heartbeat.tsv"
        if not path.is_file() or time.time() - path.stat().st_mtime > max_age:
            return False, "Esperando conexión con Allegro"
        try:
            state = parse_fields(path)
        except (OSError, ValueError, UnicodeError):
            return False, "Esperando una respuesta completa"
        if state.get("token") != self.token:
            return False, "La sesión de Allegro ha cambiado"
        if board_key(state.get("board", "")) != board_key(self.board):
            return False, "Allegro tiene abierta otra placa"
        return True, "Conectado a la placa seleccionada"

    def submit(self, action, profile: Profile, ticket="-"):
        if action not in ACTIONS:
            raise ValueError("Acción no permitida.")
        if self.pending or (self.root / "request.tsv").exists():
            raise ValueError("Ya hay una operación pendiente. No se repetirá automáticamente.")
        connected, reason = self.connection()
        if not connected:
            raise ValueError(reason)
        profile.validate()
        job = uuid.uuid4().hex
        fields = ["PCBWA1", self.token, job, action, self.board,
                  "|".join(profile.power_nets) or "-", str(profile.signal_mm), str(profile.power_mm), ticket]
        payload = "\n".join(fields) + "\n"
        temporary = self.root / "request.tmp"
        temporary.write_bytes(payload.encode("cp1252", errors="strict"))
        os.replace(temporary, self.root / "request.tsv")
        self.pending, self.started = (job, action), time.monotonic()
        return job

    def poll(self):
        if not self.pending:
            return None
        job, action = self.pending
        path = self.root / f"{job}.result.tsv"
        if not path.exists():
            return None
        result = parse_fields(path)
        if result.get("complete") != "1":
            return None
        if result.get("id") != job or result.get("token") != self.token or result.get("action") != action:
            raise ValueError("Respuesta de otra operación; no se acepta.")
        if board_key(result.get("board", "")) != board_key(self.board):
            raise ValueError("La placa activa ha cambiado; no se acepta el resultado.")
        log = self.root / f"{job}.log"
        result["log"] = log.read_text(encoding="cp1252", errors="replace") if log.exists() else ""
        self.pending = None
        return action, result


def append_history(folder, record):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "historial.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
