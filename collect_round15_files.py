from collect import ROOT,download
from concurrent.futures import ThreadPoolExecutor,as_completed
import json,zipfile
SOURCES=[('states/co/special_districts_all_dola.zip','https://storage.googleapis.com/co-publicdata/dlall.zip'),('states/co/special_districts_water_sanitation_dola.zip','https://storage.googleapis.com/co-publicdata/dlwatersan.zip'),('states/co/special_districts_metro_dola.zip','https://storage.googleapis.com/co-publicdata/dlmetro.zip'),('states/co/dola_gis_data_sources.html','https://demography.dola.colorado.gov/assets/html/gis_data.html'),('states/co/dola_special_district_map.html','https://gis.dola.colorado.gov/CO_SpecialDistrict/'),('states/co/denver_water_distributor_boundaries.pdf','https://www.denverwater.org/sites/default/files/distributor-boundaries.pdf'),('documentation/florida_broward_water_sewer_drainage_map.json','https://www.arcgis.com/sharing/rest/content/items/1b993848662442ccab540062defc5a99/data?f=json'),('documentation/florida_broward_water_sewer_drainage_item.json','https://www.arcgis.com/sharing/rest/content/items/72802779dbd04e01af014e6919f7ad78?f=json'),('states/fl/broward_water_services_website.html','https://www.broward.org/WaterServices')]
def checked(x):
 r=download(x)
 if r['status']!='downloaded':return r
 p=ROOT/r['path']
 try:
  if p.suffix=='.pdf':
   with p.open('rb') as f: assert f.read(5)==b'%PDF-'
  elif p.suffix=='.json':json.loads(p.read_text(encoding='utf8'))
  elif p.suffix=='.zip':
   with zipfile.ZipFile(p) as z: assert z.testzip() is None
 except Exception as e:
  p.unlink();r.update(status='failed',error='Format validation failed: '+str(e))
 return r
if __name__=='__main__':
 rows=[]
 with ThreadPoolExecutor(max_workers=4) as pool:
  for f in as_completed([pool.submit(checked,x) for x in SOURCES]):
   r=f.result();rows.append(r);print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
 (ROOT/'data'/'manifest_round15_files.json').write_text(json.dumps(sorted(rows,key=lambda r:r['path']),indent=2),encoding='utf8')
