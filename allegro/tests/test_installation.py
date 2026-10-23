"""Check central installation, migration and preservation of user startup code."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

INSTALLER = Path(__file__).resolve().parents[1] / 'Instalar-PcbTools.ps1'
POWERSHELL = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'


class InstallationTests(unittest.TestCase):
    def test_legacy_entrypoints_and_unrelated_startup_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / 'pcbenv'
            root = profile / 'pcb_tools'
            legacy = Path(temp) / 'old_tools'
            root.mkdir(parents=True)
            legacy.mkdir()
            (root / 'pcb_local.il').write_text('pcbMaskMarginMM = 0.05\n', encoding='ascii')
            init = profile / 'allegro.ilinit'
            init.write_bytes(b'; conservar: \xf1\r\nload("C:/otro/mi_codigo.il")\r\nload("C:/old/fx_mascara.il")\r\n')
            old = legacy / 'fx_mascara.il'
            original = b'; historical implementation\r\n'
            old.write_bytes(original)
            result = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                                     'RemoteSigned', '-File', str(INSTALLER), '-InstallRoot', str(root),
                                     '-LegacyDirectories', str(legacy)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(b'\xf1', init.read_bytes())
            self.assertIn(b'C:/otro/mi_codigo.il', init.read_bytes())
            self.assertNotIn(b'C:/old/fx_mascara.il', init.read_bytes())
            self.assertIn(b'pcb_cargar.il', init.read_bytes())
            self.assertIn('pcb_cargar.il', old.read_text())
            self.assertNotIn('historical implementation', old.read_text())
            self.assertEqual((root / 'pcb_local.il').read_text(), 'pcbMaskMarginMM = 0.05\n')
            backups = list((profile / 'pcb_tools_backups').glob('*/restauracion.json'))
            self.assertEqual(len(backups), 1)
            records = json.loads(backups[0].read_text(encoding='utf-8-sig'))
            record = next(r for r in records if Path(r['original']) == old)
            self.assertEqual(Path(record['backup']).read_bytes(), original)
            self.assertTrue((root / 'pcb_empaquetar.ps1').is_file())


if __name__ == '__main__':
    unittest.main(verbosity=2)
