"""Explicit PCB identities and immutable fabrication release records.

No old archive is migrated. Native board bytes never determine a revision label.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import time
import uuid
import zipfile

SCHEMA = "sputtering.fabrication.v1"
PROJECT_SCHEMA = "sputtering.pcb-identity.v1"
REVISION = re.compile(r"^[1-9][0-9]*\.(0|[1-9][0-9]*)$")


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def project_root(board):
    folder = Path(board).resolve().parent
    for parent in (folder, *list(folder.parents)[:2]):
        if parent.name.casefold() == "allegro":
            return parent.parent
    return folder


def local(root, relative):
    text = str(relative)
    if not text or "\\" in text or ":" in text or text.startswith("/") or any(part in (".", "..") for part in text.split("/")):
        raise ValueError("Referencia de archivo no válida.")
    path = (Path(root) / text).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("Referencia fuera del proyecto.")
    return path


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def locked(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / ".release.lock").open("a+b") as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        if os.name == "nt":
            import msvcrt
            def lock():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            def unlock():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def lock():
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def unlock():
                fcntl.flock(stream, fcntl.LOCK_UN)
        deadline = time.monotonic() + 8
        while True:
            try:
                lock()
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise ValueError("Otra ventana está registrando una liberación. Espera y vuelve a intentarlo.")
                time.sleep(.05)
        try:
            yield
        finally:
            unlock()


def binding_file(board):
    board = Path(board)
    return board.parent / "Asistente" / board.stem / "identidad_pcb.json"


def read_project(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != PROJECT_SCHEMA or str(uuid.UUID(data["project_id"])) != data["project_id"]:
        raise ValueError("Identidad de placa no reconocida.")
    if (type(data.get("next_fabrication_sequence")) is not int or data["next_fabrication_sequence"] < 1
            or not data.get("revisions") or any(not REVISION.fullmatch(label) for label in data["revisions"])
            or data.get("latest_declared_revision") not in data["revisions"] or not data.get("project_name")):
        raise ValueError("El registro de revisiones no es válido.")
    return data


def load_binding(board):
    try:
        link = json.loads(binding_file(board).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    root = project_root(board)
    path = local(root, link["project_relative_path"])
    data = read_project(path)
    if data["project_id"] != link["project_id"] or not REVISION.fullmatch(link["pcb_revision"]) or link["pcb_revision"] not in data["revisions"]:
        raise ValueError("La vinculación de la revisión PCB no coincide con su identidad.")
    return dict(root=str(root), project_file=str(path), project_id=data["project_id"],
                project_name=data["project_name"], pcb_revision=link["pcb_revision"],
                latest_declared_revision=data["latest_declared_revision"])


def available_projects(board):
    result = []
    for path in (project_root(board) / "Sputtering" / "pcb").glob("*/project.json"):
        try:
            data = read_project(path)
            result.append(dict(project_id=data["project_id"], project_name=data["project_name"], path=str(path)))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(result, key=lambda item: item["project_name"].casefold())


def bind_board(board, name, revision, existing_id=None, note=""):
    name = name.strip()
    if not name or len(name) > 160 or any(char in name for char in "\r\n\t") or not REVISION.fullmatch(revision):
        raise ValueError("Indica un nombre y una revisión MAYOR.MENOR, por ejemplo 1.0.")
    root = project_root(board)
    identifier = str(uuid.UUID(existing_id)) if existing_id else str(uuid.uuid4())
    path = root / "Sputtering" / "pcb" / identifier / "project.json"
    with locked(path.parent):
        if existing_id:
            data = read_project(path)
        else:
            if path.exists():
                raise ValueError("La identidad ya existe.")
            data = dict(schema=PROJECT_SCHEMA, project_id=identifier, project_name=name,
                        created_utc=now(), revisions={}, next_fabrication_sequence=1,
                        latest_declared_revision=revision, source_bindings=[])
        data["project_name"] = name
        data["revisions"].setdefault(revision, dict(declared_utc=now(), note=note.strip()))
        data["latest_declared_revision"] = max(data["revisions"], key=lambda value: tuple(map(int, value.split("."))))
        board_relative = Path(board).resolve().relative_to(root).as_posix()
        if board_relative not in data["source_bindings"]:
            data["source_bindings"].append(board_relative)
        atomic_json(path, data)
        atomic_json(binding_file(board), dict(project_id=identifier, pcb_revision=revision,
                                             project_relative_path=path.relative_to(root).as_posix(), linked_utc=now()))
    return load_binding(board)


def reserve_release(board, binding):
    current = load_binding(board)
    if not current or current["project_id"] != binding["project_id"] or current["pcb_revision"] != binding["pcb_revision"]:
        raise ValueError("Declara y vincula primero la identidad y revisión de esta placa.")
    path = Path(current["project_file"])
    with locked(path.parent):
        data = read_project(path)
        sequence = data["next_fabrication_sequence"]
        data["next_fabrication_sequence"] = sequence + 1
        release_id = str(uuid.uuid4())
        directory = path.parent / "releases" / release_id
        directory.mkdir(parents=True, exist_ok=False)
        reservation = dict(project_id=current["project_id"], project_name=current["project_name"],
                           pcb_revision=current["pcb_revision"], fabrication_release_id=release_id,
                           release_label=f"F{sequence:03d}", fabrication_sequence=sequence,
                           root=current["root"], directory=str(directory), reserved_utc=now())
        atomic_json(directory / "reservation.json", {k: v for k, v in reservation.items() if k not in ("root", "directory")})
        atomic_json(path, data)
    return reservation


def fail_release(reservation, reason):
    if reservation:
        directory = Path(reservation["directory"])
        if not (directory / "release.json").exists():
            atomic_json(directory / "failed.json", dict(failed_utc=now(), reason=str(reason)))


def file_role(name):
    base = PurePosixPath(name).name.upper()
    known = {"COPPER_TOP.ART": ("copper.top", "TOP"), "COPPER_BOTTOM.ART": ("copper.bottom", "BOTTOM"),
             "MASK_TOP.ART": ("soldermask.top", "TOP"), "MASK_BOTTOM.ART": ("soldermask.bottom", "BOTTOM"),
             "SILK_TOP.ART": ("silkscreen.top", "TOP"), "SILK_BOTTOM.ART": ("silkscreen.bottom", "BOTTOM"),
             "OUTLINE.ART": ("profile", None)}
    if base in known:
        return known[base]
    if base.endswith(".DRL"):
        return "drill.plated_and_nonplated", None
    if base.endswith(".ROU"):
        return ("route.plated" if "PLATED" in base and "NONPLATED" not in base else "route.nonplated"), None
    if name.startswith("parametros/"):
        return "config", None
    if name.startswith("informes/") or base.endswith((".LOG", ".TXT")):
        return "report", None
    return "other", None


def validate_archive(path):
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        if len(members) != len(set(members)) or archive.testzip():
            raise ValueError("El paquete contiene miembros duplicados o dañados.")
        for name in members:
            local(Path(path).parent, name)
        manifest_raw = archive.read("manifest.json")
        manifest = json.loads(manifest_raw)
        if manifest.get("schema") != SCHEMA:
            raise ValueError("Paquete sin contrato de trazabilidad v1.")
        inventory = set()
        for item in manifest["files"]:
            name = item["path"]
            if item.get("name") != name or name in inventory or name == "manifest.json":
                raise ValueError("El inventario del paquete es ambiguo.")
            inventory.add(name)
            raw = archive.read(name)
            if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError("Los archivos no coinciden con el manifiesto.")
        if inventory != set(members) - {"manifest.json"}:
            raise ValueError("Hay archivos ajenos o ausentes en esta liberación.")
        return manifest, hashlib.sha256(manifest_raw).hexdigest()


def seal_release(archive, record, reservation, source_snapshot):
    from package_report import annotate_package
    root = Path(reservation["root"])
    directory = Path(reservation["directory"])
    if (directory / "release.json").exists():
        raise ValueError("La liberación ya está sellada. Genera una nueva.")
    source = Path(source_snapshot).resolve()
    if not source.is_relative_to(root) or source.suffix.lower() != ".brd":
        raise ValueError("No hay una copia de origen válida dentro del proyecto.")
    snapshot = directory / "source.brd"
    with source.open("rb") as original, snapshot.open("xb") as target:
        shutil.copyfileobj(original, target)
    source_hash = digest(snapshot)
    if digest(source) != source_hash:
        raise ValueError("La copia de origen cambió durante el sellado.")
    trace = dict(schema=SCHEMA, project_id=reservation["project_id"], project_name=reservation["project_name"],
                 pcb_revision=reservation["pcb_revision"], fabrication_release_id=reservation["fabrication_release_id"],
                 release_kind="allegro_original", release_label=reservation["release_label"],
                 fabrication_sequence=reservation["fabrication_sequence"],
                 base_fabrication_release_id=reservation["fabrication_release_id"], parent_release_id=None,
                 parent_archive_sha256=None, parent_manifest_sha256=None,
                 source_board_sha256=source_hash,
                 source_board=dict(project_relative_path=snapshot.relative_to(root).as_posix(), sha256=source_hash, bytes=snapshot.stat().st_size),
                 created_utc=now(), tools=[dict(name="allegro_assistant", version=record["assistant_version"]),
                                          dict(name="pcb_utilidades", version=record["checks"].get("core")),
                                          dict(name="Cadence Allegro PCB Editor", version=record["checks"].get("allegro_version"))],
                 profile=dict(requested_rules=record.get("profile", {}), export_policy=record["policy"],
                              exported_config_path="parametros/config_utilidades.il"), provenance_status="verified")
    trace.update(source_saved_board_sha256=record.get("saved_board_sha256_at_submit"),
                 source_saved_board_observed_utc=record.get("saved_board_observed_utc"),
                 source_saved_board_observation="export_requested")
    annotate_package(archive, record, trace=trace)
    manifest, manifest_hash = validate_archive(archive)
    entry = dict(**{k: v for k, v in reservation.items() if k not in ("root", "directory")}, state="sealed", created_utc=manifest["created_utc"],
                 archive_project_path=Path(archive).resolve().relative_to(root).as_posix(),
                 archive_sha256=digest(archive), manifest_sha256=manifest_hash,
                 source_board=manifest["source_board"], saved_board_sha256_at_submit=record.get("saved_board_sha256_at_submit"),
                 release_status=manifest["release_status"])
    with (directory / "release.json").open("x", encoding="utf-8") as stream:
        json.dump(entry, stream, ensure_ascii=False, indent=2)
    return entry


def releases(binding):
    if not binding:
        return []
    found = []
    for path in (Path(binding["project_file"]).parent / "releases").glob("*/release.json"):
        item = json.loads(path.read_text(encoding="utf-8"))
        if item["project_id"] != binding["project_id"]:
            raise ValueError("El índice mezcla identidades de placas.")
        found.append(item)
    return sorted(found, key=lambda item: item["fabrication_sequence"], reverse=True)


def association_status(board, binding):
    history = releases(binding)
    if not history:
        return "Sin liberación trazable; los ZIP anteriores siguen como históricos."
    latest = history[0]
    label = f"{latest['release_label']} · PCB {latest['pcb_revision']}"
    archive = local(binding["root"], latest["archive_project_path"])
    if not archive.exists() or digest(archive) != latest["archive_sha256"]:
        return label + " · paquete ausente o modificado"
    if binding["pcb_revision"] != binding["latest_declared_revision"]:
        return label + " · existe una revisión PCB declarada más nueva: " + binding["latest_declared_revision"]
    if binding["pcb_revision"] != latest["pcb_revision"]:
        return label + " · desfasada: revisión PCB diferente"
    if latest.get("saved_board_sha256_at_submit") != digest(board):
        return label + " · archivo guardado cambiado; repetir revisión"
    return label + " · sin cambios detectados en disco; ediciones en memoria no monitorizadas"


def compare_releases(binding, first, second):
    manifests = []
    for entry in (first, second):
        path = local(binding["root"], entry["archive_project_path"])
        if digest(path) != entry["archive_sha256"]:
            raise ValueError("El ZIP ha cambiado desde su sellado.")
        manifests.append(validate_archive(path)[0])
    before, after = ({item["path"]: item for item in manifest["files"]} for manifest in manifests)
    return dict(first=first["release_label"], second=second["release_label"],
                pcb_revisions=[first["pcb_revision"], second["pcb_revision"]],
                changed=sorted(name for name in before.keys() & after.keys() if before[name]["sha256"] != after[name]["sha256"]),
                added=sorted(after.keys() - before.keys()), removed=sorted(before.keys() - after.keys()))
