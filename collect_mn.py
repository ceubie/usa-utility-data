"""Download Minnesota's published electric service-area GeoPackage and metadata."""
import json,sqlite3
from pathlib import Path
from collect import download
SOURCES=[
 ('states/mn/electric_service_areas.gpkg','https://operations.gis.data.mn.gov/api/publicdownload/download/518/util_eusa.gpkg'),
 ('states/mn/electric_service_areas_metadata.xml','https://www.arcgis.com/sharing/rest/content/items/f1b545bcc02f42fcb9b9eada85c32494/info/metadata/metadata.xml'),
]
results=[download(x) for x in SOURCES]
for r in results:
 if r['status']=='downloaded' and r['path'].endswith('.gpkg'):
  try:
   with sqlite3.connect('file:'+str(Path(r['path']).resolve())+'?mode=ro',uri=True) as db:
    r['gpkg_layers']=db.execute('select table_name,data_type from gpkg_contents').fetchall()
    if db.execute('pragma quick_check').fetchone()[0]!='ok': raise ValueError('SQLite check failed')
  except Exception as e: r.update(status='invalid',error=str(e))
 print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
(Path(__file__).parent/'data/manifest_mn.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
