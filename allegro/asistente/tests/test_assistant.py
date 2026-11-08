import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from saved_board import check_tables
from transport import Mailbox, parse_fields, skill_string
from workflow import ExportPolicy, Profile, Workflow, board_key
from package_report import annotate_package, latest_export, remember_export
import hashlib
import zipfile


def good_state(board):
    return dict(board=board, status="ok", fresh_drc="0", unplaced="0", drc="0", shapes="0",
                mask_pins="0", mask_vias="0", mask_extras="0", mask_conflicts="0", missing="0", unrouted="0", unplaced_pins="0")


class Gates(unittest.TestCase):
    def test_zero_drc_does_not_prove_connections(self):
        flow = Workflow("C:/PSU/input.brd")
        state = good_state(flow.board)
        state["unrouted"] = "3"
        state["unrouted_nets"] = ["GND: 3"]
        flow.accept("review", state)
        flow.persisted = {"ok": True}
        flow.placement_confirmed = flow.cam_confirmed = True
        self.assertTrue(any("sin rutear" in reason for reason in flow.export_blockers()))

    def test_registered_drc_not_sufficient(self):
        flow = Workflow("C:/PSU/input.brd")
        flow.accept("inspect", good_state(flow.board))
        self.assertFalse(flow.reviewed)

    def test_complete_gate_and_mutation_invalidation(self):
        flow = Workflow("C:/PSU/input.brd")
        flow.accept("review", good_state(flow.board))
        flow.accept("snapshot", good_state(flow.board))
        flow.persisted = {"ok": True}
        flow.placement_confirmed = flow.cam_confirmed = True
        self.assertEqual([], flow.export_blockers())
        flow.accept("widths", good_state(flow.board))
        self.assertTrue(flow.export_blockers())
        self.assertFalse(flow.reviewed)

    def test_wrong_board_and_unknown_metrics(self):
        flow = Workflow("C:/PSU/input.brd")
        with self.assertRaises(ValueError):
            flow.accept("inspect", good_state("C:/Other/input.brd"))
        flow.accept("review", {"board": flow.board, "status": "ok"})
        self.assertGreater(len(flow.export_blockers()), 8)

    def test_persisted_missing_blocks_export(self):
        flow = Workflow("C:/PSU/input.brd")
        flow.accept("review", good_state(flow.board))
        flow.persisted = {"ok": False, "missing": ["J1"]}
        flow.placement_confirmed = flow.cam_confirmed = True
        self.assertTrue(any("copia guardada" in reason for reason in flow.export_blockers()))

    def test_intentionally_hidden_connector_references_are_optional(self):
        flow = Workflow("C:/PSU/input.brd")
        state = good_state(flow.board)
        state.update(missing="5", missing_refs=["J1", "J2", "J3", "J4", "GND_+12V_RC1"])
        flow.accept("review", state)
        flow.persisted = dict(checked=True, ok=False, missing=state["missing_refs"], duplicates=[])
        flow.placement_confirmed = flow.cam_confirmed = True
        flow.policy = ExportPolicy(excluded_refs=state["missing_refs"].copy()).validate()
        self.assertEqual([], flow.export_blockers())
        flow.policy.excluded_refs.remove("J1")
        finding = next(item for item in flow.findings() if item.code == "missing")
        self.assertEqual("J1", finding.detail)
        self.assertEqual("1", finding.value)

    def test_skipping_texts_does_not_skip_other_checks(self):
        flow = Workflow("C:/PSU/input.brd", policy=ExportPolicy(check_texts=False))
        state = good_state(flow.board)
        state.update(missing="5", drc="2", fresh_drc="2")
        flow.accept("review", state)
        flow.placement_confirmed = flow.cam_confirmed = True
        self.assertEqual(["drc"], [item.code for item in flow.findings()])
        flow.accept_finding("drc", "Dos avisos revisados en la placa")
        self.assertEqual([], flow.export_blockers())
        self.assertEqual(["drc:2"], flow.waiver_tokens())
        state["drc"] = "3"
        self.assertTrue(flow.export_blockers())

    def test_acceptance_requires_reason_and_is_cleared_on_review(self):
        flow = Workflow("C:/PSU/input.brd", policy=ExportPolicy(check_texts=False))
        state = good_state(flow.board)
        state.update(mask_vias="1")
        flow.accept("review", state)
        with self.assertRaises(ValueError):
            flow.accept_finding("mask_vias", " ")
        with self.assertRaises(ValueError):
            flow.accept_finding("placement", "Lo sé")
        flow.accept_finding("mask_vias", "Vía de prueba que quiero dejar abierta")
        self.assertIn("mask_vias:1", flow.waiver_tokens())
        flow.accept("review", state)
        self.assertFalse(flow.waivers)

    def test_unknown_counts_and_outdated_shapes_are_not_waivable(self):
        flow = Workflow("C:/PSU/input.brd")
        state = good_state(flow.board)
        state.update(drc="nil", shapes="1")
        flow.accept("inspect", state)
        for code in ("drc", "shapes"):
            with self.assertRaises(ValueError):
                flow.accept_finding(code, "Acepto")


class Protocol(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.box = Mailbox(self.temp.name, str(Path(self.temp.name) / "diseño.brd"), "abc")
        self.heartbeat()

    def tearDown(self):
        self.temp.cleanup()

    def heartbeat(self, board=None, token="abc"):
        (self.box.root / "heartbeat.tsv").write_text(f"token\t{token}\nboard\t{board or self.box.board}\nprotocol\t4\n", encoding="cp1252")

    def test_wrong_board_stale_or_changed_session_refused(self):
        self.heartbeat(board="C:/other.brd")
        with self.assertRaises(ValueError):
            self.box.submit("mask", Profile())
        self.heartbeat(token="def")
        self.assertFalse(self.box.connection()[0])
        self.heartbeat()
        self.assertFalse(self.box.connection(max_age=-1)[0])

    def test_unicode_path_atomic_request_and_no_replay(self):
        job = self.box.submit("mask", Profile())
        request = (self.box.root / "request.tsv").read_text(encoding="cp1252").splitlines()
        self.assertEqual(len(request), 12)
        self.assertIn("ñ", request[4])
        self.assertFalse((self.box.root / "request.tmp").exists())
        with self.assertRaises(ValueError):
            self.box.submit("mask", Profile())
        result = self.box.root / f"{job}.result.tsv"
        result.write_text(f"id\t{job}\ntoken\tabc\naction\tmask\nboard\t{self.box.board}\nstatus\tok\n", encoding="cp1252")
        self.assertIsNone(self.box.poll())
        with result.open("a", encoding="cp1252") as stream:
            stream.write("complete\t1\n")
        self.assertEqual("mask", self.box.poll()[0])
        self.assertIsNone(self.box.poll())

    def test_arbitrary_code_and_controls_not_allowed(self):
        with self.assertRaises(ValueError):
            self.box.submit('system("bad")', Profile())
        with self.assertRaises(ValueError):
            self.box.submit("inspect", Profile(["0\nmalicious"]))
        with self.assertRaises(ValueError):
            skill_string("C:/file\nload")

    def test_nan_inf_and_wrong_result_rejected(self):
        for value in (float("nan"), float("inf"), -1):
            with self.assertRaises(ValueError):
                Profile(signal_mm=value).validate()
        job = self.box.submit("mask", Profile())
        (self.box.root / f"{job}.result.tsv").write_text(
            f"id\t{job}\ntoken\tabc\naction\tmask\nboard\tC:/other.brd\nstatus\tok\ncomplete\t1\n", encoding="cp1252")
        with self.assertRaises(ValueError):
            self.box.poll()
        self.assertIsNotNone(self.box.pending)

    def test_policy_and_exact_waivers_are_transmitted_as_data(self):
        self.box.submit("export", Profile(), "ticket", ExportPolicy(False, ["J1"]), ["drc:2"])
        request = (self.box.root / "request.tsv").read_text(encoding="cp1252").splitlines()
        self.assertEqual(["0", "J1", "drc:2"], request[-3:])

    def test_zero_unrouted_needs_no_manual_connection_checkbox(self):
        flow = Workflow("C:/PSU/input.brd", policy=ExportPolicy(False))
        flow.accept("review", good_state(flow.board))
        flow.placement_confirmed = flow.cam_confirmed = True
        self.assertEqual([], flow.export_blockers())
        flow.state["unrouted"] = "nil"
        self.assertTrue(any(item.code == "unrouted" and not item.waivable for item in flow.findings()))

    def test_known_unrouted_count_can_be_accepted_without_being_called_zero(self):
        flow = Workflow("C:/PSU/input.brd", policy=ExportPolicy(False))
        state = good_state(flow.board)
        state["unrouted"] = "2"
        flow.accept("review", state)
        flow.placement_confirmed = flow.cam_confirmed = True
        flow.accept_finding("unrouted", "Conector de prueba deliberadamente desconectado")
        self.assertEqual([], flow.export_blockers())
        self.assertIn("unrouted:2", flow.waiver_tokens())
        self.assertEqual("2", flow.export_record()["checks"]["unrouted"])


class PersistedReferences(unittest.TestCase):
    components = "A!REFDES!SYM_X!SYM_Y!\nS!R1!1!2!\nS!J1!3!4!\n"
    header = "A!CLASS!SUBCLASS!REFDES!GRAPHIC_DATA_NAME!GRAPHIC_DATA_7!\n"
    resistor = "S!REF DES!SILKSCREEN_TOP!R1!TEXT!R1!\n"
    connector = "S!REF DES!SILKSCREEN_TOP!J1!TEXT!J1!\n"

    def test_missing_duplicate_wrong_layer_and_good_case(self):
        result = check_tables(self.components, self.header + self.resistor)
        self.assertEqual(["J1"], result["missing"])
        self.assertFalse(result["ok"])
        self.assertTrue(check_tables(self.components, self.header + self.resistor + self.connector)["ok"])
        self.assertFalse(check_tables(self.components, self.header + self.resistor * 2 + self.connector)["ok"])
        self.assertFalse(check_tables(self.components, self.header + self.resistor + self.connector.replace("SILKSCREEN", "ASSEMBLY"))["ok"])

    def test_no_components_or_malformed_output_fails_closed(self):
        self.assertFalse(check_tables("A!REFDES!SYM_X!SYM_Y!\n", self.header)["ok"])
        with self.assertRaises(ValueError):
            check_tables("unexpected", self.header)


class PackageReview(unittest.TestCase):
    def test_latest_export_is_project_bound_and_recovers_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            board = root / "PSU.brd"
            folder = root / "Fabricacion"
            folder.mkdir()
            archive = folder / "PSU_fab_v001.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("manifest.json", "{}")
            (folder / "other_fab_v999.zip").write_bytes(b"other")
            self.assertEqual(archive, latest_export(board))
            remember_export(board, archive)
            self.assertEqual(archive, latest_export(board))
            with self.assertRaises(ValueError):
                remember_export(board, folder / "other_fab_v999.zip")

    def test_report_manifest_hashes_and_original_payload_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "fabricacion_v001"
            folder.mkdir()
            archive = root / "fabricacion_v001.zip"
            copper = b"gerber-data"
            manifest = dict(status="EXPORTADO_SIN_AVISOS", files=[dict(name="TOP.art", bytes=len(copper), sha256=hashlib.sha256(copper).hexdigest())])
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("TOP.art", copper)
                stream.writestr("manifest.json", json.dumps(manifest))
                stream.writestr("LEEME_FABRICACION.txt", "Estado: EXPORTADO_SIN_AVISOS\n")
            flow = Workflow(str(root / "input.brd"), policy=ExportPolicy(False))
            annotate_package(archive, flow.export_record())
            with zipfile.ZipFile(archive) as stream:
                self.assertIsNone(stream.testzip())
                self.assertEqual(copper, stream.read("TOP.art"))
                result = json.loads(stream.read("manifest.json"))
                self.assertEqual("EXPORTADO_CON_EXCEPCIONES_USUARIO", result["status"])
                self.assertEqual("EXPORTADO_SIN_AVISOS", result["generator_status"])
                self.assertIn("Estado: EXPORTADO_CON_EXCEPCIONES_USUARIO", stream.read("LEEME_FABRICACION.txt").decode())
                self.assertEqual(3, len(result["files"]))
                for item in result["files"]:
                    self.assertEqual(item["sha256"], hashlib.sha256(stream.read(item["name"])).hexdigest())


if __name__ == "__main__":
    unittest.main()
