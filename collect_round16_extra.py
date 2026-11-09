from concurrent.futures import ThreadPoolExecutor,as_completed
from collect import ROOT,download
import json
SOURCES=[('documentation/connecticut_dph_exclusive_areas_item.json','https://maps.dph.ct.gov/arcgis/sharing/rest/content/items/930ee45f21034a3caa180d042d456df7?f=json'),('documentation/connecticut_dph_exclusive_area_changes_item.json','https://maps.dph.ct.gov/arcgis/sharing/rest/content/items/1cca9754e1d941bda8a04821b1909445?f=json'),('documentation/connecticut_dph_community_water_areas_item.json','https://maps.dph.ct.gov/arcgis/sharing/rest/content/items/7d8d4f8022954143a1de2a7beb6e4f3b?f=json'),('documentation/connecticut_dph_drinking_watersheds_item.json','https://maps.dph.ct.gov/arcgis/sharing/rest/content/items/76d8e5c016a44803b88247ac6c87fb45?f=json'),('documentation/connecticut_connected_sewer_areas_item.json','https://www.arcgis.com/sharing/rest/content/items/335ee4ab4a474a50bdc16179d1883930?f=json')]
rows=[]
with ThreadPoolExecutor(max_workers=4) as pool:
 for f in as_completed([pool.submit(download,x) for x in SOURCES]):
  r=f.result()
  if r['status']=='downloaded':
   try:
    obj=json.loads((ROOT/r['path']).read_text(encoding='utf8'))
    if 'error' in obj: raise ValueError(str(obj['error']))
   except Exception as e:(ROOT/r['path']).unlink();r.update(status='failed',error='Invalid JSON: '+str(e))
  rows.append(r);print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
(ROOT/'data'/'manifest_round16_extra.json').write_text(json.dumps(sorted(rows,key=lambda r:r['path']),indent=2),encoding='utf8')
