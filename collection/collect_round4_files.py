"""Download official agency directories, map documents, and catalog metadata."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
from collect import download
SOURCES = [
 ('states/ct/pws_community.xlsx','https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/excel/pws_community.xlsx'),
 ('states/ct/pws_nontransient_noncommunity.xlsx','https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/excel/pws_ntnc.xlsx'),
 ('states/ct/pws_transient_noncommunity.xlsx','https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/excel/pws_tnc.xlsx'),
 ('states/ky/electric_distribution_service_areas_2024.pdf','https://psc.ky.gov/agencies/psc/images/electric_service_areas_legal_size_map.pdf'),
 ('states/nh/electric_franchise_areas_2022.pdf','https://www.energy.nh.gov/sites/g/files/ehbemt551/files/2022-01/enforcement-franchise-map-electric.pdf'),
 ('states/ri/rie_service_area_accounts_filing_2026.pdf','https://ripuc.ri.gov/sites/g/files/xkgbur841/files/2026-02/25-45-GE%20RIE%20Resps%20DIV%20Set%203%20%28Bk%201%29%20%28DIV%203-1%20to%203-41%29%20%28Public%29.pdf'),
 ('documentation/indiana_electric_territories_item.json','https://www.arcgis.com/sharing/rest/content/items/9573d22f7d544b6d82e4c4c483868d52?f=json'),
 ('documentation/massachusetts_water_areas_item.json','https://www.arcgis.com/sharing/rest/content/items/98bd3103c0744fe1afb77751da4f2f69?f=json'),
 ('documentation/massachusetts_sewer_areas_item.json','https://www.arcgis.com/sharing/rest/content/items/a2f07c0cf4a841f78ed74bda97b19cd5?f=json'),
]
if __name__=='__main__':
 with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(download,SOURCES))
 for r in results:
  if r['status']=='downloaded' and r['path'].endswith('.pdf'):
   if not (Path(__file__).parent/r['path']).read_bytes().startswith(b'%PDF-'): r.update(status='invalid',error='Missing PDF signature')
  print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
 (Path(__file__).parent/'data/manifest_round4_files.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
