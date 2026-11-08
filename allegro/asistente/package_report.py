"""Add the user's review decisions to a generated package, atomically."""
import hashlib
import json
import os
from pathlib import Path
import uuid
import zipfile


def annotate_package(archive_path, record):
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
            manifest.setdefault("generator_status", manifest["status"])
            manifest["assistant_review"] = dict(version=record["assistant_version"], report=entry,
                                                check_texts=record["policy"]["check_texts"],
                                                excluded_refs=record["policy"]["excluded_refs"],
                                                accepted_count=len(record["accepted"]))
            if record["accepted"] or not record["policy"]["check_texts"] or record["policy"]["excluded_refs"]:
                manifest["status"] = "EXPORTADO_CON_EXCEPCIONES_USUARIO"
            readme = None
            if "LEEME_FABRICACION.txt" in original.namelist():
                lines = original.read("LEEME_FABRICACION.txt").decode("utf-8-sig").splitlines()
                lines = ["Estado: " + manifest["status"] if line.startswith("Estado:") else line for line in lines]
                lines += ["", "Estado de los generadores: " + manifest["generator_status"],
                          "Decisiones del asistente y avisos aceptados: informes/ASISTENTE_REVISION.json"]
                readme = ("\n".join(lines) + "\n").encode("utf-8")
                for item in manifest["files"]:
                    if item["name"] == "LEEME_FABRICACION.txt":
                        item.update(bytes=len(readme), sha256=hashlib.sha256(readme).hexdigest())
            manifest["files"] = [item for item in manifest["files"] if item["name"] != entry]
            manifest["files"].append(dict(name=entry, bytes=len(report), sha256=hashlib.sha256(report).hexdigest()))
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
