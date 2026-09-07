"""Copy selected legacy viewer preferences into a fresh Prism Windows profile.

Run with the viewer closed. Existing destination files are never overwritten.
Credentials, browser data, caches and chat transcripts are not copied.
"""
import argparse
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


def import_preferences(source, destination):
    source, destination = source.resolve(), destination.resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('Source and destination must be separate profile directories.')
    if not (source / 'user_settings' / 'settings.xml').is_file():
        raise ValueError('Source does not contain user_settings/settings.xml.')
    global_files = ('settings.xml', 'colors.xml', 'key_bindings.xml', 'ignorable_dialogs.xml')
    account_files = ('settings_per_account.xml', 'toolbars.xml', 'filters.xml',
                     'emoji_floater_state.xml', 'volume_settings.xml')
    candidates = [source / 'user_settings' / name for name in global_files]
    for folder in source.iterdir():
        if folder.is_dir() and (folder / 'settings_per_account.xml').is_file():
            candidates.extend(folder / name for name in account_files)
    copied = skipped = 0
    for src in candidates:
        if not src.is_file():
            continue
        dst = destination / src.relative_to(source)
        if dst.exists():
            skipped += 1
            continue
        tree = ET.parse(src)
        if src.name in ('settings.xml', 'settings_per_account.xml'):
            settings = tree.getroot().find('map')
            # Drop stored installation/profile paths so Prism computes its own.
            # Explicit custom chat locations remain accessible in the old profile.
            path_keys = {'CacheLocation', 'NewCacheLocation', 'CacheLocationTopFolder',
                         'InstantMessageLogPath', 'ClientSettingsFile',
                         'UserSettingsFile', 'PerAccountSettingsFile',
                         'VersionChannelName', 'CmdLineChannel'}
            entries = list(settings)
            for key, value in zip(entries[::2], entries[1::2]):
                legacy_path = any(str(source).casefold() in (node.text or '').replace('/', os.sep).casefold()
                                  for node in value.iter('string'))
                if key.text in path_keys or legacy_path:
                    settings.remove(key)
                    settings.remove(value)
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also protects preferences if the importer is rerun.
        with dst.open('xb') as out:
            if src.name in ('settings.xml', 'settings_per_account.xml'):
                tree.write(out, encoding='utf-8', xml_declaration=True)
            else:
                with src.open('rb') as original:
                    shutil.copyfileobj(original, out)
        copied += 1
    return copied, skipped


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(os.environ['APPDATA']) / 'SecondLife')
    parser.add_argument('--destination', type=Path, default=Path(os.environ['APPDATA']) / 'Prism')
    args = parser.parse_args()
    copied, skipped = import_preferences(args.source, args.destination)
    print(f'Copied {copied} preference files; kept {skipped} existing destination files.')
