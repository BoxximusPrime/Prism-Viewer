import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location(
    'importer', Path(__file__).parents[1] / 'import_prism_preferences.py')
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


class ImportPreferencesTest(unittest.TestCase):
    def test_import_is_selective_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, dest = root / 'SecondLife', root / 'Prism'
            (source / 'user_settings').mkdir(parents=True)
            original = b'<llsd><map><key>BoxxyAOEnabled</key><map><key>Value</key><boolean>true</boolean></map><key>CacheLocation</key><map><key>Value</key><string>old cache</string></map></map></llsd>'
            (source / 'user_settings/settings.xml').write_bytes(original)
            (source / 'user_settings/bin_conf.dat').write_bytes(b'credentials')
            account = source / 'test_resident'
            account.mkdir()
            (account / 'settings_per_account.xml').write_bytes(original)
            (account / 'toolbars.xml').write_text('<toolbars/>')
            (account / 'chat.txt').write_text('private history')
            self.assertEqual(importer.import_preferences(source, dest), (3, 0))
            self.assertFalse((dest / 'user_settings/bin_conf.dat').exists())
            self.assertFalse((dest / 'test_resident/chat.txt').exists())
            settings = ET.parse(dest / 'user_settings/settings.xml')
            self.assertEqual([k.text for k in settings.findall('./map/key')], ['BoxxyAOEnabled'])
            self.assertEqual((source / 'user_settings/settings.xml').read_bytes(), original)
            saved = dest / 'user_settings/settings.xml'
            saved.write_text('existing preferences')
            self.assertEqual(importer.import_preferences(source, dest), (0, 3))
            self.assertEqual(saved.read_text(), 'existing preferences')
            with self.assertRaises(ValueError):
                importer.import_preferences(source, source / 'nested')


if __name__ == '__main__':
    unittest.main()
