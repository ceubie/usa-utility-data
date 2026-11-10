"""Preserve agency maps, reports, and source metadata for round 20."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from collect import ROOT, download
import json

SOURCES = [
 ('documentation/nc_greensboro_water_resources_gis_service.json', 'https://gis.greensboro-nc.gov/arcgis/rest/services/WaterResources/GeneralBasemapNoOrthos_MS/MapServer?f=json'),
 ('states/il/icc_2025_electric_gas_water_sewer_report.pdf', 'https://icc.illinois.gov/downloads/public/en/2025%20Electricity%20Gas%20Water%20Sewer%20Utilities%20Report.pdf'),
 ('states/il/illinois_energy_association_gas_2015_map.pdf', 'https://ilenergyassn.org/wp-content/uploads/Natural-Gas-Utilities-Illinois-political-map-2015.pdf'),
 ('states/il/illinois_energy_association_gas_map.html', 'https://ilenergyassn.org/illinois-natural-gas-utilities-map/'),
 ('states/il/icc_public_utilities.html', 'https://www.icc.illinois.gov/publicutility/'),
 ('states/co/metro_water_recovery_members_2023_map.pdf', 'https://www.metrowaterrecovery.com/wp-content/uploads/2024/02/MemberBreakDown2023.pdf'),
 ('states/co/metro_water_recovery_service_area.html', 'https://www.metrowaterrecovery.com/about-us/our-service-area/'),
 ('documentation/il_broadband_boundaries_item.json', 'https://www.arcgis.com/sharing/rest/content/items/675906ae06b5460296154760b7fb1367?f=json'),
 ('documentation/il_broadband_boundaries_service.json', 'https://services.arcgis.com/R0IGaIgf2sox9aCY/ArcGIS/rest/services/IL_Boundary_Layers/FeatureServer?f=json'),
 ('documentation/ny_tioga_gis_item.json', 'https://www.arcgis.com/sharing/rest/content/items/64282a89e0bb45b480f8d0e122b00fba?f=json'),
 ('documentation/ny_tioga_gis_service.json', 'https://services3.arcgis.com/PvkAiSMFS7cpxnJP/arcgis/rest/services/GIT_New/FeatureServer?f=json'),
 ('documentation/co_metro_water_recovery_gis_item.json', 'https://gis.metrowaterrecovery.com/portal/sharing/rest/content/items/cab296da1ae24ee78b902d548b15ffef?f=json'),
 ('documentation/co_metro_water_recovery_gis_service.json', 'https://gis.metrowaterrecovery.com/hosting/rest/services/MetroMemebers/MapServer?f=json'),
 ('documentation/co_metro_water_recovery_webmap_app.json', 'https://gis.metrowaterrecovery.com/portal/sharing/rest/content/items/e4e412ef62294f34b63680e4b2b49eda/data?f=json'),
]

def checked(source):
 result = download(source)
 if result['status'] != 'downloaded':
  return result
 path = ROOT / result['path']
 try:
  if path.suffix == '.pdf' and path.read_bytes()[:5] != b'%PDF-':
   raise ValueError('Not a PDF')
  if path.suffix == '.json':
   obj = json.loads(path.read_text(encoding='utf8'))
   if isinstance(obj, dict) and 'error' in obj:
    raise ValueError(str(obj['error']))
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
 (ROOT / 'data' / 'manifest_round20_files.json').write_text(json.dumps(sorted(rows, key=lambda r: r['path']), indent=2), encoding='utf8')
