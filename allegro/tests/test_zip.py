"""ZIP packaging regression tests using the Windows PowerShell 5.1 runtime."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

HELPER = Path(__file__).resolve().parents[1] / 'pcb_empaquetar.ps1'
POWERSHELL = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
FILMS = ('COPPER_TOP', 'COPPER_BOTTOM', 'MASK_TOP', 'MASK_BOTTOM', 'OUTLINE', 'SILK_TOP', 'SILK_BOTTOM')


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'proyecto con e\u00f1e_fab_v001'
        self.folder.mkdir()
        for film in FILMS:
            (self.folder / f'{film}.art').write_text('%FSLAX55Y55*MOMM*%\nM02*\n', encoding='ascii')
        (self.folder / 'PCB_DRILL-1-2.drl').write_text('M48\nMETRIC,TZ\nT01C.3\n%\nM30\n', encoding='ascii')
        self.info = self.folder / 'pcb_export_info.txt'
        self.info.write_text('tools_version=0.2.0\nartwork_status=1\nncdrill_status=0\n', encoding='ascii')
        (self.folder / 'private.brd').write_text('Do not include this board', encoding='ascii')

    @property
    def archive(self):
        return Path(str(self.folder) + '.zip')

    def run_helper(self):
        return subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned', '-File', str(HELPER),
                               '-Directory', str(self.folder)], capture_output=True, text=True)

    def test_unicode_path_complete_archive_and_warning_manifest(self):
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertIsNone(archive.testzip())
            self.assertNotIn('private.brd', archive.namelist())
            manifest = json.loads(archive.read('manifest.json').decode('utf-8'))
            self.assertEqual(manifest['fabrication_version'], 1)
            self.assertEqual(manifest['status'], 'REQUIERE_REVISION_AVISOS')
            for entry in manifest['files']:
                self.assertEqual(hashlib.sha256(archive.read(entry['name'])).hexdigest(), entry['sha256'])
            self.assertTrue({f'{film}.art' for film in FILMS}.issubset(archive.namelist()))
            self.assertIn('PCB_DRILL-1-2.drl', archive.namelist())

    def test_existing_archive_is_never_overwritten(self):
        self.assertEqual(self.run_helper().returncode, 0)
        before = self.archive.read_bytes()
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertEqual(before, self.archive.read_bytes())
        self.assertFalse(list(self.folder.parent.glob('*.tmp')))

    def test_windows_shell_invocation_with_quoted_paths(self):
        command = (f'cmd.exe /c ""{POWERSHELL}" -NoProfile -NonInteractive '
                   f'-ExecutionPolicy RemoteSigned -File "{HELPER}" -Directory "{self.folder}" '
                   f'> "{self.folder}/pcb_zip.log" 2>&1"')
        result = subprocess.run(command, capture_output=True, text=True)
        log = (self.folder / 'pcb_zip.log').read_text(errors='replace')
        self.assertEqual(result.returncode, 0, log + result.stderr)
        self.assertTrue(self.archive.exists())

    def test_missing_gerber_prevents_packaging(self):
        (self.folder / 'OUTLINE.art').unlink()
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertFalse(self.archive.exists())

    def test_export_error_prevents_packaging(self):
        self.info.write_text('tools_version=0.2.0\nartwork_status=2\nncdrill_status=0\n', encoding='ascii')
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertFalse(self.archive.exists())

    def test_truncated_gerber_prevents_packaging(self):
        (self.folder / 'COPPER_TOP.art').write_text('%FSLAX55Y55*MOMM*%\n', encoding='ascii')
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertFalse(self.archive.exists())

    def test_expected_slots_missing_prevents_packaging(self):
        self.info.write_text('tools_version=0.3.0\nartwork_status=0\nncdrill_status=0\n'
                             'expected_plated_slots=15\nexpected_nonplated_slots=0\n', encoding='ascii')
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Incomplete NC slots', result.stderr)
        self.assertFalse(self.archive.exists())

    def test_complete_slots_count_is_recorded(self):
        self.info.write_text('tools_version=0.3.0\nartwork_status=0\nncdrill_status=0\nncroute_status=0\n'
                             'expected_plated_slots=2\nexpected_nonplated_slots=0\n', encoding='ascii')
        route = ('M48\nMETRIC,TZ\nT01C1.1\n%\nG90\nT01\n'
                 'G00X100Y100\nM15\nG01X200Y100\nM16\n'
                 'G00X300Y100\nM15\nG01X400Y100\nM16\nM30\n')
        (self.folder / 'PCB_SLOTS_plated.rou').write_text(route, encoding='ascii')
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.archive) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['slots'], {'expected_plated': 2, 'expected_nonplated': 0,
                                                'routed_plated': 2, 'routed_nonplated': 0})
            self.assertIn('PCB_SLOTS_plated.rou', archive.namelist())

    def test_logged_warning_is_not_hidden_by_zero_process_status(self):
        self.info.write_text('tools_version=0.3.0\nartwork_status=0\nncdrill_status=0\n', encoding='ascii')
        (self.folder / 'ncdrill.log').write_text('WARNING: generated tools automatically\n', encoding='ascii')
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(json.loads(archive.read('manifest.json'))['status'], 'REQUIERE_REVISION_AVISOS')

    def test_separate_routing_is_not_silently_dropped(self):
        (self.folder / 'PCB_DRILL.rou').write_text('routing', encoding='ascii')
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertFalse(self.archive.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
