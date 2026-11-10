from concurrent.futures import ThreadPoolExecutor,as_completed
from collect import ROOT,download
import json
SOURCES=[
 ('states/md/frederick_water_and_sewer_plan_2026.pdf','https://frederickcountymd.gov/DocumentCenter/View/348978/Water--Sewerage-Plan'),
 ('states/md/frederick_water_sewer_planning.html','https://frederickcountymd.gov/107/Engineering-Planning'),
 ('documentation/mn_metc_sewersheds_metadata.html','https://resources.gisdata.mn.gov/pub/gdrs/data/pub/us_mn_state_metc/util_sanitary_sewersheds/metadata/metadata.html'),
 ('documentation/mn_metc_interceptors_metadata.html','https://resources.gisdata.mn.gov/pub/gdrs/data/pub/us_mn_state_metc/util_sewer_interceptors/metadata/metadata.html'),
 ('documentation/mn_metc_treatment_facilities_metadata.html','https://resources.gisdata.mn.gov/pub/gdrs/data/pub/us_mn_state_metc/util_wastewater_treatment_plants/metadata/metadata.html'),
 ('documentation/mn_metc_musa_composite_metadata.html','https://resources.gisdata.mn.gov/pub/gdrs/data/pub/us_mn_state_metc/plan_musa_composite/metadata/metadata.html'),
 ('documentation/mn_metc_wastewater_gis_service.json','https://arcgis.metc.state.mn.us/arcgis/rest/services/LPH/Wastewater_ES/MapServer?f=json'),
 ('documentation/mn_metc_musa_gis_service.json','https://arcgis.metc.state.mn.us/arcgis/rest/services/LPH/Wastewater_MUSA/MapServer?f=json'),
 ('documentation/md_frederick_water_sewer_gis_service.json','https://fcgis.frederickcountymd.gov/server/rest/services/PlanningAndPermitting/WaterSewerServiceAreas/MapServer?f=json'),
 ('states/mn/metc_gis_download_handbook.html','https://handbook.metrocouncil.org/resources/download-gis-data/')]
def checked(x):
 r=download(x)
 if r['status']!='downloaded':return r
 p=ROOT/r['path']
 try:
  if p.suffix=='.pdf':
   with p.open('rb') as f: assert f.read(5)==b'%PDF-'
  if p.suffix=='.json':
   j=json.loads(p.read_text(encoding='utf8'))
   if 'error' in j:raise ValueError(str(j['error']))
 except Exception as e:p.unlink();r.update(status='failed',error='Format validation failed: '+str(e))
 return r
if __name__=='__main__':
 rows=[]
 with ThreadPoolExecutor(max_workers=5) as pool:
  for f in as_completed([pool.submit(checked,x) for x in SOURCES]):
   r=f.result();rows.append(r);print(r['status'],r['path'],r.get('error',r.get('bytes')),flush=True)
 (ROOT/'data'/'manifest_round19_files.json').write_text(json.dumps(sorted(rows,key=lambda r:r['path']),indent=2),encoding='utf8')
