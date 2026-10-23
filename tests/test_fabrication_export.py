from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fabrication_export import FabricationExport


def create_source(folder, files):
    source = Path(folder)/'board.rev_fab_v003.zip'
    manifest = {'board': 'board', 'fabrication_version': 3,
                'status': 'REQUIERE_REVISION_AVISOS',
                'files': [{'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in files.items()]}
    with zipfile.ZipFile(source, 'w') as archive:
        for name, data in files.items(): archive.writestr(name, data)
        archive.writestr('manifest.json', json.dumps(manifest))
    return source


class PackageTests(unittest.TestCase):
    def test_full_package_preserves_untouched_bytes_and_source_and_numbers_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            originals = {'SILK_TOP.art': b'G04 Old*\r\nM02*\r\n', 'COPPER_TOP.art': b'copper\r\n',
                         'MASK_TOP.art': b'mask', 'PCB.drl': b'drill\r\n',
                         'parametros/nc_param.txt': b'INTEGER-PLACES 5\nDECIMAL-PLACES 5\n',
                         'LEEME_FABRICACION.txt': b'Original notes', 'informes/log.txt': b'original log'}
            source = create_source(root, originals)
            source_before = source.read_bytes()
            for revision in (1, 2):
                with FabricationExport(root/'output', {'SILK_TOP.art': b'G04 Old*\nM02*\n'}, source) as package:
                    package.path_for('SILK_TOP.art').write_bytes(b'G04 Modified*\nM02*\n')
                    folder, output = package.finish([{'file': 'SILK_TOP.art', 'mode': 'merge'}], {'threshold': 128})
                self.assertEqual(output.name, f'board.rev_fab_v003_edit_v{revision:03d}.zip')
                self.assertTrue(folder.is_dir())
                with zipfile.ZipFile(output) as archive:
                    for name, data in originals.items():
                        if name not in {'SILK_TOP.art', 'LEEME_FABRICACION.txt'}:
                            self.assertEqual(archive.read(name), data)
                    self.assertEqual(archive.read('SILK_TOP.art'), b'G04 Modified*\nM02*\n')
                    manifest = json.loads(archive.read('manifest.json'))
                    self.assertEqual(manifest['source_status'], 'REQUIERE_REVISION_AVISOS')
                    self.assertEqual(manifest['status'], 'MODIFICADO_PENDIENTE_REVISION')
                    self.assertTrue(manifest['cam_review_required'])
                    self.assertIn('historial_editor/manifest_original_001.json', archive.namelist())
                    for record in manifest['files']:
                        data = archive.read(record['name'])
                        self.assertEqual(len(data), record['bytes'])
                        self.assertEqual(hashlib.sha256(data).hexdigest(), record['sha256'])
                        self.assertEqual((folder/record['name']).read_bytes(), data)
            self.assertEqual(source.read_bytes(), source_before)

    def test_mismatched_loaded_board_or_corrupt_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = create_source(root, {'top.art': b'original'})
            with self.assertRaisesRegex(ValueError, 'no coincide'):
                with FabricationExport(root/'out', {'top.art': b'other board'}, source): pass
            self.assertEqual(list((root/'out').iterdir()), [])
            with zipfile.ZipFile(source, 'a') as archive:
                # An extra file is allowed; a changed manifest checksum is not.
                archive.writestr('new.txt', 'unmodified extra')
            bad = root/'bad.zip'
            with zipfile.ZipFile(source) as archive, zipfile.ZipFile(bad, 'w') as target:
                for name in archive.namelist():
                    target.writestr(name, b'bad data' if name == 'top.art' else archive.read(name))
            with self.assertRaisesRegex(ValueError, 'manifiesto'):
                with FabricationExport(root/'out', {}, bad): pass
            self.assertEqual(list((root/'out').iterdir()), [])

    def test_reopening_an_edited_zip_continues_revision_and_preserves_previous_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = create_source(root, {'top.art': b'original'})
            with FabricationExport(root/'out', {'top.art': b'original'}, original) as package:
                package.path_for('top.art').write_bytes(b'edit one')
                _, first = package.finish([{'file': 'top.art', 'mode': 'merge'}], {})
            first_bytes = first.read_bytes()
            with FabricationExport(root/'out', {'top.art': b'edit one'}, first) as package:
                package.path_for('top.art').write_bytes(b'edit two')
                _, second = package.finish([{'file': 'top.art', 'mode': 'merge'}], {})
            self.assertEqual(second.name, 'board.rev_fab_v003_edit_v002.zip')
            self.assertEqual(first.read_bytes(), first_bytes)
            with zipfile.ZipFile(second) as archive:
                self.assertEqual(archive.read('top.art'), b'edit two')
                self.assertIn('historial_editor/manifest_original_002.json', archive.namelist())

    def test_failure_and_unsafe_names_leave_no_partial_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(RuntimeError):
                with FabricationExport(root/'out', {'top.art': b'original'}) as package:
                    package.path_for('top.art').write_bytes(b'changed')
                    raise RuntimeError('Conversion failed')
            self.assertEqual(list((root/'out').iterdir()), [])
            bad = root/'bad.zip'
            with zipfile.ZipFile(bad, 'w') as archive: archive.writestr('../outside.art', 'bad')
            with self.assertRaises(ValueError):
                with FabricationExport(root/'out', {}, bad): pass
            self.assertFalse((root/'outside.art').exists())
            with FabricationExport(root/'out', {'top.art': b'original'}) as package:
                with self.assertRaises(ValueError): package.path_for('../outside.art')
                with self.assertRaises(ValueError): package.path_for('manifest.json')

