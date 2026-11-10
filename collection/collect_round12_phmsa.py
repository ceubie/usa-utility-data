"""Retrieve the published, raw PHMSA archive via its documented S3 mirror."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib
import json
from collect import ROOT, download

BASE = 'https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/zenodo/phmsagas/10.5281-zenodo.23296837/'
DIRECTORY = 'gas/phmsa_zenodo_23296837/'

def verified(item):
    result = download((DIRECTORY + item['name'], BASE + item['name']))
    if result['status'] == 'downloaded':
        path = ROOT / result['path']
        checksum = hashlib.md5(path.read_bytes()).hexdigest()
        result['archive_expected_md5'] = item['hash']
        result['archive_expected_bytes'] = item['bytes']
        result['archive_md5'] = checksum
        if checksum != item['hash'] or result['bytes'] != item['bytes']:
            path.unlink()
            result.update(status='failed', error='Archive checksum or size mismatch')
    return result

if __name__ == '__main__':
    manifest=[]
    meta = download((DIRECTORY + 'datapackage.json', BASE + 'datapackage.json'))
    manifest.append(meta)
    if meta['status'] != 'downloaded':
        raise SystemExit('Failed to retrieve PHMSA archive datapackage: '+str(meta))
    package = json.loads((ROOT / meta['path']).read_text(encoding='utf-8'))
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(verified, x) for x in package['resources']]):
            row = future.result(); manifest.append(row)
            print(row['status'],row['path'],row.get('bytes',row.get('error')),flush=True)
    (ROOT/'data'/'manifest_round12_phmsa.json').write_text(json.dumps(sorted(manifest,key=lambda r:r['path']),indent=2),encoding='utf-8')
