"""Preserve utility webmaps, source descriptions, and published usage terms."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from collect import ROOT, download
import json

SOURCES = [
 ('documentation/wa_king_county_sewer_service_item.json', 'https://www.arcgis.com/sharing/rest/content/items/c03ea3481bb74540a26b132f265ad49a?f=json'),
 ('documentation/wa_king_county_sewer_service.json', 'https://services.arcgis.com/Ej0PsM5Aw677QF1W/arcgis/rest/services/SEWER_SERV_AREA_2871/FeatureServer?f=json'),
 ('documentation/wa_king_county_gis_terms.html', 'https://kingcounty.gov/en/dept/kcit/data-information-services/gis-center/about/terms-conditions-copyrights'),
 ('documentation/wa_king_county_sewer_catalog.html', 'https://www5.kingcounty.gov/sdc?Layer=SEWER_SERV_AREA'),
 ('states/sc/greer_cpw_electric_service_area_2024.pdf', 'https://www.greercpw.com/wp-content/uploads/2024/04/electric_service_area_2024.pdf'),
 ('states/sc/greer_cpw_electricity.html', 'https://www.greercpw.com/utilities/electricity/'),
 ('states/sc/greer_cpw_natural_gas.html', 'https://www.greercpw.com/utilities/natural-gas/'),
 ('states/sc/greer_cpw_water.html', 'https://www.greercpw.com/utilities/water/'),
 ('documentation/epa_noncommunity_water_methods.pdf', 'https://www.arcgis.com/sharing/rest/content/items/29cee3c00b8444a7be7071f0f91ef104/data'),
 ('documentation/epa_public_water_areas_v3_data_dictionary.pdf', 'https://www.epa.gov/system/files/documents/2026-03/data-dictionary_v3_03162026.pdf'),
 ('documentation/epa_public_water_areas_fact_sheet_2026.pdf', 'https://www.epa.gov/system/files/documents/2026-03/epa-service-area-boundary-fact-sheet-rev-march-2026.pdf'),
 ('documentation/epa_public_water_service_areas.html', 'https://www.epa.gov/ground-water-and-drinking-water/public-water-system-service-areas'),
 ('documentation/epa_noncommunity_water_service_item.json', 'https://www.arcgis.com/sharing/rest/content/items/95b861a3bb0d4fa6b5eb84494b135c51?f=json'),
 ('documentation/epa_noncommunity_water_service.json', 'https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/Transient_and_Non_Transient_Non_Community_Water_System_Service_Areas/FeatureServer?f=json'),
 ('documentation/or_clean_water_services_boundaries_item.json', 'https://www.arcgis.com/sharing/rest/content/items/a2c11f98f3e84b33ac60f5e6ffc75f26?f=json'),
 ('documentation/or_clean_water_services_boundaries_service.json', 'https://services1.arcgis.com/mGbDfjleLhk48K7A/ArcGIS/rest/services/Clean_Water_Services_General_Boundaries/FeatureServer?f=json'),
 ('documentation/sc_greer_cpw_service_areas.json', 'https://maps.greercpw.com/server/rest/services/Customer/Service_Areas/MapServer?f=json'),
 ('documentation/or_portland_sewer_gis_service.json', 'https://www.portlandmaps.com/arcgis/rest/services/Public/Utilities_Sewer/MapServer?f=json'),
 ('documentation/or_portland_open_data_terms.pdf', 'https://www.portlandmaps.com/bps/arpa/tos.pdf'),
 ('documentation/or_eugene_wastewater_gis_service.json', 'https://gis.eugene-or.gov/arcgis/rest/services/PWE/Wastewater/MapServer?f=json'),
 ('documentation/or_eugene_gis_disclaimer.html', 'https://www.eugene-or.gov/1352/Maps-and-GIS-Disclaimer'),
 ('documentation/sc_summerville_cpw_service_item.json', 'https://www.arcgis.com/sharing/rest/content/items/3f04bc440c204f4ca6eba14c03040925?f=json'),
 ('documentation/sc_summerville_cpw_service.json', 'https://services5.arcgis.com/sfU39kIu21kNLvKK/arcgis/rest/services/SCPW_Service_Area_Map/FeatureServer?f=json'),
 ('documentation/sc_summerville_cpw_webmap.json', 'https://www.arcgis.com/sharing/rest/content/items/906e357c586642c0af3576d3e6209d09/data?f=json'),
 ('states/sc/summerville_cpw_service_area.html', 'https://www.summervillecpw.com/servicearea'),
 ('states/sc/summerville_cpw_availability.html', 'https://www.summervillecpw.com/index.asp?SEC=CD7EF2AA-CFFC-4097-B050-613B04AF8153&Type=QUICKFORM&mobile=false'),
 ('states/or/portland_sewer_connection.html', 'https://www.portland.gov/bds/city-sewer'),
 ('states/or/eugene_wastewater.html', 'https://www.eugene-or.gov/186/Wastewater'),
]

def checked(source):
 result = download(source)
 if result['status'] != 'downloaded': return result
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
   row = future.result(); rows.append(row)
   print(row['status'], row['path'], row.get('error', row.get('bytes')), flush=True)
 (ROOT / 'data' / 'manifest_round22_files.json').write_text(json.dumps(sorted(rows, key=lambda r: r['path']), indent=2), encoding='utf8')
