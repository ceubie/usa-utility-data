"""Acquire state-published utility lookup data, source metadata and reports."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from collect import ROOT, download
import json
SOURCES = [
 ('states/mo/mopsc_utility_locator.html','https://psc.mo.gov/utilitylocator.aspx'),
 ('states/mo/missouri_utility_lookup_historical.csv','https://data.mo.gov/resource/yeiz-h2m2.csv?$limit=50000'),
 ('documentation/missouri_utility_lookup_socrata_metadata.json','https://data.mo.gov/api/views/yeiz-h2m2.json'),
 ('states/mo/mopsc_annual_report_2025.pdf','https://psc.mo.gov/CMSInternetData/Annual%20Reports/PSC%20Annual%20Reports/2025%20PSC%20Annual%20Report.pdf'),
 ('states/mo/ameren_missouri_fact_sheet_2025.pdf','https://www.ameren.com/-/media/missouri-site/Files/AboutUs/AmerenMissouriFactSheet.pdf'),
 ('states/nd/ndpsc_electric_gas_utility_list.html','https://www.psc.nd.gov/jurisdictions/electric-gas'),
 ('states/nd/nd_grid_resiliency_plan_2025.pdf','https://www.ndic.nd.gov/sites/www/files/documents/Transmission-Authority/Publications/ND-Grid-Resiliency-Plan/ND-Grid-Resiliency-Plan-2025.pdf'),
 ('documentation/nm_electric_coop_arcgis_item.json','https://www.arcgis.com/sharing/rest/content/items/0220614f61d64382af9aa2e7dfa84233?f=json'),
 ('documentation/nm_electric_coop_map_service.json','https://gis.doit.nm.gov/nmgis/rest/services/AdministrativeBoundaries/Electric_Coop_Boundaries/MapServer?f=pjson'),
 ('documentation/nm_electric_coop_2025_layer_iteminfo.json','https://gis.doit.nm.gov/nmgis/rest/services/AdministrativeBoundaries/Electric_Coop_Boundaries/MapServer/0/iteminfo?f=json'),
]
rows=[]
with ThreadPoolExecutor(max_workers=4) as pool:
 for f in as_completed([pool.submit(download,x) for x in SOURCES]):
  x=f.result()
  if x['status']=='downloaded' and x['path'].endswith('.json'):
   try:
    body=json.loads((ROOT/x['path']).read_text(encoding='utf8'))
    if isinstance(body,dict) and 'error' in body:
     x.update(status='failed',error='Source returned JSON error: '+json.dumps(body['error']))
   except Exception as exc:
    x.update(status='failed',error='Invalid JSON: '+str(exc))
  rows.append(x);print(x['status'],x['path'],x.get('error',x.get('bytes')),flush=True)
(ROOT/'data'/'manifest_round25.json').write_text(json.dumps(sorted(rows,key=lambda x:x['path']),indent=2),encoding='utf8')
