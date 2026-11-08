import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package_report import annotate_package, latest_export
from traceability import (SCHEMA, association_status, bind_board, compare_releases, digest, fail_release,
                          load_binding, releases, reserve_release, seal_release, validate_archive)
from workflow import Workflow


class Traceability(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "Proyecto"
        self.board = self.root / "allegro" / "PSU_V1_3.brd"
        self.board.parent.mkdir(parents=True)
        self.board.write_bytes(b"saved native board fixture")
        self.snapshot = self.board.parent / "current_snapshot.brd"
        self.snapshot.write_bytes(b"different in-memory board fixture")
        self.binding = bind_board(self.board, "PSU de prueba", "1.3", note="Declarado por el test")

    def tearDown(self):
        self.temp.cleanup()

    def raw(self, version=1, copper=b"gerber fixture"):
        folder = self.board.parent / "Fabricacion" / f"{self.board.stem}_fab_v{version:03d}"
        folder.mkdir(parents=True)
        archive = folder.with_suffix(".zip")
        manifest = dict(board=self.board.stem, fabrication_version=version, status="EXPORTADO_SIN_AVISOS", files=[])
        with zipfile.ZipFile(archive, "w") as stream:
            for name, content in {"COPPER_TOP.art": copper, "PCB_DRILL.drl": b"drill fixture"}.items():
                stream.writestr(name, content)
                manifest["files"].append(dict(name=name, bytes=len(content), sha256=hashlib.sha256(content).hexdigest()))
            stream.writestr("LEEME_FABRICACION.txt", "Estado: EXPORTADO_SIN_AVISOS\n")
            stream.writestr("manifest.json", json.dumps(manifest))
        return archive

    def record(self):
        flow = Workflow(str(self.board))
        flow.state = dict(core="0.3.0", allegro_version="17.2 P028", board=str(self.board))
        record = flow.export_record()
        record.update(profile=dict(power_mm=.8), saved_board_sha256_at_submit=digest(self.board),
                      saved_board_observed_utc="2026-11-08T00:00:00+00:00")
        return record

    def commit(self, version=1, copper=b"gerber fixture"):
        archive = self.raw(version, copper)
        reservation = reserve_release(self.board, self.binding)
        entry = seal_release(archive, self.record(), reservation, self.snapshot)
        return archive, entry

    def test_explicit_identity_does_not_invent_historical_metadata(self):
        old = self.raw()
        before = digest(old)
        bind_board(self.board, "Nuevo nombre legible", "2.0", self.binding["project_id"], "Cambio eléctrico declarado")
        self.assertEqual(before, digest(old))
        with zipfile.ZipFile(old) as archive:
            self.assertNotIn("project_id", json.loads(archive.read("manifest.json")))
        self.assertEqual([], releases(self.binding))

    def test_renamed_board_is_linked_explicitly_to_same_identity(self):
        archive, _ = self.commit()
        renamed = self.board.with_name("otro_nombre.brd")
        shutil.copyfile(self.board, renamed)
        self.assertIsNone(load_binding(renamed))
        linked = bind_board(renamed, "PSU de prueba", "1.3", self.binding["project_id"])
        self.assertEqual(self.binding["project_id"], linked["project_id"])
        self.assertEqual(archive, latest_export(renamed))

    def test_release_records_exact_memory_source_and_complete_inventory(self):
        archive, entry = self.commit()
        manifest, manifest_hash = validate_archive(archive)
        self.assertEqual(SCHEMA, manifest["schema"])
        self.assertEqual(self.binding["project_id"], manifest["project_id"])
        self.assertEqual("1.3", manifest["pcb_revision"])
        self.assertEqual(entry["fabrication_release_id"], manifest["base_fabrication_release_id"])
        self.assertEqual(digest(self.snapshot), manifest["source_board_sha256"])
        self.assertNotEqual(digest(self.board), manifest["source_board_sha256"])
        self.assertEqual(digest(self.board), manifest["source_saved_board_sha256"])
        self.assertEqual(manifest_hash, entry["manifest_sha256"])
        self.assertEqual(digest(archive), entry["archive_sha256"])
        self.assertIn("LEEME_FABRICACION.txt", {item["path"] for item in manifest["files"]})
        self.assertTrue(all(item["path"] == item["name"] for item in manifest["files"]))
        self.assertEqual("copper.top", next(item for item in manifest["files"] if item["path"] == "COPPER_TOP.art")["role"])

    def test_sealed_package_cannot_be_reannotated(self):
        archive, _ = self.commit()
        before = digest(archive)
        with self.assertRaises(ValueError):
            annotate_package(archive, self.record())
        self.assertEqual(before, digest(archive))

    def test_reexports_have_different_ids_but_same_pcb_revision(self):
        _, first = self.commit()
        _, second = self.commit(2)
        self.assertNotEqual(first["fabrication_release_id"], second["fabrication_release_id"])
        self.assertEqual(["F001", "F002"], [first["release_label"], second["release_label"]])
        self.assertEqual("1.3", second["pcb_revision"])
        self.assertEqual(2, len(releases(self.binding)))

    def test_compare_and_changed_saved_file_status(self):
        _, first = self.commit()
        _, second = self.commit(2, b"different copper fixture")
        report = compare_releases(self.binding, first, second)
        self.assertIn("COPPER_TOP.art", report["changed"])
        self.assertIn("sin cambios detectados en disco", association_status(self.board, self.binding))
        self.board.write_bytes(b"changed saved board")
        self.assertIn("archivo guardado cambiado", association_status(self.board, self.binding))
        self.binding = bind_board(self.board, "PSU de prueba", "2.0", self.binding["project_id"])
        self.assertIn("revisión PCB diferente", association_status(self.board, self.binding))

    def test_relocation_keeps_all_identity_and_source_links_portable(self):
        archive, entry = self.commit()
        moved = Path(self.temp.name) / "moved"
        shutil.copytree(self.root, moved)
        board = moved / self.board.relative_to(self.root)
        binding = load_binding(board)
        self.assertEqual(self.binding["project_id"], binding["project_id"])
        linked = releases(binding)[0]
        self.assertTrue((moved / linked["source_board"]["project_relative_path"]).is_file())
        self.assertEqual(moved / archive.relative_to(self.root), latest_export(board))
        stored = (Path(binding["project_file"]).parent / "releases" / entry["fabrication_release_id"] / "release.json").read_text(encoding="utf-8")
        self.assertNotIn(str(self.root).replace("\\", "\\\\"), stored)

    def test_failed_reservation_does_not_reuse_a_release_label(self):
        pending = reserve_release(self.board, self.binding)
        fail_release(pending, "Software test failure")
        _, entry = self.commit()
        self.assertEqual("F002", entry["release_label"])
        self.assertEqual(1, len(releases(self.binding)))

    def test_changed_sealed_bytes_are_detected(self):
        archive, _ = self.commit()
        with archive.open("ab") as stream:
            stream.write(b"changed")
        self.assertIn("modificado", association_status(self.board, self.binding))


if __name__ == "__main__":
    unittest.main()
