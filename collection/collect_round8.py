"""Collect federal wind-turbine data and its documentation."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
from collect import download

SOURCES=[
 ('electric/usgs_uswtdb_latest_csv.zip','https://energy.usgs.gov/uswtdb/assets/data/uswtdbCSV.zip'),
 ('electric/uswtdb_decommissioned_v9_1_20260928.csv','https://eta-publications.lbl.gov/sites/default/files/2026-10/uswtdb_decommissioned_20260928.csv'),
 ('documentation/uswtdb_v9_1_memo.pdf','https://eta-publications.lbl.gov/sites/default/files/2026-10/uswtdb_v9_1_20260928_memo.pdf'),
 ('documentation/uswtdb_v9_1_codebook.xlsx','https://eta-publications.lbl.gov/sites/default/files/2026-10/uswtdb_v9_1_20260928_codebook.xlsx'),
 ('documentation/uswtdb_usgs_metadata.xml','https://data.usgs.gov/datacatalog/metadata/USGS.57bdfd8fe4b03fd6b7df5ff9.xml'),
]
def validated(source):
 r=download(source)
 if r['status']=='downloaded' and r['path'].endswith('.pdf'):
  with (Path(__file__).parent/r['path']).open('rb') as f:
   if not f.read(8).startswith(b'%PDF-'):r.update(status='invalid',error='Missing PDF signature')
 print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
 return r
if __name__=='__main__':
 with ThreadPoolExecutor(max_workers=4) as p:results=list(p.map(validated,SOURCES))
 (Path(__file__).parent/'data/manifest_round8.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
