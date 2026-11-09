"""Collect official service descriptions, source metadata, and utility reports."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from collect import ROOT, download
import json

SOURCES = [
 ('documentation/va_state_sewer_vdh_item.json', 'https://www.arcgis.com/sharing/rest/content/items/fa9a22d06aa64fc0bc076cb295f18e82?f=json'),
 ('documentation/va_state_sewer_vdh_service.json', 'https://services5.arcgis.com/8CMfd3uYk8d4J22E/ArcGIS/rest/services/VA_Sewer_Service_Area_DEQ_S_2019/FeatureServer?f=json'),
 ('documentation/va_fairfax_sewer_item.json', 'https://www.arcgis.com/sharing/rest/content/items/a0906e5184364ca3afecef163d25bb84?f=json'),
 ('documentation/va_fairfax_gis_disclaimer.html', 'https://www.fairfaxcounty.gov/maps/disclaimer'),
 ('documentation/sc_conway_public_utility_service.json', 'https://gis.cityofconway.com/arcgis/rest/services/WATER_AND_SEWER_MAPS/WATER_AND_SEWER_UTILITY_MAP_FOR_PUBLIC/MapServer?f=json'),
 ('states/sc/ors_energy_risk_assessment_2026.pdf', 'https://ors.sc.gov/sites/scors/files/2026-03/South%20Carolina%20Energy%20Risk%20Assessment_FINAL_508.pdf'),
 ('states/sc/ors_electric_regulated_utilities.html', 'https://ors.sc.gov/regulated-utilities/electric-natural-gas/electric/regulated-electric-utilities'),
 ('states/sc/ors_natural_gas_regulated_companies.html', 'https://ors.sc.gov/regulated-utilities/electric-natural-gas/natural-gas/natural-gas-regulated-companies'),
]

def checked(source):
 result = download(source)
 if result['status'] != 'downloaded':
  return result
 path = ROOT / result['path']
 try:
  if path.suffix == '.pdf':
   with path.open('rb') as f:
    if f.read(5) != b'%PDF-': raise ValueError('Not a PDF')
  if path.suffix == '.json':
   obj = json.loads(path.read_text(encoding='utf8'))
   if isinstance(obj, dict) and 'error' in obj: raise ValueError(str(obj['error']))
 except Exception as exc:
  path.unlink()
  result.update(status='failed', error='Format validation failed: ' + str(exc))
 return result

if __name__ == '__main__':
 rows = []
 with ThreadPoolExecutor(max_workers=5) as pool:
  for future in as_completed([pool.submit(checked, source) for source in SOURCES]):
   row = future.result()
   rows.append(row)
   print(row['status'], row['path'], row.get('error', row.get('bytes')), flush=True)
 (ROOT / 'data' / 'manifest_round21_files.json').write_text(json.dumps(sorted(rows, key=lambda r: r['path']), indent=2), encoding='utf8')
