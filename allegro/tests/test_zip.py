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


if __name__ == '__main__':
    unittest.main(verbosity=2)
