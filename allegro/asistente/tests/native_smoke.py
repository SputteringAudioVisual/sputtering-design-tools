"""Opt-in integration test. Opens a disposable board copy in real Allegro.

Never point --source at a file being edited. The original is hashed and copied;
all native operations and reports run on that copy. No fabrication export.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from saved_board import verify_snapshot
from transport import Mailbox
from workflow import Profile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--exercise-ui", action="store_true", help="Also test Tk button callbacks and create a TEST-ONLY ZIP on the disposable board")
    parser.add_argument("--exclude-refs", default="")
    parser.add_argument("--min-unrouted", type=int, default=0)
    parser.add_argument("--expect-unrouted", type=int)
    parser.add_argument("--hide-rats", action="store_true")
    args = parser.parse_args()
    root = args.scratch.resolve()
    str(root).encode("ascii")
    if root.exists():
        raise ValueError("Use a new scratch directory, never an existing project folder.")
    root.mkdir(parents=True)
    original = hashlib.sha256(args.source.read_bytes()).hexdigest()
    shutil.copyfile(args.source, root / "input.brd")
    shutil.copyfile(Path(__file__).resolve().parents[1] / "bridge" / "pcb_assistant_bridge.il", root / "bridge.il")
    box = Mailbox(root / "session", root / "input.brd")
    script = box.bootstrap(root / "bridge.il", "C:/SPB_Data/pcbenv/pcb_tools")
    if args.hide_rats:
        with script.open("a", encoding="cp1252") as stream:
            stream.write("skill foreach(net axlDBGetDesign()->nets axlRatsnestBlank(net))\n")
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    process = subprocess.Popen(["C:/Cadence/SPB_17.2/tools/bin/allegro.exe", "-s", str(script), str(root / "input.brd")],
                               cwd=root, startupinfo=startup, stdout=(root / "stdout.log").open("wb"),
                               stderr=(root / "stderr.log").open("wb"))
    print(json.dumps({"pid": process.pid, "scratch": str(root)}), flush=True)
    report = {"original_sha256": original, "pid": process.pid, "actions": {}}
    try:
        deadline = time.monotonic() + 300
        while not box.connection()[0]:
            if time.monotonic() > deadline or process.poll() is not None:
                raise TimeoutError("Automatic Allegro connection did not become ready")
            time.sleep(1)
        first = (box.root / "heartbeat.tsv").stat().st_mtime_ns
        time.sleep(3)
        assert (box.root / "heartbeat.tsv").stat().st_mtime_ns != first, "GUI timer did not fire"
        print("Live Allegro timer: OK", flush=True)
        for action in ("inspect", "review", "snapshot"):
            box.submit(action, Profile())
            deadline = time.monotonic() + 180
            received = None
            while not received:
                received = box.poll()
                if time.monotonic() > deadline:
                    raise TimeoutError(f"No response to {action}; NOT retried")
                time.sleep(0.5)
            _, result = received
            report["actions"][action] = result
            assert result["status"] == "ok", result
            assert int(result["unrouted"]) >= args.min_unrouted, result
            if args.expect_unrouted is not None:
                assert int(result["unrouted"]) == args.expect_unrouted, result
            print(f"Automatic dispatch {action}: OK", flush=True)
        snapshot = report["actions"]["snapshot"]["snapshot"]
        report["persisted"] = verify_snapshot(snapshot, "C:/Cadence/SPB_17.2/tools/bin/extracta.exe", root / "scratch")
        if args.exercise_ui:
            from app import Assistant
            from traceability import bind_board
            import zipfile
            window = Assistant(board=str(root / "input.brd"))
            window.withdraw()
            bind_board(root / "input.brd", "PLACA SINTETICA DE PRUEBA", "1.0", note="Declaración explícita de fixture, no de una PCB histórica")
            window.refresh_identity()
            window.mailbox = box
            window.placement_var.set(True)
            window.excluded_var.set(args.exclude_refs)
            window.update_policy()
            try:
                # These are the real button callbacks, driven by Tk's event loop.
                # This is a software integration test, not desktop input injection.
                for index in range(6):
                    window.show_step(index)
                    window.update_idletasks()
                    assert window.content.winfo_width() > 200
                window.prepare_export()
                deadline = time.monotonic() + 240
                while window.finalizing or window.task or box.pending:
                    window.update()
                    if time.monotonic() > deadline:
                        raise TimeoutError("UI review/copy verification did not finish")
                    time.sleep(0.05)
                assert window.flow.reviewed and window.flow.persisted.get("checked"), window.flow
                # The fixture can be intentionally unrouted. This confirms only
                # the export integration, never approval for manufacturing.
                assert window.flow.export_blockers(), "Export must still require manual confirmations"
                if int(window.flow.state["unrouted"]) > 0:
                    window.flow.accept_finding("unrouted", "Copia de prueba de software, NO aprobada para fabricar")
                window.cam_var.set(True)
                window.export()
                assert box.pending, "Export callback did not send a request"
                deadline = time.monotonic() + 240
                while box.pending:
                    window.update()
                    if time.monotonic() > deadline:
                        raise TimeoutError("UI export did not finish; not retried")
                    time.sleep(0.05)
                state = window.flow.state
                assert state["status"] == "ok" and state.get("zip"), state
                assert state["source_films"] == "7", state
                assert window.last_zip and window.last_zip.is_file()
                assert str(window.last_zip) == window.export_path_var.get()
                assert str(window.export_folder_button["state"]) == "normal"
                with zipfile.ZipFile(state["zip"]) as archive:
                    assert archive.testzip() is None
                    names = archive.namelist()
                    assert len([name for name in names if name.lower().endswith(".art")]) == 7, names
                    assert any(name.lower().endswith(".drl") for name in names), names
                    assert "informes/ASISTENTE_REVISION.json" in names, names
                report["ui_callbacks"] = "review -> snapshot -> extracta -> export: OK"
                report["test_only_zip"] = state["zip"]
                if report["persisted"]["missing"]:
                    # Same absent texts, now accepted as a concrete warning
                    # instead of permanently excluding individual RefDes.
                    window.excluded_var.set("")
                    window.update_policy()
                    window.prepare_export()
                    deadline = time.monotonic() + 240
                    while window.finalizing or window.task or box.pending:
                        window.update()
                        if time.monotonic() > deadline:
                            raise TimeoutError("Second UI review did not finish")
                        time.sleep(0.05)
                    window.flow.accept_finding("missing", "Referencias intencionadamente ausentes en la copia de prueba")
                    window.placement_var.set(True)
                    if int(window.flow.state["unrouted"]) > 0:
                        window.flow.accept_finding("unrouted", "Copia de prueba de software, NO aprobada para fabricar")
                    window.cam_var.set(True)
                    window.export()
                    assert box.pending, window.flow.export_blockers()
                    deadline = time.monotonic() + 240
                    while box.pending:
                        window.update()
                        if time.monotonic() > deadline:
                            raise TimeoutError("Accepted-warning export did not finish")
                        time.sleep(0.05)
                    assert window.flow.state["status"] == "ok", window.flow.state
                    with zipfile.ZipFile(window.flow.state["zip"]) as archive:
                        record = json.loads(archive.read("informes/ASISTENTE_REVISION.json"))
                        assert record["accepted"][0]["code"] == "missing", record
                        assert json.loads(archive.read("manifest.json"))["status"] == "EXPORTADO_CON_EXCEPCIONES_USUARIO"
                    report["accepted_warning_zip"] = window.flow.state["zip"]
                (root / "NO_FABRICAR_PRUEBA.txt").write_text("Paquete de prueba de software. La conectividad de esta copia NO esta aprobada para fabricacion.\n", encoding="utf-8")
                print("Tk callbacks and TEST-ONLY versioned ZIP: OK", flush=True)
            finally:
                window.destroy()
        report["ok"] = True
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
        raise
    finally:
        # This process was created above for this test on a disposable copy.
        # Never enumerate/kill user-owned Allegro processes.
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
        report["original_unchanged"] = hashlib.sha256(args.source.read_bytes()).hexdigest() == original
        (root / "result.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"ok": report.get("ok"), "original_unchanged": report["original_unchanged"]}), flush=True)


if __name__ == "__main__":
    main()
