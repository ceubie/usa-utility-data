from concurrent.futures import ThreadPoolExecutor,as_completed
from collect import ROOT,download
import json
SOURCES=[
('states/ct/dph_water_utility_coordination.html','https://portal.ct.gov/dph/drinking-water/wucc/water-utility-coordinating-committee'),
('states/ct/dph_exclusive_area_changes.html','https://portal.ct.gov/dph/home/drinking-water/wucc/exclusive-service-area-changes?language=en_US'),
('states/ct/deep_water_diversion.html','https://portal.ct.gov/deep/water/diversions/water-diversion-program'),
('states/ct/statewide_water_coordination_summary.pdf','https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/wucc-statewide_10pager-final-3-20.pdf'),
('states/ct/western_wucc_exclusive_areas_2017.pdf','https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/westernesadocument_final20170613.pdf'),
('states/ct/central_wucc_exclusive_areas_2017.pdf','https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/centralesadocument_final20170614.pdf'),
('states/ct/eastern_wucc_exclusive_areas_2017.pdf','https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/easternesa_final20170614.pdf'),
('states/ct/ledyard_esa_modification_2025.pdf','https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/ledyard-esa-modification-letter-and-map-july102025.pdf'),
('states/ct/glastonbury_esa_modification_2019.pdf','https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/bell_st.pdf'),
('states/ct/glastonbury_esa_modification_2018.pdf','https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/mdc-manchester-draft-esa-modification-letter-11-29-2018.pdf'),
('states/ct/suffield_esa_modification_2018.pdf','https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/suffield-esa-modification-letter--map-2718.pdf'),
('states/ct/new_fairfield_esa_modification_2018.pdf','https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/new-fairfield-esa-change.pdf'),
('states/ct/montville_esa_modification_2018.pdf','https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/revised_statement_of_confirmation_scwa_042518.pdf'),
('states/ct/exclusive_service_areas_annual_report_2022.pdf','https://portal.ct.gov/-/media/Departments-and-Agencies/DPH/dph/drinking_water/pdf/SA-P-WUCC-Annual-Report-2022.pdf'),
('documentation/connecticut_dph_water_map_application.json','https://maps.dph.ct.gov/arcgis/sharing/rest/content/items/b8f5c344dfa54cd29b65d11c113bbf1e/data?f=json'),
('documentation/connecticut_dph_drinking_water_webmap.json','https://maps.dph.ct.gov/arcgis/sharing/rest/content/items/74d71d5c084a427287c3b62473c72ff6/data?f=json'),
('documentation/texas_electric_iou_restricted_item.json','https://www.arcgis.com/sharing/rest/content/items/f7edde48d50140fe93a6fd4797693a9c?f=json'),
('documentation/texas_electric_cooperative_restricted_item.json','https://www.arcgis.com/sharing/rest/content/items/8bd7d46e88354017a8cbb6af96c65d0c?f=json'),
('documentation/texas_electric_municipal_restricted_item.json','https://www.arcgis.com/sharing/rest/content/items/60fe2d79f2fc45caa6b2701c182c71fc?f=json'),
('documentation/new_jersey_dep_utility_service.json','https://mapsdep.nj.gov/arcgis/rest/services/Features/Utilities/MapServer?f=json')]
def checked(x):
 r=download(x)
 if r['status']!='downloaded':return r
 p=ROOT/r['path']
 try:
  if p.suffix=='.pdf':
   with p.open('rb') as f: assert f.read(5)==b'%PDF-'
  elif p.suffix=='.json':json.loads(p.read_text(encoding='utf8'))
 except Exception as e:p.unlink();r.update(status='failed',error='Format validation failed: '+str(e))
 return r
if __name__=='__main__':
 rows=[]
 with ThreadPoolExecutor(max_workers=4) as pool:
  for f in as_completed([pool.submit(checked,x) for x in SOURCES]):
   r=f.result();rows.append(r);print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
 (ROOT/'data'/'manifest_round16_files.json').write_text(json.dumps(sorted(rows,key=lambda r:r['path']),indent=2),encoding='utf8')
