"""Archive Catalyst's raw FERC input packages with Zenodo metadata and checksums.

These are third-party snapshots of agency-reported filings, not live FERC data.
Record IDs are pinned so that metadata and files remain a consistent release.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from collect import ROOT, download
import hashlib, json, time

RECORDS = {'1':'22172378', '2':'23296841', '6':'21965243',
           '60':'19947282', '714':'21738524'}
MANIFEST = ROOT / 'data' / 'manifest_round24_ferc.json'

def write_manifest(rows):
 temp = MANIFEST.with_suffix('.json.tmp')
 temp.write_text(json.dumps(sorted(rows, key=lambda x: x['path']), indent=2), encoding='utf8')
 # Windows readers or antivirus can briefly lock the destination. Preserve the
 # temporary manifest and retry rather than abandoning the collection at once.
 for attempt in range(30):
  try:
   temp.replace(MANIFEST)
   break
  except PermissionError:
   if attempt == 29: raise
   time.sleep(0.5)

def md5_file(path):
 h = hashlib.md5()
 with path.open('rb') as f:
  for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
 return h.hexdigest()

def fetch_file(spec):
 form, record, item = spec
 row = download(('ferc/raw/form' + form + '/' + item['key'], item['links']['self']))
 row['zenodo_record'] = record
 row['publisher_checksum'] = item['checksum']
 row['publisher_size'] = item['size']
 if row['status'] == 'downloaded':
  path = ROOT / row['path']
  actual = md5_file(path)
  row['md5'] = actual
  if item['checksum'] != 'md5:' + actual or item['size'] != row['bytes']:
   row.update(status='failed', error='Mismatch against Zenodo record checksum or size')
 return row

if __name__ == '__main__':
 rows = []
 specs = []
 for form, record in RECORDS.items():
  row = download(('documentation/ferc_form' + form + '_zenodo_record_' + record + '.json',
                  'https://zenodo.org/api/records/' + record))
  rows.append(row); write_manifest(rows)
  print(row['status'], row['path'], row.get('error', row.get('bytes')), flush=True)
  if row['status'] != 'downloaded': continue
  meta = json.loads((ROOT / row['path']).read_text(encoding='utf8'))
  if str(meta.get('id')) != record: raise ValueError('Unexpected Zenodo record ID')
  for item in meta['files']:
   if item['key'].endswith('.zip') or item['key'] == 'datapackage.json':
    specs.append((form, record, item))
 with ThreadPoolExecutor(max_workers=4) as pool:
  for future in as_completed([pool.submit(fetch_file, spec) for spec in specs]):
   row = future.result(); rows.append(row); write_manifest(rows)
   print(row['status'], row['path'], row.get('error', row.get('bytes')), flush=True)
