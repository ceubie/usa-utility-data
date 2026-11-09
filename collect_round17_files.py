from concurrent.futures import ThreadPoolExecutor,as_completed
from collect import ROOT,download
import json,zipfile,xml.etree.ElementTree as ET
SOURCES=[
('states/ky/psc_natural_gas_distribution_service_areas_2026.pdf','https://psc.ky.gov/agencies/psc/images/GasDistributionSA2026.pdf'),
('states/ky/psc_maps_and_gis.html','https://psc.ky.gov/Home/Maps'),
('states/fl/collier_potable_water_service_areas_2025.pdf','https://www.collier.gov/files/assets/county/v/1/public-utilities/documents/epmd-planning/resources/potable-water-service-area-map.pdf'),
('states/wa/utility_side_charging_assessment_2024.pdf','https://app.leg.wa.gov/ReportsToTheLegislature/Home/GetPDF?fileName=CommerceReports_2024_Energy_WUSCIA_12-30-24%20Final_bc0013f3-dc1e-401f-91d6-bbea8cace2ec.pdf'),
('states/wa/public_utilities.html','https://wa.gov/health-safety/public-utilities'),
('states/nj/public_water_purveyors_2026_shapefile.zip','https://www.nj.gov/dep/gis/digidownload/zips/OpenData/Util_drinkingwater_PSA_shp.zip'),
('states/nj/public_water_purveyors_2026_geodatabase.zip','https://www.nj.gov/dep/gis/digidownload/zips/OpenData/Util_drinkingwater_PSA.zip'),
('documentation/nj_public_water_purveyors_2026_metadata.xml','https://www.arcgis.com/sharing/rest/content/items/00e7ff046ddb4302abe7b49b2ddee07e/info/metadata/metadata.xml'),
('documentation/nj_public_water_purveyors_2026_item.json','https://www.arcgis.com/sharing/rest/content/items/00e7ff046ddb4302abe7b49b2ddee07e?f=json'),
('documentation/washington_gas_service_webmap.json','https://www.arcgis.com/sharing/rest/content/items/666d5dc97ba94fdfaf61a6d791915791/data?f=json'),
('documentation/washington_gas_service_webmap_item.json','https://www.arcgis.com/sharing/rest/content/items/666d5dc97ba94fdfaf61a6d791915791?f=json'),
('documentation/washington_gas_service_layer_item.json','https://www.arcgis.com/sharing/rest/content/items/83d787563ebc4f409da56645fe89e686?f=json'),
('documentation/utah_electric_service_area_item.json','https://www.arcgis.com/sharing/rest/content/items/92916071272248d48dcd546dd2ec72ec?f=json'),
('documentation/ny_ontario_water_district_restricted_item.json','https://www.arcgis.com/sharing/rest/content/items/5a7bf74c93cb4441b73a848cf3622012?f=json'),
('documentation/fl_collier_water_area_item.json','https://www.arcgis.com/sharing/rest/content/items/023569edfd3e4d58a7536007ace8882a?f=json'),
('documentation/fl_collier_wastewater_area_item.json','https://www.arcgis.com/sharing/rest/content/items/da60c98702c549f195b6e1706ca46f4a?f=json'),
('documentation/fl_lee_water_area_item.json','https://www.arcgis.com/sharing/rest/content/items/6ffb9014f190482da5b2ff77d0f60464?f=json'),
('documentation/louisiana_baton_rouge_electric_areas_catalog.json','https://data.brla.gov/api/views/3dv4-vdqq.json')]
def checked(x):
 r=download(x)
 if r['status']!='downloaded':return r
 p=ROOT/r['path']
 try:
  if p.suffix=='.pdf':
   with p.open('rb') as f: assert f.read(5)==b'%PDF-'
  elif p.suffix=='.json':
   j=json.loads(p.read_text(encoding='utf8'))
   if 'error' in j:raise ValueError(str(j['error']))
  elif p.suffix=='.xml':ET.parse(p)
  elif p.suffix=='.zip':
   with zipfile.ZipFile(p) as z:assert z.testzip() is None
 except Exception as e:p.unlink();r.update(status='failed',error='Format validation failed: '+str(e))
 return r
if __name__=='__main__':
 rows=[]
 with ThreadPoolExecutor(max_workers=5) as pool:
  for f in as_completed([pool.submit(checked,x) for x in SOURCES]):
   r=f.result();rows.append(r);print(r['status'],r['path'],r.get('error',r.get('bytes')),flush=True)
 (ROOT/'data'/'manifest_round17_files.json').write_text(json.dumps(sorted(rows,key=lambda r:r['path']),indent=2),encoding='utf8')
