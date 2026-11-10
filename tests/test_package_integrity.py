"""A renamed or extra layer must not silently join a manufacturing release."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from package_integrity import validate_manifest,read_archive
from fabrication_export import FabricationExport
from pcb_project import _payload


class PackageIntegrityTests(unittest.TestCase):
    def manifest(self):
        raw=b'original layer'
        return {'top.gto':raw},dict(files=[dict(path='top.gto',name='top.gto',sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))])

    def test_path_alias_is_supported_and_inconsistent_alias_is_rejected(self):
        payload,m=self.manifest()
        self.assertEqual(validate_manifest(payload,m)[0]['name'],'top.gto')
        del m['files'][0]['name'];validate_manifest(payload,m)
        m['files'][0]['name']='other.gto'
        with self.assertRaisesRegex(ValueError,'discrepantes'):validate_manifest(payload,m)

    def test_added_fabrication_layer_is_rejected_by_import_and_derived_export(self):
        payload,m=self.manifest();payload['other-release.gbl']=b'foreign copper'
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'mixed.zip'
            with zipfile.ZipFile(source,'w') as z:
                for name,raw in payload.items():z.writestr(name,raw)
                z.writestr('manifest.json',json.dumps(m))
            with self.assertRaisesRegex(ValueError,'no declarado'):_payload(source)
            from panel_model import load_references
            refs,errors=load_references([source]);self.assertFalse(refs);self.assertTrue(errors)
            with self.assertRaisesRegex(ValueError,'no declarado'):
                with FabricationExport(Path(tmp)/'output',{},source):pass
            self.assertFalse(list((Path(tmp)/'output').iterdir()))

    def test_complete_inventory_and_legacy_metadata(self):
        payload,m=self.manifest();payload['LEEME_FABRICACION.txt']=b'legacy readme'
        validate_manifest(payload,m)
        with self.assertRaisesRegex(ValueError,'no declarado'):validate_manifest(payload,m,True)
        m['files'].append(dict(m['files'][0]))
        with self.assertRaisesRegex(ValueError,'duplicado'):validate_manifest(payload,m)

    def test_corrupt_archive_reports_a_user_readable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'broken.zip';source.write_bytes(b'not a zip')
            with self.assertRaisesRegex(ValueError,'No se puede leer'):read_archive(source)
            with self.assertRaisesRegex(ValueError,'No se puede leer'):
                with FabricationExport(Path(tmp)/'output',{},source):pass


if __name__=='__main__':unittest.main()
