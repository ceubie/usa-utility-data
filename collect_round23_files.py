"""Download original Wisconsin and Hawaii utility source metadata and reports."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from collect import ROOT, download
import json

SOURCES = [
 ('states/hi/maui_water_shortage_plan_2024_alternate.pdf', 'https://waterresources.mauicounty.gov/DocumentCenter/View/768/Maui_DWS_WSCP_2024'),
 ('states/hi/maui_dws_annual_report_fy2025.pdf', 'https://www.mauicounty.gov/DocumentCenter/View/161180/FY2025-Annual-Report'),
 ('states/hi/maui_west_system_capacity_2025.pdf', 'https://www.mauicounty.gov/DocumentCenter/View/156461/Max-Reliable-Capacity-WEST-SIDE'),
 ('states/hi/maui_central_system_capacity_2025.pdf', 'https://www.mauicounty.gov/DocumentCenter/View/155090/Maximum-Reliable-Capacity-Analysis-2025-AUGUST-REVISE-20250826'),
 ('states/hi/maui_upcountry_system_capacity_2025.pdf', 'https://www.mauicounty.gov/DocumentCenter/View/155068/Max-Reliable-Capacity-Upcountry-20250826'),
 ('documentation/wi_carpc_sewer_areas_item.json', 'https://www.arcgis.com/sharing/rest/content/items/8d95d582e5fe47b79044cdca8aff98ca?f=json'),
 ('documentation/wi_carpc_sewer_amendments_item.json', 'https://www.arcgis.com/sharing/rest/content/items/a7a231fe1948423a81fae6fca3b005f5?f=json'),
 ('documentation/wi_carpc_sewer_areas_service.json', 'https://services1.arcgis.com/4NZ4Ghri2AQmNOuO/arcgis/rest/services/Urban_Service_Area_09242021/FeatureServer?f=json'),
 ('documentation/wi_carpc_sewer_amendments_service.json', 'https://services1.arcgis.com/4NZ4Ghri2AQmNOuO/arcgis/rest/services/SSAA_update_10182022/FeatureServer?f=json'),
 ('documentation/wi_sewrpc_regional_sewer_item.json', 'https://www.arcgis.com/sharing/rest/content/items/126dece4390645d8b761cd8eaabf2493?f=json'),
 ('documentation/wi_sewrpc_waukesha_item.json', 'https://www.arcgis.com/sharing/rest/content/items/35e6afd436b84e1088457ba6afa8a49a?f=json'),
 ('documentation/wi_sewrpc_regional_sewer_service.json', 'https://services3.arcgis.com/dZlu5nJgfmCUXRzB/arcgis/rest/services/Sewer_Service_Areas/FeatureServer?f=json'),
 ('documentation/wi_washington_county_plan_service.json', 'https://maps.washcowisco.gov/server/rest/services/CommunityDevelopment/ComprehensivePlan/MapServer?f=json'),
 ('documentation/wi_caledonia_district_item.json', 'https://www.arcgis.com/sharing/rest/content/items/ea9017f289f44b07a08a0a217d971617?f=json'),
 ('documentation/wi_caledonia_district_service.json', 'https://services3.arcgis.com/eTwbJcqmqhBzmOfs/arcgis/rest/services/Caledonia_District_Overlays/FeatureServer?f=json'),
 ('states/wi/dnr_sewer_service_area_planning.html', 'https://dnr.wisconsin.gov/topic/SurfaceWater/SSAPlanning.html'),
 ('states/wi/capital_area_sewer_service_planning.html', 'https://www.capitalarearpc.org/water-quality/service-areas/'),
 ('states/wi/sewrpc_sanitary_sewer_planning.html', 'https://www.sewrpc.org/Local-Planning/Sanitary-Sewer-Service-Area-Planning'),
 ('documentation/hi_maui_water_service_item.json', 'https://www.arcgis.com/sharing/rest/content/items/3fd99ed11e46426686e55b2bdaf5807e?f=json'),
 ('documentation/hi_maui_water_service.json', 'https://services3.arcgis.com/fsrDo0QMPlK9CkZD/arcgis/rest/services/WaterServiceAreas/FeatureServer?f=json'),
 ('documentation/hi_maui_recycled_water_item.json', 'https://www.arcgis.com/sharing/rest/content/items/6cbd5cf5be394ac48cebe905d4baf775?f=json'),
 ('documentation/hi_maui_recycled_water_service.json', 'https://services3.arcgis.com/fsrDo0QMPlK9CkZD/arcgis/rest/services/RW_Customers/FeatureServer?f=json'),
 ('documentation/hi_maui_sewer_system_item.json', 'https://www.arcgis.com/sharing/rest/content/items/5fc570de6ae64b29b181c1235fc331fb?f=json'),
 ('documentation/hi_maui_sewer_system_service.json', 'https://services3.arcgis.com/fsrDo0QMPlK9CkZD/arcgis/rest/services/Sewer_System_Full/FeatureServer?f=json'),
 ('states/hi/maui_water_shortage_conservation_plan_oct2025.pdf', 'https://www.mauicounty.gov/DocumentCenter/View/156111/Maui_DWS_WSCP_2024_UpdatedOct2025'),
 ('states/hi/cwrm_lahaina_water_system_permit_summary_nov2025.pdf', 'https://files.hawaii.gov/dlnr/cwrm/publishedreports/PR202502.pdf'),
 ('states/hi/hawaii_water_service_areas.html', 'https://www.hawaiiwaterservice.com/about/company-information/'),
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
 (ROOT / 'data' / 'manifest_round23_files.json').write_text(json.dumps(sorted(rows, key=lambda r: r['path']), indent=2), encoding='utf8')
