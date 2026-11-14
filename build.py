# SPDX-License-Identifier: GPL-3.0-only
# AyuGhost: modified source version, 2026-11-14.
# AyuGhost changes maintained by @internetmodel and @skerbio.
# Original feature basis: re:extera by @bleizix and @shikaatux.
# See LICENSE and NOTICE for licensing and attribution.

"""Build the source-only Elyx package using Python's standard library."""
from pathlib import Path
import ast,json,zipfile
ROOT=Path(__file__).resolve().parent
FILES=('refmap.json','metainfo.json','main.py','native.py','policy.py','storage.py','LICENSE','NOTICE','CHANGELOG.md','KNOWN_LIMITATIONS.md','README.md')
def build():
    for name in FILES:
        path=ROOT/name
        if not path.is_file():raise FileNotFoundError(path)
        if path.suffix=='.py':ast.parse(path.read_text(encoding='utf-8'))
    meta=json.loads((ROOT/'metainfo.json').read_text(encoding='utf-8'))
    if meta['id']!='ayughost_source_test':raise ValueError('Unexpected plugin id')
    target=ROOT/'ayughost_source_test.elyx'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name in FILES:
            info=zipfile.ZipInfo(name,date_time=(2026,11,14,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16
            archive.writestr(info,(ROOT/name).read_bytes())
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:raise ValueError('Invalid archive')
        ref=json.loads(archive.read('refmap.json'))
        if ref['main'] not in archive.namelist():raise ValueError('Missing entry point')
    print(target)
if __name__=='__main__':build()
