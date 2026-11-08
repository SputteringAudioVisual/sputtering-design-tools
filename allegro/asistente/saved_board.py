"""Independent check of persisted RefDes, using Cadence extracta read-only."""
from collections import Counter
from pathlib import Path
import hashlib
import shutil
import subprocess
import tempfile

GEOMETRY = "FULL_GEOMETRY\nCLASS\nSUBCLASS\nREFDES\nGRAPHIC_DATA_NAME\nGRAPHIC_DATA_7\nEND\n"
COMPONENTS = "COMPONENT\nREFDES\nSYM_X\nSYM_Y\nEND\n"


def rows(text):
    lines = text.splitlines()
    header = next((line.split("!")[1:-1] for line in lines if line.startswith("A!")), None)
    if not header:
        raise ValueError("Cadence no devolvió una tabla válida.")
    return [dict(zip(header, line.split("!")[1:-1])) for line in lines if line.startswith("S!")]


def check_tables(component_text, geometry_text):
    components, geometry = rows(component_text), rows(geometry_text)
    expected = {item["REFDES"] for item in components if item.get("SYM_X", "") and item.get("SYM_Y", "")}
    refs = Counter(item["REFDES"] for item in geometry if item.get("CLASS") == "REF DES"
                   and item.get("SUBCLASS", "").startswith("SILKSCREEN")
                   and item.get("GRAPHIC_DATA_NAME") == "TEXT"
                   and item.get("GRAPHIC_DATA_7") == item.get("REFDES"))
    missing = sorted(expected - refs.keys())
    duplicates = sorted(ref for ref in expected if refs[ref] > 1)
    return {"ok": bool(expected) and not missing and not duplicates, "checked": bool(expected),
            "components": len(expected), "missing": missing, "duplicates": duplicates}


def verify_snapshot(board, extracta, scratch_root):
    board = Path(board)
    digest = hashlib.sha256(board.read_bytes()).hexdigest()
    # Allegro 17.2 CLI has trouble with Unicode paths. Work on an ASCII copy.
    Path(scratch_root).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="refs_", dir=scratch_root) as folder:
        scratch = Path(folder)
        shutil.copyfile(board, scratch / "input.brd")
        tables = []
        for name, query in (("components", COMPONENTS), ("geometry", GEOMETRY)):
            query_path = scratch / (name + ".query")
            query_path.write_text(query, encoding="ascii")
            run = subprocess.run([str(extracta), "-q", "-w", "-l", str(scratch / (name + ".log")),
                                  str(scratch / "input.brd"), str(query_path)], cwd=scratch,
                                 capture_output=True, timeout=90,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if run.returncode:
                raise RuntimeError("No se pudo comprobar la copia guardada con Cadence.")
            tables.append(run.stdout.decode("cp1252", errors="replace"))
        result = check_tables(*tables)
    if hashlib.sha256(board.read_bytes()).hexdigest() != digest:
        raise ValueError("La copia ha cambiado durante la comprobación.")
    result.update(snapshot=str(board), sha256=digest)
    return result
