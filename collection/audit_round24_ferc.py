"""Audit completed Catalyst FERC archive downloads against pinned Zenodo metadata.

Safe to run while the collector is active: incomplete .partial files are ignored.
The resulting manifest is a point-in-time audit, not a live inventory.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

ROOT = Path(__file__).resolve().parent
RECORDS = {'1':'22172378', '2':'23296841', '6':'21965243',
           '60':'19947282', '714':'21738524'}
rows = []
for form, record in RECORDS.items():
    meta_path = ROOT / 'data' / 'documentation' / f'ferc_form{form}_zenodo_record_{record}.json'
    meta = json.loads(meta_path.read_text(encoding='utf8'))
    for item in meta['files']:
        if not (item['key'].endswith('.zip') or item['key'] == 'datapackage.json'):
            continue
        path = ROOT / 'data' / 'ferc' / 'raw' / f'form{form}' / item['key']
        row = {'path': path.relative_to(ROOT).as_posix(), 'url': item['links']['self'],
               'zenodo_record': record, 'publisher_checksum': item['checksum'],
               'publisher_size': item['size'], 'audited_utc': datetime.now(timezone.utc).isoformat()}
        if not path.is_file():
            row['status'] = 'not_present_at_audit'
        else:
            md5, sha = hashlib.md5(), hashlib.sha256()
            with path.open('rb') as f:
                for block in iter(lambda: f.read(1024*1024), b''):
                    md5.update(block); sha.update(block)
            row.update(bytes=path.stat().st_size, md5=md5.hexdigest(), sha256=sha.hexdigest())
            row['status'] = ('verified' if row['bytes'] == item['size'] and
                             item['checksum'] == 'md5:' + row['md5'] else 'mismatch')
        rows.append(row)
        print(row['status'], row['path'], flush=True)
out = ROOT / 'data' / 'manifest_round24_ferc_audit.json'
out.write_text(json.dumps(rows, indent=2), encoding='utf8')
