from collect import ROOT,download
import json
item=('documentation/arizona_dema_electric_boundaries_source_item.json','https://www.arcgis.com/sharing/rest/content/items/604abd0f9fdb4d33b041316208fff095?f=json')
r=download(item)
if r['status']=='downloaded':
 try:
  j=json.loads((ROOT/r['path']).read_text(encoding='utf8'))
  if 'error' in j:raise ValueError(str(j['error']))
 except Exception as e:(ROOT/r['path']).unlink();r.update(status='failed',error=str(e))
(ROOT/'data'/'manifest_round18_extra.json').write_text(json.dumps([r],indent=2),encoding='utf8')
print(r['status'],r['path'],r.get('error',r.get('bytes')))
