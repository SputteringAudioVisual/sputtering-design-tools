import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from saved_board import check_tables
from transport import Mailbox, parse_fields, skill_string
from workflow import Profile, Workflow, board_key


def good_state(board):
    return dict(board=board, status="ok", fresh_drc="0", unplaced="0", drc="0", shapes="0",
                mask_pins="0", mask_vias="0", mask_extras="0", mask_conflicts="0", missing="0")


class Gates(unittest.TestCase):
    def test_zero_drc_does_not_prove_connections(self):
        flow = Workflow("C:/PSU/input.brd")
        flow.accept("review", good_state(flow.board))
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
        flow.placement_confirmed = flow.connections_confirmed = flow.cam_confirmed = True
        self.assertEqual([], flow.export_blockers())
        flow.accept("widths", good_state(flow.board))
        self.assertTrue(flow.export_blockers())
        self.assertFalse(flow.connections_confirmed)
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
        flow.placement_confirmed = flow.connections_confirmed = flow.cam_confirmed = True
        self.assertTrue(any("copia guardada" in reason for reason in flow.export_blockers()))


class Protocol(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.box = Mailbox(self.temp.name, str(Path(self.temp.name) / "diseño.brd"), "abc")
        self.heartbeat()

    def tearDown(self):
        self.temp.cleanup()

    def heartbeat(self, board=None, token="abc"):
        (self.box.root / "heartbeat.tsv").write_text(f"token\t{token}\nboard\t{board or self.box.board}\n", encoding="cp1252")

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
        self.assertEqual(len(request), 9)
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


if __name__ == "__main__":
    unittest.main()
