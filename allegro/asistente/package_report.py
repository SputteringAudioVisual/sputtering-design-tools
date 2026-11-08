"""Add the user's review decisions to a generated package, atomically."""
import hashlib
import json
import os
from pathlib import Path
import uuid
import zipfile

from workflow import project_history
from traceability import SCHEMA, file_role, load_binding, local, project_root, releases


def valid_export(board, value):
    path = Path(value).resolve()
    if not path.is_relative_to(project_root(board)) or not path.is_file() or path.suffix.lower() != ".zip":
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema") == SCHEMA:
            binding = load_binding(board)
            return bool(binding and manifest.get("project_id") == binding["project_id"])
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return False
    return path.is_relative_to(Path(board).resolve().parent) and path.stem.startswith(Path(board).stem + "_fab_v")


def latest_export(board):
    folder = project_history(board)
    try:
        binding = load_binding(board)
        for entry in releases(binding):
            path = local(binding["root"], entry["archive_project_path"])
            if valid_export(board, path):
                return path
    except (OSError, ValueError, KeyError):
        pass
    try:
        value = json.loads((folder / "ultima_exportacion.json").read_text(encoding="utf-8"))["zip"]
        if valid_export(board, value):
            return Path(value)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        for line in reversed((folder / "historial.jsonl").read_text(encoding="utf-8").splitlines()):
            record = json.loads(line)
            if record.get("action") == "export" and record.get("status") == "ok" and record.get("zip") and valid_export(board, record["zip"]):
                return Path(record["zip"])
    except (OSError, ValueError, TypeError):
        pass
    candidates = [path for path in (Path(board).parent / "Fabricacion").glob(Path(board).stem + "_fab_v*.zip") if valid_export(board, path)]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def remember_export(board, archive):
    if not valid_export(board, archive):
        raise ValueError("El ZIP no corresponde a esta placa dentro del proyecto.")
    folder = project_history(board)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ultima_exportacion.json").write_text(json.dumps({"zip": str(Path(archive).resolve())}, ensure_ascii=False), encoding="utf-8")


def annotate_package(archive_path, record, trace=None):
    archive_path = Path(archive_path).resolve()
    if not archive_path.is_relative_to(Path(record["board"]).resolve().parent):
        raise ValueError("El paquete no está dentro del proyecto.")
    entry = "informes/ASISTENTE_REVISION.json"
    report = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
    temporary = archive_path.with_name(archive_path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(archive_path) as original:
            if original.testzip():
                raise ValueError("El ZIP generado tiene un error de lectura.")
            manifest = json.loads(original.read("manifest.json"))
            if manifest.get("schema") == SCHEMA or manifest.get("fabrication_release_id"):
                raise ValueError("Esta liberación ya está sellada; genera un paquete nuevo.")
            for item in manifest["files"]:
                raw = original.read(item["name"])
                if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest().lower() != item["sha256"].lower():
                    raise ValueError("El paquete original no coincide con su inventario.")
            manifest.setdefault("generator_status", manifest["status"])
            manifest["assistant_review"] = dict(version=record["assistant_version"], report=entry,
                                                check_texts=record["policy"]["check_texts"],
                                                excluded_refs=record["policy"]["excluded_refs"],
                                                accepted_count=len(record["accepted"]))
            if record["accepted"] or not record["policy"]["check_texts"] or record["policy"]["excluded_refs"]:
                manifest["status"] = "EXPORTADO_CON_EXCEPCIONES_USUARIO"
            if trace:
                manifest.update(trace)
                manifest["release_status"] = "pending_cam_review" if manifest["status"] == "EXPORTADO_SIN_AVISOS" else "pending_cam_review_with_warnings"
            readme = None
            if "LEEME_FABRICACION.txt" in original.namelist():
                lines = original.read("LEEME_FABRICACION.txt").decode("utf-8-sig").splitlines()
                lines = ["Estado: " + manifest["status"] if line.startswith("Estado:") else line for line in lines]
                lines += ["", "Estado de los generadores: " + manifest["generator_status"],
                          "Decisiones del asistente y avisos aceptados: informes/ASISTENTE_REVISION.json"]
                if trace:
                    lines += [f"Placa: {trace['project_name']} · PCB {trace['pcb_revision']} · {trace['release_label']}",
                              "Identidad: " + trace["project_id"], "Liberacion: " + trace["fabrication_release_id"],
                              "Paquete inmutable; las ediciones Gerber requieren otra liberacion y procedencia."]
                readme = ("\n".join(lines) + "\n").encode("utf-8")
                for item in manifest["files"]:
                    if item["name"] == "LEEME_FABRICACION.txt":
                        item.update(bytes=len(readme), sha256=hashlib.sha256(readme).hexdigest())
            payloads = {item.filename: original.read(item) for item in original.infolist() if item.filename not in ("manifest.json", entry)}
            if readme:
                payloads["LEEME_FABRICACION.txt"] = readme
            payloads[entry] = report
            manifest["files"] = []
            for name, payload in sorted(payloads.items()):
                role, layer = file_role(name)
                manifest["files"].append(dict(path=name, name=name, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(), role=role, layer=layer))
            data = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED) as target:
                for item in original.infolist():
                    if item.filename not in ("manifest.json", entry) and not (readme and item.filename == "LEEME_FABRICACION.txt"):
                        target.writestr(item, original.read(item))
                if readme:
                    target.writestr("LEEME_FABRICACION.txt", readme)
                target.writestr(entry, report)
                target.writestr("manifest.json", data)
        with zipfile.ZipFile(temporary) as check:
            if check.testzip():
                raise ValueError("No se pudo verificar el ZIP con el informe.")
            for item in manifest["files"]:
                payload = check.read(item["name"])
                if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest().lower() != item["sha256"].lower():
                    raise ValueError("El manifiesto del ZIP no coincide con sus archivos.")
        os.replace(temporary, archive_path)
        folder = archive_path.with_suffix("")
        (folder / "ASISTENTE_REVISION.json").write_bytes(report)
        (folder / "manifest.json").write_bytes(data)
        if readme:
            (folder / "LEEME_FABRICACION.txt").write_bytes(readme)
    finally:
        if temporary.exists():
            temporary.unlink()
